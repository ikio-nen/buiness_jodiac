"""Self-check for the SQLite seam (agents/db.py + agents/store.py).

Run:  python -X utf8 agents/test_db.py   (repo root)
Exit 0 = all checks green. Uses a fake agents.config (OUTPUT_DIR -> tmp dir)
so the real Windows paths and the heavy agents/__init__ are never touched.
The SQL itself runs for real against stdlib sqlite3 — no mocks.
"""
import importlib.util
import os
import shutil
import sys
import types
from pathlib import Path

_TMP = Path("/tmp/jodiac_db_test")


def _load(env_home: str):
    for m in ["agents", "agents.config", "agents.db", "agents.store"]:
        sys.modules.pop(m, None)
    cfg = types.ModuleType("agents.config")
    cfg.OUTPUT_DIR = Path(env_home)
    pkg = types.ModuleType("agents")
    pkg.__path__ = []
    sys.modules["agents"] = pkg
    sys.modules["agents.config"] = cfg
    for name, rel in (("agents.db", "agents/db.py"),
                      ("agents.store", "agents/store.py")):
        spec = importlib.util.spec_from_file_location(
            name, os.path.join("agents", rel.split("/", 1)[1]))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules["agents.db"], sys.modules["agents.store"]


CHECKS = []


def check(name):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


@check("migrate: idempotent, version recorded, WAL mode")
def _():
    db, _ = _load(str(_TMP))
    assert db.migrate() == 1
    assert db.migrate() == 1  # second run is a no-op
    assert db.current_version() == 1
    assert db.journal_mode().lower() == "wal"
    st = db.status()
    assert st["version"] == 1 and "businesses" in st["tables"]
    assert st["path"].endswith("jodiac.db")


@check("businesses: upsert dedups on (session_id, ext_id)")
def _():
    db, store = _load(str(_TMP))
    b1 = {"id": "b1", "name": "Alpha Coaching", "category": "education",
          "phone": "111", "fit": {"score": 80, "fit": "fits",
                                  "rationale": "teaches AutoCAD"}}
    i1 = store.upsert_business("s1", b1)
    assert i1 > 0
    b1["fit"] = {"score": 92, "fit": "fits", "rationale": "updated"}
    i2 = store.upsert_business("s1", b1)
    assert i2 == i1  # same row updated, not duplicated
    assert store.count_businesses("s1") == 1
    i3 = store.upsert_business("s2", b1)  # other session -> new row
    assert i3 != i1 and store.count_businesses() == 2
    rows = store.list_businesses("s1")
    assert rows[0]["fit_score"] == 92 and rows[0]["phone"] == "111"


@check("businesses: list filters by verdict, orders by score")
def _():
    db, store = _load(str(_TMP))
    store.upsert_business("s9", {"id": "a", "name": "A",
                                 "fit": {"score": 10, "fit": "unlikely"}})
    store.upsert_business("s9", {"id": "b", "name": "B",
                                 "fit": {"score": 95, "fit": "fits"}})
    store.upsert_business("s9", {"id": "c", "name": "C",
                                 "fit": {"score": 50, "fit": "plausible"}})
    fits = store.list_businesses("s9", verdict="fits")
    assert [r["name"] for r in fits] == ["B"]
    all_rows = store.list_businesses("s9")
    assert [r["name"] for r in all_rows] == ["B", "C", "A"]


@check("emails: draft -> sent lifecycle")
def _():
    db, store = _load(str(_TMP))
    bid = store.upsert_business("s1", {"id": "b1", "name": "Alpha"})
    eid = store.save_email("s1", "a@x.com", "Hi", "body text", business_id=bid)
    assert eid > 0
    drafts = store.list_emails("s1", kind="draft")
    assert len(drafts) == 1 and drafts[0]["status"] == "draft"
    assert store.mark_email_sent(eid, provider="resend") is True
    assert store.list_emails("s1", kind="draft") == []
    sent = store.list_emails("s1", kind="sent")
    assert len(sent) == 1 and sent[0]["provider"] == "resend"
    assert sent[0]["sent_at"] != ""


@check("sessions: register, get, upsert on conflict")
def _():
    db, store = _load(str(_TMP))
    assert store.register_session("sess1", name="N1", product="AutoCAD") is True
    s = store.get_session("sess1")
    assert s["name"] == "N1" and s["product"] == "AutoCAD"
    store.register_session("sess1", name="N2", product="AutoCAD")
    assert store.get_session("sess1")["name"] == "N2"
    assert store.get_session("nope") == {}


@check("usage: per-capability and per-provider stats")
def _():
    db, store = _load(str(_TMP))
    store.log_usage("2026-10-02T10:00:00", "score_fit", ok=True,
                    used_gemini=False, provider="zai")
    store.log_usage("2026-10-02T10:00:01", "score_fit", ok=True,
                    used_gemini=False, provider="zai")
    store.log_usage("2026-10-02T10:00:02", "score_fit", ok=False,
                    used_gemini=False, provider="groq")
    store.log_usage("2026-10-02T10:00:03", "draft_email", ok=True,
                    used_gemini=True, provider="gemini")
    us = store.usage_stats()
    assert us["score_fit"]["calls"] == 3
    assert us["score_fit"]["fallbacks"] == 3  # none used gemini
    assert us["score_fit"]["errors"] == 1
    assert us["draft_email"]["gemini"] == 1
    ps = store.provider_stats()
    assert ps["zai"] == {"calls": 2, "ok_rate": 1.0}
    assert ps["groq"] == {"calls": 1, "ok_rate": 0.0}
    assert ps["gemini"]["calls"] == 1


@check("resilience: broken DB path -> safe defaults, never raises")
def _():
    broken = "/tmp/jodiac_db_broken"
    Path(broken).write_text("not a dir")
    db, store = _load(broken)
    assert store.upsert_business("s", {"id": "x", "name": "X"}) == 0
    assert store.list_businesses("s") == []
    assert store.count_businesses() == 0
    assert store.save_email("s", "a@b.c", "s", "b") == 0
    assert store.mark_email_sent(1) is False
    assert store.register_session("s") is False
    assert store.get_session("s") == {}
    assert store.log_usage("t", "cap") is False
    assert store.usage_stats() == {}
    assert store.provider_stats() == {}
    os.remove(broken)


def main():
    failed = 0
    for name, fn in CHECKS:
        shutil.rmtree(_TMP, ignore_errors=True)
        try:
            fn()
        except Exception as e:
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
        else:
            print(f"ok   {name}")
    shutil.rmtree(_TMP, ignore_errors=True)
    print(f"\n{len(CHECKS) - failed}/{len(CHECKS)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
