import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
REPORT = ROOT / "reports" / "NSA_Enforcement_Litigation_Dashboard_Source_2026-09-29.xlsx"
