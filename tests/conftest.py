import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
REPORT = ROOT / "reports" / "NSA_Enforcement_Litigation_Dashboard_Source_2026-09-29.xlsx"


@pytest.fixture(autouse=True)
def never_publish(monkeypatch):
    """No test may build the real website or push to GitHub: the daily update's website step is replaced, and no
    GitHub token is visible (test_publish's push test uses a stand-in remote in a temp folder)."""
    import daily_update
    monkeypatch.setattr(daily_update, "update_website", lambda message: "not updated (tests)")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("LT_ROOT", raising=False)
