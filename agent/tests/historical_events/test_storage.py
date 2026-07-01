from pathlib import Path

from src.historical_events.models import HistoricalEvent
from src.historical_events.storage import HistoricalEventStore


def event() -> HistoricalEvent:
    return HistoricalEvent(
        event_id="hk-0700-2024-01-02-2024-01-03",
        market="hk", symbol="0700", company_name="腾讯控股",
        start_date="2024-01-02", end_date="2024-01-03",
        direction="down", return_pct=-9.2, trigger_windows=[1],
        driver_type="原因未确认", primary_driver="原因未确认",
        narrative="未找到足够可靠的同期证据。", confidence="低",
    )


def test_event_survives_store_reopen(tmp_path: Path):
    path = tmp_path / "events.db"
    expected = event()
    HistoricalEventStore(path).save_event(expected)

    loaded = HistoricalEventStore(path).list_events("hk", "0700", "2024-01-01", "2024-12-31")

    assert [item.model_dump(mode="json") for item in loaded] == [expected.model_dump(mode="json")]


def test_same_versioned_event_is_replaced_not_duplicated(tmp_path: Path):
    store = HistoricalEventStore(tmp_path / "events.db")
    store.save_event(event())
    changed = event().model_copy(update={"narrative": "更新后的归因"})
    store.save_event(changed)

    loaded = store.list_events("hk", "0700", "2024-01-01", "2024-12-31")

    assert len(loaded) == 1
    assert loaded[0].narrative == "更新后的归因"


def test_list_can_select_only_current_analysis_version(tmp_path: Path):
    store = HistoricalEventStore(tmp_path / "events.db")
    store.save_event(event().model_copy(update={"analysis_version": "historical-event-analysis-v1"}))
    store.save_event(event().model_copy(update={
        "analysis_version": "historical-event-analysis-v2", "narrative": "可信数据源结果",
    }))

    loaded = store.list_events(
        "hk", "0700", "2024-01-01", "2024-12-31",
        analysis_version="historical-event-analysis-v2",
    )

    assert len(loaded) == 1
    assert loaded[0].narrative == "可信数据源结果"
