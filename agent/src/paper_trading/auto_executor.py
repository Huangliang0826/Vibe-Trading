"""Deterministic autonomous paper-trading executor (live Phase 2a).

Follows the forecast robust strategy signals mechanically — no LLM. It reconciles
the paper account to the *target position* each strategy currently wants, which
makes a tick **idempotent**: running it twice places no second order.

Rule set (confirmed with the user):
  * A stock the robust strategy currently wants LONG (its latest trade is still
    open) but that we do not hold  -> BUY.
  * A stock the strategy now wants FLAT (latest trade closed / unreliable / none)
    that we DO hold                -> SELL the whole position.
  * Entry size: ``ENTRY_NOTIONAL`` (capped at ``MAX_ORDER_NOTIONAL`` and by
    available buying power). Exits sell the full position (exempt from the size
    cap — a risk-reducing close must not be left partial) but still consume one
    of the day's order slots.
  * At most ``MAX_TRADES_PER_DAY`` orders per UTC day; exits are planned before
    entries so risk-reduction wins when the budget is tight.
  * The GLOBAL kill switch aborts the whole tick before any order.
  * Alpaca paper trades US equities only, so non-US watchlist names are skipped.

Everything with side effects is injected via :class:`PaperTickDeps`, so the core
is unit-testable with no broker, network or LLM.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ── Limits / sizing (user-approved) ──────────────────────────────────────────
MAX_TRADES_PER_DAY = 5
MAX_ORDER_NOTIONAL = 10_000.0
ENTRY_NOTIONAL = 10_000.0
PROFILE_ID = "alpaca-paper-trade"
BROKER_KEY = PROFILE_ID  # daily-count / audit namespace


@dataclass(frozen=True)
class PlannedOrder:
    market: str
    code: str
    side: str          # "buy" | "sell"
    reason: str        # "entry" | "exit"
    notional: Optional[float] = None   # set for entries
    quantity: Optional[float] = None   # set for exits (full position)


@dataclass
class TickResult:
    as_of: str
    dry_run: bool
    halted: bool = False
    planned: list[PlannedOrder] = field(default_factory=list)
    executed: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)   # {code, reason}
    daily_count_before: int = 0
    daily_count_after: int = 0
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "dry_run": self.dry_run,
            "halted": self.halted,
            "planned": [o.__dict__ for o in self.planned],
            "executed": self.executed,
            "skipped": self.skipped,
            "daily_count_before": self.daily_count_before,
            "daily_count_after": self.daily_count_after,
            "limit_max_trades_per_day": MAX_TRADES_PER_DAY,
            "limit_max_order_notional": MAX_ORDER_NOTIONAL,
            "note": self.note,
        }


def desired_position(trades: list[dict], reliable: bool) -> str:
    """Return the position the robust strategy currently wants: 'long' | 'flat'.

    LONG only when the strategy is reliable and its most recent trade is still
    open (``exit_reason == 'end_of_backtest'``). Everything else is FLAT.
    """
    if not reliable or not trades:
        return "flat"
    latest = max(trades, key=lambda t: str(t.get("exit_date") or t.get("entry_date") or ""))
    return "long" if latest.get("exit_reason") == "end_of_backtest" else "flat"


def plan_paper_tick(
    targets: list[dict],           # [{market, code, desired}]
    held_qty: dict[str, float],    # code(upper) -> qty held (>0 == long)
    *,
    remaining_slots: int,
    buying_power: float,
) -> tuple[list[PlannedOrder], list[dict]]:
    """Pure planner: reconcile targets vs holdings into orders + skips.

    Exits are emitted first, then entries, each bounded by ``remaining_slots``
    and (entries only) available ``buying_power``.
    """
    exits: list[PlannedOrder] = []
    entries: list[PlannedOrder] = []
    skipped: list[dict] = []

    for t in targets:
        code = str(t["code"]).upper()
        desired = t["desired"]
        qty = held_qty.get(code, 0.0)
        held = qty > 0
        if desired == "flat" and held:
            exits.append(PlannedOrder(market=t["market"], code=code, side="sell", reason="exit", quantity=qty))
        elif desired == "long" and not held:
            entries.append(PlannedOrder(
                market=t["market"], code=code, side="buy", reason="entry",
                notional=min(ENTRY_NOTIONAL, MAX_ORDER_NOTIONAL),
            ))
        # long+held or flat+flat -> already reconciled, nothing to do.

    plan: list[PlannedOrder] = []
    budget = buying_power
    for order in [*exits, *entries]:
        if len(plan) >= remaining_slots:
            skipped.append({"code": order.code, "reason": "daily_trade_limit"})
            continue
        if order.side == "buy":
            if order.notional is None or order.notional > budget:
                skipped.append({"code": order.code, "reason": "insufficient_buying_power"})
                continue
            budget -= order.notional
        plan.append(order)
    return plan, skipped


@dataclass
class PaperTickDeps:
    """Injected side-effecting collaborators (real in prod, fakes in tests)."""
    halt_check: Callable[[], bool]
    get_watchlist: Callable[[], list[tuple[str, str]]]      # [(market, code)]
    get_buying_power: Callable[[], float]
    get_positions: Callable[[], dict[str, float]]           # code(upper) -> qty
    get_signal: Callable[[str, str], tuple[list[dict], bool]]  # (market, code)->(trades, reliable)
    place_order: Callable[..., dict]                        # (market, code, side, notional, quantity)->result
    count_read: Callable[[], int]
    count_incr: Callable[[], int]
    audit: Callable[[dict], None]
    now_iso: Callable[[], str]


def run_paper_tick(deps: PaperTickDeps, *, dry_run: bool = True) -> TickResult:
    """Run one deterministic paper tick. Dry-run by default (plans, never trades)."""
    as_of = deps.now_iso()
    result = TickResult(as_of=as_of, dry_run=dry_run)
    result.halted = deps.halt_check()

    result.daily_count_before = deps.count_read()
    remaining = max(0, MAX_TRADES_PER_DAY - result.daily_count_before)

    # US-only (Alpaca paper trades US equities).
    watchlist = [(m, c) for (m, c) in deps.get_watchlist() if m.lower() == "us"]
    positions = deps.get_positions()

    targets: list[dict] = []
    for market, code in watchlist:
        try:
            trades, reliable = deps.get_signal(market, code)
        except Exception as exc:  # noqa: BLE001 - a bad symbol must not sink the tick
            result.skipped.append({"code": code.upper(), "reason": f"signal_error:{exc}"})
            continue
        targets.append({"market": market, "code": code, "desired": desired_position(trades, reliable)})

    plan, skips = plan_paper_tick(
        targets, positions, remaining_slots=remaining, buying_power=deps.get_buying_power(),
    )
    result.planned = plan
    result.skipped.extend(skips)

    if dry_run:
        result.daily_count_after = result.daily_count_before
        result.note = ("dry-run 预览 — kill switch 已触发,实际执行会被拦截"
                       if result.halted else "dry-run — 未下任何单")
        return result

    # Execution respects the kill switch — planning above always runs so the
    # preview is available, but no order is placed while halted.
    if result.halted:
        result.daily_count_after = result.daily_count_before
        result.note = "kill switch tripped — no orders placed"
        return result

    count = result.daily_count_before
    for order in plan:
        if count >= MAX_TRADES_PER_DAY:
            result.skipped.append({"code": order.code, "reason": "daily_trade_limit"})
            continue
        res = deps.place_order(
            market=order.market, code=order.code, side=order.side,
            notional=order.notional, quantity=order.quantity,
        )
        ok = isinstance(res, dict) and res.get("status") == "ok"
        record = {
            "as_of": as_of, "code": order.code, "side": order.side, "reason": order.reason,
            "notional": order.notional, "quantity": order.quantity,
            "ok": ok, "order_status": (res or {}).get("order_status"),
            "error": None if ok else (res or {}).get("error"),
        }
        result.executed.append(record)
        deps.audit(record)
        if ok:
            count = deps.count_incr()

    result.daily_count_after = deps.count_read()
    result.note = f"executed {sum(1 for e in result.executed if e['ok'])}/{len(plan)} orders"
    return result


# ── Production wiring ─────────────────────────────────────────────────────────
def _real_signal(market: str, code: str) -> tuple[list[dict], bool]:
    """Robust strategy signal for one US symbol: (trades, reliable).

    Uses the same annual-robust selection the UI's forecast signals ride on
    (the validated pick — not any per-user manual override, which lives only in
    the browser).
    """
    from src.paper_trading.hstech_best import (
        default_end_date, normalize_best_strategy_symbol,
        run_selected_single_symbol_strategy, select_single_symbol_robust_strategy,
    )
    _paper, _yahoo, display = normalize_best_strategy_symbol(code, market)
    end = default_end_date()
    selection = select_single_symbol_robust_strategy(display, market, end_date=end)
    payload = run_selected_single_symbol_strategy(
        display, market, display, display, selection=selection, end_date=end,
    )
    return (payload.get("best", {}).get("trades") or []), bool(payload.get("reliable"))


def _paper_audit(record: dict) -> None:
    """Append one action to the paper audit ledger (best-effort, 0600)."""
    import json
    import os
    from src.config.paths import get_runtime_root
    try:
        path = get_runtime_root() / "live" / "paper" / "actions.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        os.chmod(path, 0o600)
    except OSError as exc:  # audit must never sink a tick
        logger.warning("paper audit write failed: %s", exc)


def build_default_deps(profile_id: str = PROFILE_ID) -> PaperTickDeps:
    """Wire the executor to the real halt switch, watchlist, account and broker."""
    from datetime import datetime, timezone
    from src.live.daily_count import increment_daily_count, read_daily_count
    from src.live.halt import halt_flag_set
    from src.trading import service
    from src.watchlist import WatchlistStore

    def get_watchlist() -> list[tuple[str, str]]:
        return [("us", c) for c in WatchlistStore().get("us")]

    def get_buying_power() -> float:
        acct = service.get_account(profile_id)
        inner = acct.get("account") if isinstance(acct, dict) else None
        try:
            return float((inner or {}).get("buying_power") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def get_positions() -> dict[str, float]:
        pos = service.get_positions(profile_id)
        out: dict[str, float] = {}
        for p in (pos.get("positions") or []):
            try:
                out[str(p.get("symbol")).upper()] = float(p.get("qty") or 0.0)
            except (TypeError, ValueError):
                continue
        return out

    def place(*, market, code, side, notional, quantity):  # noqa: ANN001
        return service.place_order(
            code, profile_id, side=side, quantity=quantity, notional=notional,
            order_type="market", time_in_force="day",
        )

    return PaperTickDeps(
        halt_check=lambda: halt_flag_set(broker=None),
        get_watchlist=get_watchlist,
        get_buying_power=get_buying_power,
        get_positions=get_positions,
        get_signal=_real_signal,
        place_order=place,
        count_read=lambda: read_daily_count(BROKER_KEY),
        count_incr=lambda: increment_daily_count(BROKER_KEY),
        audit=_paper_audit,
        now_iso=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )
