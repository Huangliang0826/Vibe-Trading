from __future__ import annotations

from src.scanner.core import Candidate, ScanResult


def test_candidate_roundtrips_through_dict():
    c = Candidate(symbol="AVGO", score=92.4, provider_id="factor_rank",
                  attribution="momentum factors top 3%",
                  detail={"gtja_alpha_032": 34.1})
    d = c.to_dict()
    assert d["symbol"] == "AVGO"
    assert d["score"] == 92.4
    assert d["provider_id"] == "factor_rank"
    assert d["detail"]["gtja_alpha_032"] == 34.1
    assert Candidate.from_dict(d) == c


def test_scanresult_roundtrips_and_sorts_candidates_by_score_desc():
    r = ScanResult(
        universe="sp500", asof="2026-06-11", providers=["factor_rank"],
        candidates=[
            Candidate("CAT", 88.1, "factor_rank", "quality+lowvol top 5%", {}),
            Candidate("AVGO", 92.4, "factor_rank", "momentum top 3%", {}),
        ],
        warnings=["factor whitelist 3 days old"],
    )
    d = r.to_dict()
    assert [c["symbol"] for c in d["candidates"]] == ["AVGO", "CAT"], \
        "candidates must serialize ranked by score descending"
    assert ScanResult.from_dict(d) == r
