from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OWNED_FILES = [
    ROOT / "frontend/src/components/charts/PriceHistoryChart.tsx",
    ROOT / "frontend/src/pages/Overview.tsx",
    ROOT / "frontend/src/pages/HSTech.tsx",
]


def test_price_chart_consumers_do_not_reimplement_financial_metrics():
    forbidden = (
        "computeDailyDca",
        "computeDrawdown",
        "wealth / contributed",
        "close / firstClose",
        "price - base) / base",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in OWNED_FILES)

    assert not [formula for formula in forbidden if formula in combined]
