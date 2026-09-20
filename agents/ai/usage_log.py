"""Usage log — one record per Gemini service call.

Answers "what did this cost / has Gemini gone quiet" without digging through
raw logs (PRD §5, §6). Writes JSONL under agent_output/usage/ and emits an
office event per call so the floor can visualize the seam working (ARCH §8).
A flatlined count for a capability that should be firing is the outage signal.
"""

import json
import time
from pathlib import Path

from agents.ai.schemas import UsageRecord

_LOG_DIR = Path("agent_output/usage")
_LOG_FILE = _LOG_DIR / "usage.jsonl"


def record(capability: str, prompt_version: str, business_id: str = "",
           ok: bool = True, used_gemini: bool = False, notes: str = "") -> None:
    """Append one UsageRecord. Never raises — logging can't break the seam."""
    try:
        rec = UsageRecord(
            ts=time.strftime("%Y-%m-%dT%H:%M:%S"),
            capability=capability,
            prompt_version=prompt_version,
            business_id=business_id,
            ok=ok,
            used_gemini=used_gemini,
            notes=notes[:160],
        )
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        with _LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec.model_dump(), ensure_ascii=True) + "\n")
        try:
            from agents.event_bus import emit
            emit("brain", action="ai",
                 detail=f"{capability}{' ✓' if ok else ' fell back'}"
                        + (f" [{business_id}]" if business_id else ""),
                 source="ai_service")
        except Exception:
            pass
    except Exception:
        pass


def stats() -> dict:
    """Per-capability totals for the status panel / dashboards."""
    out: dict[str, dict] = {}
    try:
        if not _LOG_FILE.exists():
            return out
        with _LOG_FILE.open(encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                s = out.setdefault(r["capability"], {"calls": 0, "gemini": 0, "fallbacks": 0})
                s["calls"] += 1
                s["gemini" if r.get("used_gemini") else "fallbacks"] += 1
    except Exception:
        pass
    return out
