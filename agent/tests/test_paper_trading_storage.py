from src.paper_trading.models import PaperHolding, PaperTradingCreate, StrategyConfig
from src.paper_trading.storage import PaperTradingStore


def test_paper_run_persists_reproducibility_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_CODE_VERSION", "test-revision")
    store = PaperTradingStore(root=tmp_path / "runs", db_path=tmp_path / "paper.db")
    payload = PaperTradingCreate(
        title="metadata test",
        holdings=[PaperHolding(symbol="AAPL", market="us", allocation_pct=100)],
        strategy=StrategyConfig(name="buy_and_hold", params={"foo": 1}),
        start_date="2020-01-01",
        end_date="2024-01-01",
    )

    created = store.create_run(payload)
    restored = store.get_run(created.run_id)

    assert restored is not None
    assert restored.experiment is not None
    assert restored.experiment.code_version == "test-revision"
    assert restored.experiment.metric_version == "backtest.metrics.v2"
    assert restored.experiment.data_sources == ["yfinance"]
    assert restored.experiment.benchmark == "buy_and_hold"
    assert restored.experiment.cost_model["us"]["slippage_bps"] == 5.0
    assert len(restored.experiment.reproducibility_key) == 64
