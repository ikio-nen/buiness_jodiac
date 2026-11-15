#!/usr/bin/env python
"""Rebuild jodiac_handoff.zip: the app plus its gitignored data root, minus secrets.

Usage (from the repo root):

    "E:\\python.exe" -X utf8 tools/make_handoff.py
    "E:\\python.exe" -X utf8 tools/make_handoff.py --output F:/tmp/handoff.zip
    "E:\\python.exe" -X utf8 tools/make_handoff.py --dry-run

Why this exists: everything needed to run the app on another machine is either
tracked code or the gitignored data root ``jodiac_data/``, and the data root
holds key material (``.env``, ``vault.json``, the chat database). Building that
by hand invites shipping a secret, so the exclusion list and the leak check live
here instead of in someone's terminal history.

The script refuses to report success if a secret-bearing path ends up inside the
archive, if the archive fails its CRC check, or if a required entry is missing.
Exit status is 0 only when the bundle is complete and clean.
"""
from __future__ import annotations

import argparse
import fnmatch
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directory names that never belong in a handoff, wherever they appear.
SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".vs", ".vscode", ".idea", ".freebuff", "node_modules",
    # the data root is copied deliberately below, not as ordinary app files
    "jodiac_data", "agent_output", "output", "_backups", "playtest_screenshots",
}

# Files that are machine-local, scratch, or secret.
SKIP_FILES = [
    ".env", ".env.*",              # real keys; .env.example is re-allowed below
    "*.log", "*.log.err", "*.zip", "*.pid", "server_pid.txt",
    ".freebuffpreview-*", "Thumbs.db", ".DS_Store",
    # agent work-notes, not part of the app
    "task_plan.md", "findings.md", "progress.md", "chat_notes.md",
    "handoff_notes.md",
    # scratch files the agent leaves in the root
    "_*.json", "_*.txt", "_*.md", "_*.bat",
]
ALLOW_FILES = [".env.example"]     # matched against SKIP_FILES

# Inside the data root only caches are skipped -- agent_output/ is the payload.
DATA_SKIP_DIRS = {"__pycache__", ".git", ".ipynb_checkpoints", ".pytest_cache"}

# Inside jodiac_data: personal or secret-bearing, never shipped.
DATA_SKIP_PREFIXES = [
    "agent_output/vault.json",
    "agent_output/.vault_key",
    "agent_output/secret_data.pdf",
    "agent_output/memory/conversations.db",   # also catches -wal / -shm sidecars
]

# Any of these appearing in the finished archive is a bug in this script.
LEAK_PATTERNS = [
    "*.env", ".env", ".env.*", "*.vault_key", "vault.json",
    "conversations.db", "conversations.db-*", "secret_data.pdf",
    "*.key", "*.pem", "*.pfx", "*.p12", "credentials.json",
    "service_account.json", "service-account*.json",
]

# The bundle is useless without these; their absence means the walk broke.
REQUIRED_ENTRIES = [
    "README-HANDOFF.txt",
    "jarvis.bat",
    "requirements.txt",
    "AGENTS.md",
    "agents/web/server.py",
    "agents/web/api.py",
    "agents/web/static/index.html",
    "jodiac_data/agent_output/config.json",
]


README_HANDOFF = """JODIAC / JARVIS -- portable handoff bundle
==========================================

The app plus its runtime data root (jodiac_data) in one folder. It runs from any
location on any machine: jarvis.bat points JODIAC_HOME at the jodiac_data folder
beside it, so no F: or D: drive is needed.

Tested from scratch on a clean virtual environment: fresh venv, pip install -r
requirements.txt, server started, the app's own 20-check audit passed inside it.

INCLUDED
  agents/ tests/ docs/        the application (zero build step, no npm)
  requirements.txt            Python packages
  AGENTS.md                   project documentation -- read this first
  jodiac_data/                everything the app reads and writes:
      agent_output/config.json       settings (contains no keys)
      agent_output/knowledge_base/   industry research
      agent_output/brain/            what the system has learned
      agent_output/skills/           learned procedures
      agent_output/contact_cache.json
      agent_output/sessions/         past sessions and drafts
      agent_output/emails/           send ledger + bounce list
      agent_output/jodiac.db         businesses / emails / usage
      obsidian/  playtests/

LEFT OUT ON PURPOSE (yours, not portable)
  .env                                        real keys, Gmail app password
  agent_output/vault.json                     encrypted key vault
  agent_output/secret_data.pdf                personal file
  agent_output/memory/conversations.db (+ -wal/-shm)   chat transcripts

SETUP ON ANOTHER WINDOWS MACHINE
  1. Install Python 3.11+ from python.org, ticking "Add python.exe to PATH".
  2. In this folder, make a virtual environment and install into it:
         python -m venv .venv
         .venv\\Scripts\\activate
         python -m pip install -r requirements.txt
     The scrapling[fetchers] line is required; without it the contact finder and
     several workflows fail to import.
  3. Copy .env.example to .env and fill in:
         GEMINI_API_KEY=...       AI drafting, scoring, research
         GMAIL_USER=...           only needed to actually send mail
         GMAIL_APP_PASSWORD=...   Gmail -> 2-Step Verification -> App passwords
     With no GEMINI_API_KEY the app runs on template fallbacks. With no Gmail
     pair it runs fine but refuses to send.
  4. Start it, with the virtual environment still active:
         python -m agents.jarvis        menu: web UI, CLI chat, dashboard
     or
         python -m agents.web.server    web UI only
     The console prints a one-time launch URL:
         http://127.0.0.1:8765/?token=...
     Open that exact URL once; it stores the session cookie. The bare address
     works afterwards.

  ABOUT jarvis.bat: it prefers a pinned interpreter at E:\\python.exe when that
  file exists, otherwise it runs whatever "python" is on PATH. If you want the
  virtual environment to be used, activate it first (step 2) and start the app
  with "python -m ..." instead of the .bat, or edit the .bat to point at
  .venv\\Scripts\\python.exe.

ENCODING (IMPORTANT ON NON-ENGLISH WINDOWS)
  Windows consoles default to a legacy codepage (cp932 on Japanese installs).
  The app prints em dashes and the rupee sign, which crash with
  UnicodeEncodeError under cp932. jarvis.bat sets PYTHONUTF8=1 and passes
  -X utf8 for exactly this reason. When starting the app by hand, do the same:
         set PYTHONUTF8=1
         python -X utf8 -m agents.web.server

ON macOS / LINUX
  There is no .bat file. From this folder:
      python3 -m venv .venv && source .venv/bin/activate
      pip install -r requirements.txt
      export JODIAC_HOME="$PWD/jodiac_data"
      export JODIAC_OBSIDIAN="$PWD/jodiac_data/obsidian"
      python3 -X utf8 -m agents.web.server

OPTIONAL: CLOUDFLARE-PROTECTED SITES
  The contact finder scrapes with curl-based fetching and needs no browser. Only
  Cloudflare-protected sites fall back to a stealth browser, which must be
  installed once if you want that:
         python -m patchright install chromium

PORT
  The server listens on 8765 and the security allowlists (allowed hosts,
  WebSocket origins, CSP connect-src) are pinned to 127.0.0.1/localhost:8765.
  Free that port before starting; changing the port also needs those lists
  updated in agents/web/server.py and agents/web/ws.py.

SEND HISTORY
  agent_output/emails/sent_ledger.jsonl is what stops addresses being mailed
  twice; it ships with the bundle. Delete it to make every address mailable
  again from that copy. bounces.jsonl lists addresses the mailbox rejected.
"""


def _is_skipped(name: str) -> bool:
    if any(fnmatch.fnmatch(name, pat) for pat in ALLOW_FILES):
        return False
    return any(fnmatch.fnmatch(name, pat) for pat in SKIP_FILES)


def app_files(root: Path) -> list[Path]:
    """Tracked-style app files: the repo minus ignored scratch, caches and data."""
    out: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.suffix in (".pyc", ".pyo"):
            continue
        if _is_skipped(path.name):
            continue
        out.append(path)
    return out


def data_files(root: Path) -> list[Path]:
    """The runtime data root, minus vault, chat DB and personal files.

    The walk is relative to jodiac_data, so its own name is not treated as a
    skipped directory (SKIP_DIRS carries it only to keep the app walk out).
    """
    data_root = root / "jodiac_data"
    if not data_root.is_dir():
        return []
    out: list[Path] = []
    for path in sorted(data_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(data_root)
        if any(part in DATA_SKIP_DIRS for part in rel.parts):
            continue
        posix = rel.as_posix()
        if any(posix == p or posix.startswith(p) for p in DATA_SKIP_PREFIXES):
            continue
        out.append(path)
    return out


def leaks_in(names: list[str]) -> list[str]:
    """Secret-bearing entries. Templates like .env.example are explicitly fine."""
    hits = []
    for name in names:
        base = name.rsplit("/", 1)[-1]
        if any(fnmatch.fnmatch(base, pat) for pat in ALLOW_FILES):
            continue
        if any(fnmatch.fnmatch(base, pat) or fnmatch.fnmatch(name, pat)
               for pat in LEAK_PATTERNS):
            hits.append(name)
    return hits


def build(output: Path, dry_run: bool) -> int:
    app = app_files(ROOT)
    data = data_files(ROOT)
    if not app:
        print("error: no app files found -- run this from inside the repo", file=sys.stderr)
        return 1
    if not data:
        print("warning: jodiac_data/ is empty or missing; the bundle would carry no data",
              file=sys.stderr)

    planned = [p.relative_to(ROOT).as_posix() for p in app + data]
    planned.append("README-HANDOFF.txt")

    if dry_run:
        print(f"would write {output.name}: {len(planned)} entries")
        print(f"  app files : {len(app)}")
        print(f"  data files: {len(data)}")
        top = sorted({n.split('/')[0] for n in planned})
        print(f"  top level : {', '.join(top)}")
        return 0 if not leaks_in(planned) else 1

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in app + data:
            archive.write(path, arcname=path.relative_to(ROOT).as_posix())
        archive.writestr("README-HANDOFF.txt", README_HANDOFF)

    # Check the finished archive from a closed handle: reading entries back
    # through the writer's own handle reports false corruption.
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        bad = archive.testzip()

    problems: list[str] = []
    if bad:
        problems.append(f"archive is corrupt at {bad}")
    leaked = leaks_in(names)
    if leaked:
        problems.append(f"secret-bearing entries: {leaked}")
    missing = [r for r in REQUIRED_ENTRIES if r not in names]
    if missing:
        problems.append(f"required entries missing: {missing}")

    size_mib = output.stat().st_size / 1048576
    print(f"wrote {output}  ({size_mib:.2f} MiB, {len(names)} entries)")
    print(f"  app files  : {len(app)}")
    print(f"  data files : {len(data)}")
    if problems:
        for problem in problems:
            print(f"  FAIL {problem}", file=sys.stderr)
        print("the bundle does not meet the handoff contract", file=sys.stderr)
        return 1
    print("  integrity  : OK")
    print("  secrets    : none")
    print("  required   : all present")
    print("ready to send.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild the portable handoff bundle (app + data root, no secrets).")
    parser.add_argument("--output", default=str(ROOT / "jodiac_handoff.zip"),
                        help="where to write the zip (default: jodiac_handoff.zip in the repo root)")
    parser.add_argument("--dry-run", action="store_true",
                        help="list what would be included without writing a zip")
    args = parser.parse_args()
    return build(Path(args.output), args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
