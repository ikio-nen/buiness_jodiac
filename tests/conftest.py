"""
pytest fixtures for the outbox ledger.

Each test that needs a ledger gets its own temporary database, created and
destroyed by the fixture — no shared file, no test litter, no ordering
dependency between tests.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from agents.outbox.ledger import Ledger


# These suites are runnable scripts, not pytest modules: they execute their
# checks at import time and call sys.exit(). While they lived in agents/ pytest
# never collected them; now that every suite sits in tests/, one SystemExit at
# import aborts the whole session (INTERNALERROR) and test_ledger's tests never
# run. They stay runnable directly: `python -X utf8 tests/<name>.py`.
collect_ignore = [
    "test_category_exclusions.py",
    "test_contact_enricher.py",
    "test_db.py",
    "test_final_audit.py",
    "test_goal_state.py",
    "test_outreach_apis.py",
    "test_provider_cascade.py",
]


@pytest.fixture
def outbox_dir(tmp_path: Path) -> Path:
    """A fresh, real directory a Ledger can own."""
    return tmp_path


@pytest.fixture
def ledger(
    outbox_dir: Path, request: pytest.FixtureRequest
) -> Ledger:
    """A Ledger over a temp database, closed and removed after the test."""
    path = outbox_dir / "outbox.db"
    lgr = Ledger(path)
    yield lgr
    lgr.close()
    # Defensive: remove the file and the WAL/SHM companions so no test
    # artifact survives into the next run or the repo. The session-litter
    # lesson is that temp files left behind by one test are the kind of
    # thing that quietly becomes a real file on a fresh checkout.
    for name in ("outbox.db", "outbox.db-wal", "outbox.db-shm"):
        candidate = outbox_dir / name
        if candidate.exists():
            candidate.unlink()
