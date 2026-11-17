#!/usr/bin/env python3
"""Regression: a map pin must search its own point, not its label.

The original failure (reproduced 2026-11-16): a pin dropped in Kolkata carried
the label "Simla" — a real Kolkata locality — and `runPin` searched
`pin.display || pin.label` by name. Nominatim resolved "Simla" to Shimla,
Himachal Pradesh, so the round searched a different state ("found 13, kept 0")
and the panel said nothing about why. When the label could not be geocoded at
all the search died on "Could not find that location".

Two fixes are pinned here:
  1. `/api/map/search` accepts `lat`/`lon` and the workflow uses them, so a pin
     never depends on a geocode.
  2. Source failures reach the panel as copy that says what to do, never as a
     raw provider string such as "… is not supported".

Run: "E:/python.exe" -X utf8 tests/test_map_pin_coords.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import map_search, workflows  # noqa: E402


class _Recorder:
    """Capture calls made to a module attribute, with a canned answer."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _quiet_other_sources():
    """Make the workflow's failover stage inert and offline."""
    import agents.training_source as training_source
    training_source.available = lambda: False
    import agents.gmaps_source as gmaps
    gmaps.available = lambda: False


def check_variants_extract_the_place():
    got = map_search._geocode_variants("coaching centres in Bandel")
    assert got[0] == "coaching centres in Bandel", got
    assert "Bandel" in got, got
    got2 = map_search._geocode_variants("Howrah, West Bengal, India")
    assert got2[0] == "Howrah, West Bengal, India" and "India" in got2, got2
    assert map_search._geocode_variants("") == []


def check_geocode_retries_with_the_place():
    """The phrase fails at Nominatim; the town inside it must still resolve."""
    seen = []

    def fake_nominatim(query, timeout=10.0):
        seen.append(query)
        if "bandel" in query.lower() and "coaching" in query.lower():
            return None, True          # answered: no such place
        return ({"lat": 22.9226, "lon": 88.3877, "display": "Bandel, Hooghly"}, True)

    original = map_search._nominatim
    map_search._nominatim = fake_nominatim
    try:
        hit = map_search.geocode("coaching centres in Bandel")
    finally:
        map_search._nominatim = original
    assert hit and abs(hit["lat"] - 22.9226) < 1e-6, hit
    assert len(seen) == 2, seen


def check_first_hit_makes_one_call():
    calls = []

    def fake(query, timeout=10.0):
        calls.append(query)
        return {"lat": 1.0, "lon": 2.0, "display": "x"}, True

    original = map_search._nominatim
    map_search._nominatim = fake
    try:
        hit = map_search.geocode("Bandel, Hooghly, West Bengal, India")
    finally:
        map_search._nominatim = original
    assert hit and len(calls) == 1, calls


def check_unreachable_service_stops_at_one_call():
    """A timeout is not an empty answer: do not try the other spellings."""
    calls = []

    def fake(query, timeout=10.0):
        calls.append(query)
        return None, False

    original = map_search._nominatim
    map_search._nominatim = fake
    try:
        hit = map_search.geocode("coaching centres in Bandel")
    finally:
        map_search._nominatim = original
    assert hit is None, hit
    assert len(calls) == 1, calls


def check_variants_share_one_budget():
    """Three slow spellings can never exceed the geocode budget."""
    import time as _time

    calls = []

    def fake(query, timeout=10.0):
        calls.append((query, timeout))
        _time.sleep(0.45)
        return None, True

    original = map_search._nominatim
    map_search._nominatim = fake
    started = _time.monotonic()
    try:
        hit = map_search.geocode("a in b, c", budget=1.0)
    finally:
        map_search._nominatim = original
    elapsed = _time.monotonic() - started
    assert hit is None, hit
    assert elapsed < 1.6, f"spent {elapsed:.2f}s on a 1.0s budget"
    assert len(calls) == 2, calls       # third try would start past the deadline
    assert calls[-1][1] <= 1.0, calls   # per-attempt timeout honours what is left
    assert map_search.GEOCODE_BUDGET_S <= 15.0, map_search.GEOCODE_BUDGET_S


def check_pin_coords_never_geocode():
    geocode = _Recorder(AssertionError("geocode must not run for a pin"))
    search = _Recorder([])
    original = (workflows.geocode, workflows.search_businesses)
    workflows.geocode, workflows.search_businesses = geocode, search
    try:
        _quiet_other_sources()
        workflows.search_businesses_workflow(
            "Simla", 2500, category="coaching centres", coords=(22.5719, 88.3644))
    finally:
        workflows.geocode, workflows.search_businesses = original

    assert geocode.calls == [], "the pin's label was geocoded anyway"
    assert search.calls, "the places source was never asked"
    args = search.calls[0][0]
    assert args[0] == 22.5719 and args[1] == 88.3644, args


def check_coords_beat_a_wrong_geocode():
    """Even when the label resolves, it must not override the pin's point."""
    geocode = _Recorder({"lat": 31.1040, "lon": 77.1708, "display": "Shimla"})
    search = _Recorder([])
    original = (workflows.geocode, workflows.search_businesses)
    workflows.geocode, workflows.search_businesses = geocode, search
    try:
        _quiet_other_sources()
        workflows.search_businesses_workflow(
            "Simla, Kolkata", 2500, coords=(22.5719, 88.3644))
    finally:
        workflows.geocode, workflows.search_businesses = original

    assert geocode.calls == [], "a label geocode replaced the pin's coordinates"
    assert search.calls[0][0][:2] == (22.5719, 88.3644), search.calls[0]


def check_api_forwards_pin_coords():
    from agents.web import api

    captured = {}

    def fake_workflow(location, radius, category="", goal="", coords=None):
        captured.update(location=location, radius=radius,
                        category=category, coords=coords)
        return {"businesses": [], "found_raw": 0, "filter_report": ""}

    original = workflows.search_businesses_workflow
    workflows.search_businesses_workflow = fake_workflow
    try:
        out = api.api_map_search({"location": "Simla", "radius": 2500,
                                  "lat": 22.5, "lon": 88.3,
                                  "category": "coaching centres"})
    finally:
        workflows.search_businesses_workflow = original

    assert captured["coords"] == (22.5, 88.3), captured
    assert out["raw"] == 0 and out["rows"] == [], out


def check_api_translates_unsupported():
    from agents.web import api

    def failing(location, radius, category="", goal="", coords=None):
        return {"error": "400 INVALID_ARGUMENT: this query is not supported"}

    original = workflows.search_businesses_workflow
    workflows.search_businesses_workflow = failing
    try:
        out = api.api_map_search({"location": "Bandel", "radius": 2500})
    finally:
        workflows.search_businesses_workflow = original

    msg = out["error"]
    assert "not supported" not in msg.lower(), msg
    assert "pin" in msg.lower() or "town" in msg.lower(), msg


def check_api_requires_a_place_or_a_point():
    from fastapi import HTTPException
    from agents.web import api

    try:
        api.api_map_search({"radius": 2500})
    except HTTPException as e:
        assert e.status_code == 400, e.status_code
    else:
        raise AssertionError("an empty search was accepted")


def check_missing_location_copy_is_actionable():
    """A place Nominatim cannot resolve names the string and the next step."""
    geocode = _Recorder(None)
    original = workflows.geocode
    workflows.geocode = geocode
    try:
        out = workflows.search_businesses_workflow("qwertyuiop", 2000)
    finally:
        workflows.geocode = original
    assert out.get("error"), out
    assert "qwertyuiop" in out["error"], out["error"]
    assert "pin" in out["error"].lower() or "town" in out["error"].lower(), out["error"]


CHECKS = [
    ("variants_extract_the_place", check_variants_extract_the_place),
    ("geocode_retries_with_the_place", check_geocode_retries_with_the_place),
    ("first_hit_makes_one_call", check_first_hit_makes_one_call),
    ("unreachable_service_stops_at_one_call", check_unreachable_service_stops_at_one_call),
    ("variants_share_one_budget", check_variants_share_one_budget),
    ("pin_coords_never_geocode", check_pin_coords_never_geocode),
    ("coords_beat_a_wrong_geocode", check_coords_beat_a_wrong_geocode),
    ("api_forwards_pin_coords", check_api_forwards_pin_coords),
    ("api_translates_unsupported", check_api_translates_unsupported),
    ("api_requires_a_place_or_a_point", check_api_requires_a_place_or_a_point),
    ("missing_location_copy_is_actionable", check_missing_location_copy_is_actionable),
]


# pytest also collects these by their check_ name.
def main() -> int:
    passed = 0
    for name, fn in CHECKS:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - a suite reports, it does not crash
            print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
        else:
            passed += 1
            print(f"[ok]   {name}")
    print(f"\nTotal: {len(CHECKS)} checks, {passed} passed, "
          f"{len(CHECKS) - passed} failed")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
