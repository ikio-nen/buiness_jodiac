"""Verify that no data path resolves to the legacy F:/jodiac or D:/brain paths."""
import os
import sys
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

def test_paths_are_local_and_portable():
    # Save original env
    orig_home = os.environ.get("JODIAC_HOME")
    orig_obs = os.environ.get("JODIAC_OBSIDIAN")
    try:
        # Clear env to test default resolution
        os.environ.pop("JODIAC_HOME", None)
        os.environ.pop("JODIAC_OBSIDIAN", None)

        # Reload config in-place to avoid breaking module references
        import importlib
        import agents.config
        importlib.reload(agents.config)
        from agents import config

        project_root = config.PROJECT_ROOT.resolve()
        assert "jodiac_data" in str(config._JODIAC_HOME), f"_JODIAC_HOME must use jodiac_data: {config._JODIAC_HOME}"
        assert str(config.PROJECT_ROOT) in str(config._JODIAC_HOME), f"_JODIAC_HOME must be under PROJECT_ROOT: {config._JODIAC_HOME}"
        assert str(config.PROJECT_ROOT) in str(config.OBSIDIAN_VAULT), f"OBSIDIAN_VAULT must be under PROJECT_ROOT: {config.OBSIDIAN_VAULT}"

        for p in [config.OUTPUT_DIR, config.SITES_DIR, config.REPORTS_DIR,
                  config.EMAILS_DIR, config.DATA_DIR, config.SESSIONS_DIR,
                  config.PDF_DIR, config.KB_DIR, config.OBSIDIAN_VAULT]:
            s = str(p).replace("\\", "/")
            assert "F:/jodiac/" not in s and not s.endswith("F:/jodiac"), f"Path resolves to legacy F:/jodiac: {p}"
            assert "D:/brain" not in s, f"Path resolves to legacy D:/brain: {p}"

        # Test proactive followups path
        if "agents.proactive" in sys.modules:
            del sys.modules["agents.proactive"]
        from agents import proactive
        import inspect
        src = inspect.getsource(proactive._overdue_followups)
        assert 'Path("D:/brain' not in src, "proactive._overdue_followups still hardcodes D:/brain"

        print("  [PASS] All paths resolve to local project directories and avoid F:/jodiac and D:/brain")
    finally:
        if orig_home is not None:
            os.environ["JODIAC_HOME"] = orig_home
        if orig_obs is not None:
            os.environ["JODIAC_OBSIDIAN"] = orig_obs

if __name__ == "__main__":
    test_paths_are_local_and_portable()
