"""Self-check for the SQLite seam (agents/db.py + agents/store.py).

Run:  python -X utf8 tests/test_db.py   (repo root)
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
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(env_home: str):
    for m in ["agents", "agents.config", "agents.db", "agents.store",
              "agents.db_backfill"]:
        sys.modules.pop(m, None)
    cfg = types.ModuleType("agents.config")
    cfg.OUTPUT_DIR = Path(env_home)
    pkg = types.ModuleType("agents")
    pkg.__path__ = []
    sys.modules["agents"] = pkg
    sys.modules["agents.config"] = cfg
    for name, rel in (("agents.db", "agents/db.py"),
                      ("agents.store", "agents/store.py"),
                      ("agents.db_backfill", "agents/db_backfill.py")):
        spec = importlib.util.spec_from_file_location(
            name, os.path.join(_ROOT, "agents", rel.split("/", 1)[1]))
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
    assert db.migrate() == 2
    assert db.migrate() == 2  # second run is a no-op
    assert db.current_version() == 2
    assert db.journal_mode().lower() == "wal"
    st = db.status()
    assert st["version"] == 2 and "businesses" in st["tables"]
    assert "contacts" in st["tables"]
    assert st["path"].endswith("jodiac.db")


@check("directory schema: normalised keys, contacts, lookup indexes")
def _():
    db, store = _load(str(_TMP))
    db.migrate()
    with db.connect() as conn:
        bcols = {r[1] for r in conn.execute("PRAGMA table_info(businesses)")}
        ecols = {r[1] for r in conn.execute("PRAGMA table_info(emails)")}
        idx = {r[1] for r in conn.execute("PRAGMA index_list(businesses)")}
        view = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'"
            " AND name='v_directory'").fetchone()
    assert {"name_norm", "domain", "goal", "times_seen",
            "first_seen", "last_seen"} <= bcols
    assert {"business_name", "sent_at", "error", "contact_id"} <= ecols
    assert {"idx_businesses_norm", "idx_businesses_domain",
            "idx_businesses_email"} <= idx
    assert view is not None


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


@check("directory: same business twice is one row with merged fields")
def _():
    db, store = _load(str(_TMP))
    a = store.upsert_business("", {"name": "Aakash  Institute",
                                   "category": "training", "phone": ""})
    b = store.upsert_business("", {"name": "aakash institute!",
                                   "phone": "999", "website": "http://www.aakash.in/x",
                                   "times_seen": 6})
    assert a == b and a > 0
    assert store.count_businesses() == 1
    row = store.list_businesses("")[0]
    assert row["name_norm"] == "aakash institute"
    assert row["domain"] == "aakash.in"
    assert row["phone"] == "999"          # thin record did not wipe the phone
    assert row["category"] == "training"  # nor the category
    assert row["times_seen"] == 6
    # replays are free: the same history cannot inflate the counter
    store.upsert_business("", {"name": "Aakash Institute", "times_seen": 6})
    assert store.list_businesses("")[0]["times_seen"] == 6


@check("contacts: channels dedupe, merge, and link by domain")
def _():
    db, store = _load(str(_TMP))
    bid = store.upsert_business("", {"name": "Vivekananda Institution",
                                      "website": "www.vivekanandainstitution.com"})
    c1 = store.upsert_contact(bid, email="viv.inst.how@gmail.com",
                              domain="vivekanandainstitution.com",
                              source="homepage", verified=True)
    c2 = store.upsert_contact(bid, email="viv.inst.how@gmail.com",
                              domain="vivekanandainstitution.com",
                              phone="0123", status="deliverable")
    assert c1 == c2 and c1 > 0
    rows = store.contacts_for(bid)
    assert len(rows) == 1
    assert rows[0]["verified"] == 1 and rows[0]["phone"] == "0123"
    assert rows[0]["status"] == "deliverable"
    # An orphan found later attaches to the business owning its domain.
    store.upsert_contact(0, email="principal@vivekanandainstitution.com")
    store.link_contact_domains()
    assert len(store.contacts_for(bid)) == 2
    assert store.stats()["verified_contacts"] == 1


@check("directory: search, stats and email link")
def _():
    db, store = _load(str(_TMP))
    bid = store.upsert_business("", {"name": "Alpha Coaching",
                                      "category": "education",
                                      "location": "Kolkata",
                                      "fit": {"score": 80, "fit": "fits"}})
    store.upsert_business("", {"name": "Beta Works", "category": "training"})
    assert [r["name"] for r in store.search_businesses("kolkata")] == ["Alpha Coaching"]
    assert [r["name"] for r in store.search_businesses("alpha")] == ["Alpha Coaching"]
    eid = store.save_email("", "a@alpha.com", "Hi", "body", business_id=bid,
                           kind="sent", status="sent", business_name="Alpha Coaching")
    assert eid > 0 and store.emails_for(bid)[0]["status"] == "sent"
    st = store.stats()
    assert st["businesses"] == 2 and st["sent"] == 1 and st["drafts"] == 0
    out = {r["name"]: r for r in store.directory()}
    assert out["Alpha Coaching"]["sent_count"] == 1
    assert store.directory(limit=1)[0]["fit_score"] == 80


@check("backfill: JSON stores import idempotently")
def _():
    root = Path(_TMP)
    for sub in ("brain/businesses", "emails"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "brain/businesses/a.json").write_text(
        '{"name": "Aakash Institute", "category": "training",'
        ' "fit": "plausible", "fit_score": 60, "why_fit": "w",'
        ' "goal": "CAD", "times_seen": 6}', encoding="utf-8")
    (root / "contact_cache.json").write_text(
        '{"abc": {"email": "hi@aakash.in", "phone": "", "whatsapp": "",'
        ' "sources": {"email": "www.aakash.in (homepage)", "email_verified": true},'
        ' "candidates": [{"email": "hi@aakash.in", "status": "deliverable"}]}}',
        encoding="utf-8")
    (root / "emails/sent_ledger.jsonl").write_text(
        '{"to": "hi@aakash.in", "name": "Aakash Institute",'
        ' "subject": "Seats", "sent_at": "2026-11-15T22:30:37",'
        ' "success": true, "error": ""}\n'
        '{"to": "hey@beta.in", "name": "Beta Works", "subject": "Intro",'
        ' "sent_at": "2026-11-15T22:31:00", "success": true, "error": ""}\n',
        encoding="utf-8")
    (root / "emails/bounces.jsonl").write_text(
        '{"to": "hi@aakash.in", "subject": "Seats", "reason": "relay denied"}\n',
        encoding="utf-8")
    db, store = _load(str(_TMP))
    import agents.db_backfill as bf  # loaded by _load from the same root
    first = bf.run()
    # 1 business from brain, 1 contact from the cache; the ledger adds the
    # second business and its email, so the DB ends up with 2 of each.
    assert first["businesses"] == 1 and first["contacts"] == 1
    assert first["sent"] == 2 and first["bounced"] == 1
    assert first["db"]["businesses"] == 2 and first["db"]["contacts"] == 2
    # One delivery stands, the bounced one is now 'failed'.
    assert first["db"]["sent"] == 1 and first["db"]["failed"] == 1
    second = bf.run()  # a replay adds nothing
    assert second["sent"] == 0 and second["db"] == first["db"]
    assert store.stats()["businesses"] == 2


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
    assert store.search_businesses("x") == []
    assert store.contacts_for(1) == []
    assert store.upsert_contact(1, email="a@b.c") == 0
    assert store.mark_email_failed(1, "e") is False
    assert store.stats()["businesses"] == 0
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
