from src.scanner.core import Candidate, ScanResult
from src.scanner.universe_metadata import attach_company_names


def test_attach_company_names_enriches_hstech_candidates() -> None:
    result = ScanResult(
        universe="hstech",
        asof="2026-07-01",
        providers=["factor_rank"],
        candidates=[Candidate("700.HK", 90, "factor_rank", "test")],
    )

    enriched = attach_company_names(result)

    assert enriched.candidates[0].company_name == "腾讯控股"
    assert enriched.to_dict()["candidates"][0]["company_name"] == "腾讯控股"


def test_attach_company_names_leaves_other_universes_unchanged() -> None:
    result = ScanResult(
        universe="sp500",
        asof="2026-07-01",
        providers=["factor_rank"],
        candidates=[Candidate("AAPL", 90, "factor_rank", "test")],
    )

    assert attach_company_names(result) is result
