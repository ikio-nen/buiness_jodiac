#!/usr/bin/env python3
"""CLI for the outreach draft gate.

The rule lives in `agents/email_lint.py` (the drafting agents import it); this
wrapper exists so the gate can also be run by hand from the repo root:

    "E:/python.exe" -X utf8 tools/email_lint.py
    "E:/python.exe" -X utf8 tools/email_lint.py "Subject line" draft.txt
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.email_lint import lint, main  # noqa: E402


def run_cli(argv: list[str]) -> int:
    if len(argv) < 3:
        return main()
    subject = argv[1]
    body = Path(argv[2]).read_text(encoding="utf-8")
    problems = lint(subject, body)
    for problem in problems:
        print(f"- {problem}")
    print("pass" if not problems else f"{len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(run_cli(sys.argv))
