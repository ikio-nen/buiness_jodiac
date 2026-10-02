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
