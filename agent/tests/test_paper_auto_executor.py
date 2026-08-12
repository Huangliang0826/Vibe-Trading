"""Deterministic paper auto-executor (live Phase 2a)."""
from __future__ import annotations

from src.paper_trading import auto_executor as ax
from src.paper_trading.auto_executor import (
    PaperTickDeps, desired_position, plan_paper_tick, run_paper_tick,
)


# ── desired_position ─────────────────────────────────────────────────────────
def _open(entry="2026-07-30"):
    return {"entry_date": entry, "exit_date": "2026-07-31", "exit_reason": "end_of_backtest"}
def _closed(exit_date="2026-07-20"):
    return {"entry_date": "2026-07-01", "exit_date": exit_date, "exit_reason": "signal"}


def test_desired_position_long_when_latest_trade_open():
    assert desired_position([_closed(), _open()], reliable=True) == "long"

def test_desired_position_flat_when_latest_trade_closed():
    # No open trade -> the strategy is currently flat.
    assert desired_position([_closed("2026-07-01"), _closed("2026-07-25")], reliable=True) == "flat"

def test_desired_position_flat_when_unreliable_or_empty():
    assert desired_position([_open()], reliable=False) == "flat"
    assert desired_position([], reliable=True) == "flat"


# ── plan_paper_tick ──────────────────────────────────────────────────────────
def test_plan_buys_entries_and_sells_exits_reconciling_to_target():
    targets = [
        {"market": "us", "code": "AAPL", "desired": "long"},   # not held -> buy
        {"market": "us", "code": "NVDA", "desired": "flat"},   # held -> sell
        {"market": "us", "code": "MSFT", "desired": "long"},   # held -> nothing
        {"market": "us", "code": "TSLA", "desired": "flat"},   # flat -> nothing
    ]
    plan, skipped = plan_paper_tick(
        targets, {"NVDA": 3.0, "MSFT": 2.0}, remaining_slots=5, buying_power=100_000,
    )
    sides = [(o.code, o.side, o.reason) for o in plan]
    # exits first, then entries
    assert sides == [("NVDA", "sell", "exit"), ("AAPL", "buy", "entry")]
    assert plan[0].quantity == 3.0
    assert plan[1].notional == ax.ENTRY_NOTIONAL
    assert skipped == []


def test_plan_respects_daily_slot_budget():
    targets = [{"market": "us", "code": c, "desired": "long"} for c in ("A", "B", "C")]
    plan, skipped = plan_paper_tick(targets, {}, remaining_slots=2, buying_power=1_000_000)
    assert len(plan) == 2
    assert skipped == [{"code": "C", "reason": "daily_trade_limit"}]


def test_plan_skips_entries_without_buying_power():
    targets = [{"market": "us", "code": "AAPL", "desired": "long"}]
    plan, skipped = plan_paper_tick(targets, {}, remaining_slots=5, buying_power=100.0)
    assert plan == []
    assert skipped == [{"code": "AAPL", "reason": "insufficient_buying_power"}]


# ── run_paper_tick ───────────────────────────────────────────────────────────
def _deps(*, halted=False, watchlist=None, positions=None, signals=None, count=0, placed=None):
    placed = placed if placed is not None else []
    counter = {"n": count}
    def place(**kw):
        placed.append(kw)
        return {"status": "ok", "order_status": "OrderStatus.NEW"}
    return PaperTickDeps(
        halt_check=lambda: halted,
        get_watchlist=lambda: watchlist or [],
        get_buying_power=lambda: 400_000.0,
        get_positions=lambda: positions or {},
        get_signal=lambda m, c: (signals or {}).get(c.upper(), ([], False)),
        place_order=place,
        count_read=lambda: counter["n"],
        count_incr=lambda: counter.update(n=counter["n"] + 1) or counter["n"],
        audit=lambda rec: None,
        now_iso=lambda: "2026-07-31T14:00:00Z",
    ), placed, counter


def test_halt_blocks_execution_but_not_planning():
    deps, placed, _ = _deps(halted=True, watchlist=[("us", "AAPL")], signals={"AAPL": ([_open()], True)})
    res = run_paper_tick(deps, dry_run=False)
    assert res.halted is True
    assert placed == []                       # no order placed while halted
    assert [o.code for o in res.planned] == ["AAPL"]   # plan still computed


def test_dry_run_previews_even_while_halted():
    deps, placed, _ = _deps(halted=True, watchlist=[("us", "AAPL")], signals={"AAPL": ([_open()], True)})
    res = run_paper_tick(deps, dry_run=True)
    assert res.halted is True and placed == []
    assert [o.code for o in res.planned] == ["AAPL"]


def test_dry_run_plans_but_places_nothing():
    deps, placed, counter = _deps(watchlist=[("us", "AAPL")], signals={"AAPL": ([_open()], True)})
    res = run_paper_tick(deps, dry_run=True)
    assert [o.code for o in res.planned] == ["AAPL"]
    assert placed == [] and counter["n"] == 0


def test_execute_places_orders_and_counts():
    deps, placed, counter = _deps(
        watchlist=[("us", "AAPL"), ("us", "NVDA")],
        positions={"NVDA": 5.0},
        signals={"AAPL": ([_open()], True), "NVDA": ([_closed()], True)},
    )
    res = run_paper_tick(deps, dry_run=False)
    assert {p["code"] for p in placed} == {"AAPL", "NVDA"}
    assert counter["n"] == 2
    assert all(e["ok"] for e in res.executed)


def test_non_us_symbols_are_skipped():
    deps, placed, _ = _deps(
        watchlist=[("hk", "1810"), ("cn", "600519"), ("us", "AAPL")],
        signals={"AAPL": ([_open()], True), "1810": ([_open()], True), "600519": ([_open()], True)},
    )
    run_paper_tick(deps, dry_run=False)
    assert [p["code"] for p in placed] == ["AAPL"]


def test_daily_limit_enforced_across_execution():
    wl = [("us", c) for c in ("A", "B", "C", "D", "E", "F")]
    sig = {c: ([_open()], True) for c in ("A", "B", "C", "D", "E", "F")}
    deps, placed, counter = _deps(watchlist=wl, signals=sig, count=0)
    run_paper_tick(deps, dry_run=False)
    assert len(placed) == ax.MAX_TRADES_PER_DAY  # capped at 5
    assert counter["n"] == ax.MAX_TRADES_PER_DAY


# ── build_default_deps.get_positions (the daily re-buy regression) ──────────
def _positions_reader(monkeypatch, payload):
    from src.trading import service
    monkeypatch.setattr(service, "get_positions", lambda pid: payload)
    return ax.build_default_deps().get_positions


def test_default_positions_reader_uses_connector_quantity_key(monkeypatch):
    # Alpaca normalizes to ``quantity`` — reading ``qty`` made every held
    # position look flat, so the executor re-bought the same names daily.
    reader = _positions_reader(monkeypatch, {
        "status": "ok",
        "positions": [{"symbol": "AAPL", "quantity": "129.57"}, {"symbol": "QQQ", "qty": 13.9}],
    })
    assert reader() == {"AAPL": 129.57, "QQQ": 13.9}


def test_default_positions_reader_fails_closed_on_error_status(monkeypatch):
    reader = _positions_reader(monkeypatch, {"status": "error", "error": "boom"})
    try:
        reader()
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass


def test_default_positions_reader_fails_closed_on_unparseable_qty(monkeypatch):
    reader = _positions_reader(monkeypatch, {
        "status": "ok", "positions": [{"symbol": "AAPL"}],  # no quantity at all
    })
    try:
        reader()
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass


def test_read_paper_actions_newest_first_and_limited(monkeypatch, tmp_path):
    import src.config.paths as paths
    monkeypatch.setattr(paths, "get_runtime_root", lambda: tmp_path)
    p = tmp_path / "live" / "paper" / "actions.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text('{"code":"A"}\n\n{"code":"B"}\nnot-json\n{"code":"C"}\n', encoding="utf-8")

    rows = ax.read_paper_actions(limit=2)
    assert [r["code"] for r in rows] == ["C", "B"]  # newest first, malformed skipped, limited
    assert ax.read_paper_actions() == [] or ax.read_paper_actions()[0]["code"] == "C"


def test_read_paper_actions_missing_file(monkeypatch, tmp_path):
    import src.config.paths as paths
    monkeypatch.setattr(paths, "get_runtime_root", lambda: tmp_path)
    assert ax.read_paper_actions() == []


def test_tick_is_idempotent_once_reconciled():
    # AAPL long-desired and already held, nothing else -> no orders.
    deps, placed, _ = _deps(
        watchlist=[("us", "AAPL")], positions={"AAPL": 30.0},
        signals={"AAPL": ([_open()], True)},
    )
    res = run_paper_tick(deps, dry_run=False)
    assert res.planned == [] and placed == []
