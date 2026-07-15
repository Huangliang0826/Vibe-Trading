"""Quintile-sort backtest: split the cross-section into 5 buckets by composite
factor score each rebalance date, track equal-weighted returns per bucket.

The long-short spread (Q1 − Q5) is the core test for cross-sectional alpha.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

logger = logging.getLogger(__name__)

N_QUANTILES = 5
DEFAULT_REBAL_DAYS = 21  # ~monthly
DEFAULT_COST_BPS = 30  # round-trip for HK equities
MONO_THRESHOLD = -0.3  # Spearman rank-corr cutoff (absolute value used for screening)
WF_IS_DAYS = 252  # ~12 months in-sample
WF_OOS_DAYS = 126  # ~6 months out-of-sample


@dataclass
class FactorScreenResult:
    factor_id: str
    zoo: str
    ir: float
    mono_score: float  # Spearman corr between quintile rank and mean return (negative = good)
    quintile_means: list[float]  # mean return per quintile Q1..Q5
    kept: bool


@dataclass
class QuintileResult:
    rebal_days: int
    cost_bps: int
    n_periods: int
    quintile_returns: dict[str, list[float]]  # "Q1".."Q5" → cumulative NAV
    long_short: list[float]  # long−short cumulative NAV
    dates: list[str]
    summary: dict[str, dict[str, float]]  # per-quintile stats
    spread_summary: dict[str, float]  # long-short stats
    long_q: str = "Q1"  # which quintile is the long leg
    short_q: str = "Q5"  # which quintile is the short leg
    screening: list[dict[str, Any]] | None = None  # factor screening details

    def to_dict(self) -> dict[str, Any]:
        d = {
            "rebal_days": self.rebal_days,
            "cost_bps": self.cost_bps,
            "n_periods": self.n_periods,
            "quintile_returns": self.quintile_returns,
            "long_short": self.long_short,
            "dates": self.dates,
            "summary": self.summary,
            "spread_summary": self.spread_summary,
            "long_q": self.long_q,
            "short_q": self.short_q,
        }
        if self.screening is not None:
            d["screening"] = self.screening
        return d


def _compute_composite(
    factors: list[dict[str, Any]],
    registry: Any,
    panel: dict[str, pd.DataFrame],
    asof_idx: int,
    close: pd.DataFrame,
) -> pd.Series | None:
    """Compute IR-weighted composite percentile rank at a single date index."""
    date_label = close.index[asof_idx]
    truncated = {k: v.iloc[: asof_idx + 1] for k, v in panel.items() if isinstance(v, pd.DataFrame)}

    weighted = pd.Series(dtype=float)
    total_weight = 0.0

    for f in factors:
        mono = float(f.get("mono", 0.0))
        ir = float(f.get("ir", 0.0))
        if mono != 0.0:
            weight = abs(mono)
            positive_dir = mono < 0  # negative mono = Q1 best → standard direction
        elif ir != 0.0:
            weight = abs(ir)
            positive_dir = ir >= 0
        else:
            weight = 1.0
            positive_dir = True
        try:
            factor_df = registry.compute(f["id"], truncated)
        except Exception:
            continue
        if factor_df is None or factor_df.empty:
            continue
        idx = pd.to_datetime(factor_df.index)
        mask = idx <= pd.Timestamp(date_label)
        if not mask.any():
            continue
        row = factor_df.loc[mask].iloc[-1].dropna()
        if row.empty:
            continue
        pct = row.rank(pct=True)
        signed = pct if positive_dir else (1.0 - pct)
        weighted = weighted.add(signed * weight, fill_value=0.0)
        total_weight += weight

    if total_weight == 0.0 or weighted.empty:
        return None
    return weighted / total_weight


def screen_factor_monotonicity(
    panel: dict[str, pd.DataFrame],
    factors: list[dict[str, Any]],
    registry: Any,
    rebal_days: int = DEFAULT_REBAL_DAYS,
    warmup: int = 60,
    threshold: float = MONO_THRESHOLD,
) -> list[FactorScreenResult]:
    """Score each factor's quintile monotonicity independently.

    For each factor, run a single-factor quintile sort and compute Spearman
    rank correlation between quintile number [1..5] and mean period return.
    A perfectly monotonic factor scores −1.0 (Q1 best → Q5 worst).
    """
    close = panel["close"]
    n_rows = len(close)
    rebal_indices = list(range(warmup, n_rows - rebal_days, rebal_days))
    if not rebal_indices:
        return []

    results: list[FactorScreenResult] = []

    for f in factors:
        fid = f["id"]
        ir = float(f.get("ir", 0.0))
        zoo = f.get("zoo", "")

        q_returns: dict[int, list[float]] = {q: [] for q in range(N_QUANTILES)}
        valid_periods = 0

        for idx in rebal_indices:
            date_label = close.index[idx]
            truncated = {k: v.iloc[: idx + 1] for k, v in panel.items() if isinstance(v, pd.DataFrame)}

            try:
                factor_df = registry.compute(fid, truncated)
            except Exception:
                continue
            if factor_df is None or factor_df.empty:
                continue

            ts_idx = pd.to_datetime(factor_df.index)
            mask = ts_idx <= pd.Timestamp(date_label)
            if not mask.any():
                continue
            row = factor_df.loc[mask].iloc[-1].dropna()
            if len(row) < N_QUANTILES:
                continue

            pct = row.rank(pct=True)
            signed = pct if ir >= 0 else (1.0 - pct)

            try:
                labels = pd.qcut(signed, N_QUANTILES, labels=False, duplicates="drop")
            except ValueError:
                continue
            if labels is None or labels.nunique() < N_QUANTILES:
                continue

            hold_end = min(idx + rebal_days, n_rows - 1)
            for q in range(N_QUANTILES):
                q_label = N_QUANTILES - 1 - q  # map so 0→Q5, 4→Q1
                symbols = labels[labels == q].index.tolist()
                if not symbols:
                    continue
                s_prices = close.iloc[idx][symbols].dropna()
                e_prices = close.iloc[hold_end][symbols].dropna()
                common = s_prices.index.intersection(e_prices.index)
                if common.empty:
                    continue
                ret = float((e_prices[common] / s_prices[common] - 1).mean())
                q_returns[q_label].append(ret)
            valid_periods += 1

        if valid_periods < 3:
            results.append(FactorScreenResult(fid, zoo, ir, 0.0, [0.0] * N_QUANTILES, False))
            continue

        q_means = [float(np.mean(q_returns[q])) if q_returns[q] else 0.0 for q in range(N_QUANTILES)]
        ranks = list(range(1, N_QUANTILES + 1))
        corr, _ = sp_stats.spearmanr(ranks, q_means)
        mono = float(corr) if not np.isnan(corr) else 0.0

        kept = abs(mono) >= abs(threshold)
        results.append(FactorScreenResult(fid, zoo, ir, round(mono, 3), [round(m, 5) for m in q_means], kept))
        tag = "KEEP" if kept else "DROP"
        logger.info("screen %s: mono=%.3f %s  Q1..Q5=%s", fid, mono, tag, [f"{m:.4f}" for m in q_means])

    kept_count = sum(1 for r in results if r.kept)
    logger.info("screening done: %d/%d factors kept (threshold=%.2f)", kept_count, len(results), threshold)
    return results


def _annual_stats(nav: np.ndarray, n_periods: int, rebal_days: int) -> dict[str, float]:
    """Compute annualized return, volatility, Sharpe from a NAV series."""
    if len(nav) < 2:
        return {"total_return": 0.0, "annual_return": 0.0, "annual_vol": 0.0, "sharpe": 0.0, "max_drawdown": 0.0}

    total = float(nav[-1] / nav[0] - 1)
    periods_per_year = 252 / rebal_days
    n_years = n_periods / periods_per_year
    ann_ret = float((1 + total) ** (1 / max(n_years, 0.01)) - 1) if n_years > 0 else 0.0

    period_rets = np.diff(nav) / nav[:-1]
    ann_vol = float(np.std(period_rets) * np.sqrt(periods_per_year)) if len(period_rets) > 1 else 0.0
    sharpe = ann_ret / ann_vol if ann_vol > 1e-8 else 0.0

    running_max = np.maximum.accumulate(nav)
    drawdowns = (nav - running_max) / running_max
    max_dd = float(np.min(drawdowns))

    return {
        "total_return": round(total, 4),
        "annual_return": round(ann_ret, 4),
        "annual_vol": round(ann_vol, 4),
        "sharpe": round(sharpe, 2),
        "max_drawdown": round(max_dd, 4),
    }


def run_quintile_backtest(
    panel: dict[str, pd.DataFrame],
    factors: list[dict[str, Any]],
    registry: Any,
    rebal_days: int = DEFAULT_REBAL_DAYS,
    cost_bps: int = DEFAULT_COST_BPS,
    warmup: int = 60,
    refined: bool = False,
    long_q: str = "Q1",
    short_q: str = "Q5",
) -> QuintileResult:
    """Run quintile sort backtest over the panel.

    Args:
        panel: Wide OHLCV panel from ``_load_universe_panel``.
        factors: Factor manifest entries (id, zoo, ir).
        registry: Factor registry instance.
        rebal_days: Trading days between rebalances.
        cost_bps: Round-trip transaction cost in basis points.
        warmup: Minimum rows before first rebalance (factor lookback).
        refined: If True, screen factors for monotonicity first and
            only use those that pass.
    """
    screening_info: list[dict[str, Any]] | None = None

    if refined:
        screen_results = screen_factor_monotonicity(
            panel, factors, registry, rebal_days=rebal_days, warmup=warmup,
        )
        screening_info = [
            {
                "id": r.factor_id, "zoo": r.zoo, "ir": r.ir,
                "mono": r.mono_score, "q_means": r.quintile_means, "kept": r.kept,
            }
            for r in screen_results
        ]
        kept_ids = {r.factor_id for r in screen_results if r.kept}
        if not kept_ids:
            raise ValueError("no factors passed monotonicity screening")
        factors = [f for f in factors if f["id"] in kept_ids]
        logger.info("refined: %d factors after screening", len(factors))

    close = panel["close"]
    n_rows = len(close)
    cost_frac = cost_bps / 10000.0

    rebal_indices = list(range(warmup, n_rows - rebal_days, rebal_days))
    if not rebal_indices:
        raise ValueError("insufficient data for quintile backtest")

    quintile_navs: dict[str, list[float]] = {f"Q{i}": [1.0] for i in range(1, N_QUANTILES + 1)}
    ls_nav = [1.0]
    nav_dates = [str(close.index[rebal_indices[0]])]

    n_periods = 0
    for idx in rebal_indices:
        composite = _compute_composite(factors, registry, panel, idx, close)
        if composite is None or len(composite) < N_QUANTILES:
            continue

        # Assign quintiles: Q1 = highest score (best), Q5 = lowest
        labels = pd.qcut(composite, N_QUANTILES, labels=False, duplicates="drop")
        if labels is None or labels.nunique() < N_QUANTILES:
            continue

        hold_end = min(idx + rebal_days, n_rows - 1)
        end_date = str(close.index[hold_end])

        period_rets: dict[str, float] = {}
        for q in range(N_QUANTILES):
            q_label = f"Q{N_QUANTILES - q}"  # Q5(low) → Q1(high)
            symbols = labels[labels == q].index.tolist()
            if not symbols:
                period_rets[q_label] = 0.0
                continue
            start_prices = close.iloc[idx][symbols].dropna()
            end_prices = close.iloc[hold_end][symbols].dropna()
            common = start_prices.index.intersection(end_prices.index)
            if common.empty:
                period_rets[q_label] = 0.0
                continue
            rets = (end_prices[common] / start_prices[common] - 1).mean()
            period_rets[q_label] = float(rets) - cost_frac

        for q_label in quintile_navs:
            prev = quintile_navs[q_label][-1]
            quintile_navs[q_label].append(prev * (1 + period_rets.get(q_label, 0.0)))

        ls_ret = period_rets.get(long_q, 0.0) - period_rets.get(short_q, 0.0)
        ls_nav.append(ls_nav[-1] * (1 + ls_ret))
        nav_dates.append(end_date)
        n_periods += 1

    if n_periods == 0:
        raise ValueError("no valid rebalance periods")

    summary = {}
    for q_label, nav_list in quintile_navs.items():
        summary[q_label] = _annual_stats(np.array(nav_list), n_periods, rebal_days)

    spread_summary = _annual_stats(np.array(ls_nav), n_periods, rebal_days)

    return QuintileResult(
        rebal_days=rebal_days,
        cost_bps=cost_bps,
        n_periods=n_periods,
        quintile_returns={k: [round(v, 6) for v in vals] for k, vals in quintile_navs.items()},
        long_short=[round(v, 6) for v in ls_nav],
        dates=nav_dates,
        summary=summary,
        spread_summary=spread_summary,
        long_q=long_q,
        short_q=short_q,
        screening=screening_info,
    )


# ---------------------------------------------------------------------------
# Walk-forward out-of-sample validation
# ---------------------------------------------------------------------------

@dataclass
class WalkForwardFold:
    fold: int
    is_start: str
    is_end: str
    oos_start: str
    oos_end: str
    n_factors_kept: int
    factors_kept: list[str]
    oos_ls_return: float  # OOS long-short period return


@dataclass
class WalkForwardResult:
    rebal_days: int
    cost_bps: int
    is_days: int
    oos_days: int
    n_folds: int
    folds: list[dict[str, Any]]
    quintile_returns: dict[str, list[float]]
    long_short: list[float]
    dates: list[str]
    n_periods: int
    summary: dict[str, dict[str, float]]
    spread_summary: dict[str, float]
    long_q: str = "Q2"
    short_q: str = "Q5"
    latest_portfolio: dict[str, list[str]] | None = None  # Q1..Q5 → symbol list

    def to_dict(self) -> dict[str, Any]:
        d = {
            "rebal_days": self.rebal_days,
            "cost_bps": self.cost_bps,
            "is_days": self.is_days,
            "oos_days": self.oos_days,
            "n_folds": self.n_folds,
            "folds": self.folds,
            "quintile_returns": self.quintile_returns,
            "long_short": self.long_short,
            "dates": self.dates,
            "n_periods": self.n_periods,
            "summary": self.summary,
            "spread_summary": self.spread_summary,
            "long_q": self.long_q,
            "short_q": self.short_q,
        }
        if self.latest_portfolio is not None:
            d["latest_portfolio"] = self.latest_portfolio
        return d


WF_TOP_K = 30  # keep only the strongest factors per fold


def _screen_on_window(
    panel_window: dict[str, pd.DataFrame],
    factors: list[dict[str, Any]],
    registry: Any,
    rebal_days: int,
    warmup: int,
    threshold: float,
    top_k: int = WF_TOP_K,
) -> list[dict[str, Any]]:
    """Run monotonicity screening on a sub-window of the panel.
    Returns factor dicts annotated with ``mono`` score from IS screening.
    Only the top-K factors by abs(mono) are kept to concentrate signal."""
    results = screen_factor_monotonicity(
        panel_window, factors, registry,
        rebal_days=rebal_days, warmup=warmup, threshold=threshold,
    )
    kept = sorted(
        [r for r in results if r.kept],
        key=lambda r: abs(r.mono_score),
        reverse=True,
    )
    if top_k > 0:
        kept = kept[:top_k]
    mono_by_id = {r.factor_id: r.mono_score for r in kept}
    out = []
    for f in factors:
        if f["id"] in mono_by_id:
            annotated = {**f, "mono": mono_by_id[f["id"]]}
            out.append(annotated)
    return out


def run_walkforward_backtest(
    panel: dict[str, pd.DataFrame],
    factors: list[dict[str, Any]],
    registry: Any,
    rebal_days: int = DEFAULT_REBAL_DAYS,
    cost_bps: int = DEFAULT_COST_BPS,
    warmup: int = 60,
    is_days: int = WF_IS_DAYS,
    oos_days: int = WF_OOS_DAYS,
    long_q: str = "Q2",
    short_q: str = "Q5",
) -> WalkForwardResult:
    """Walk-forward validation: screen factors in-sample, test out-of-sample.

    Rolls through the panel in (IS, OOS) windows:
      - IS window: ``is_days`` trading days for factor screening
      - OOS window: ``oos_days`` trading days for quintile backtest
      - Step forward by ``oos_days`` each fold

    Only OOS returns are accumulated into the final equity curve,
    eliminating look-ahead bias in factor selection.
    """
    close = panel["close"]
    n_rows = len(close)
    cost_frac = cost_bps / 10000.0

    min_start = warmup
    fold_starts: list[int] = []
    pos = min_start
    while pos + is_days + oos_days <= n_rows:
        fold_starts.append(pos)
        pos += oos_days

    if not fold_starts:
        raise ValueError(
            f"insufficient data for walk-forward: need {is_days + oos_days} rows, "
            f"have {n_rows - min_start} after warmup"
        )

    quintile_navs: dict[str, list[float]] = {f"Q{i}": [1.0] for i in range(1, N_QUANTILES + 1)}
    ls_nav: list[float] = [1.0]
    nav_dates: list[str] = []
    fold_details: list[dict[str, Any]] = []
    total_periods = 0
    latest_portfolio: dict[str, list[str]] | None = None

    for fold_idx, fs in enumerate(fold_starts):
        is_end = fs + is_days
        oos_end = min(is_end + oos_days, n_rows)

        is_start_date = str(close.index[fs])
        is_end_date = str(close.index[is_end - 1])
        oos_start_date = str(close.index[is_end])
        oos_end_date = str(close.index[oos_end - 1])

        logger.info(
            "fold %d: IS [%s..%s] → OOS [%s..%s]",
            fold_idx + 1, is_start_date, is_end_date, oos_start_date, oos_end_date,
        )

        # Slice panel for IS window
        is_panel = {
            k: v.iloc[fs:is_end] for k, v in panel.items()
            if isinstance(v, pd.DataFrame)
        }
        # Copy non-DF entries (metadata)
        for k, v in panel.items():
            if not isinstance(v, pd.DataFrame):
                is_panel[k] = v

        kept_factors = _screen_on_window(
            is_panel, factors, registry,
            rebal_days=rebal_days, warmup=warmup, threshold=MONO_THRESHOLD,
        )

        if not kept_factors:
            logger.warning("fold %d: no factors passed screening, skipping", fold_idx + 1)
            fold_details.append({
                "fold": fold_idx + 1,
                "is_start": is_start_date, "is_end": is_end_date,
                "oos_start": oos_start_date, "oos_end": oos_end_date,
                "n_factors_kept": 0, "factors_kept": [],
                "oos_ls_return": 0.0,
            })
            continue

        logger.info("fold %d: %d factors kept → %s", fold_idx + 1, len(kept_factors),
                     [f["id"] for f in kept_factors])

        # Run quintile backtest on OOS window only
        oos_rebal_indices = list(range(is_end, oos_end - rebal_days, rebal_days))
        fold_ls_total = 0.0
        fold_periods = 0

        if not nav_dates:
            nav_dates.append(str(close.index[is_end]))

        for idx in oos_rebal_indices:
            composite = _compute_composite(kept_factors, registry, panel, idx, close)
            if composite is None or len(composite) < N_QUANTILES:
                continue

            labels = pd.qcut(composite, N_QUANTILES, labels=False, duplicates="drop")
            if labels is None or labels.nunique() < N_QUANTILES:
                continue

            hold_end = min(idx + rebal_days, oos_end)
            end_date = str(close.index[hold_end - 1] if hold_end < n_rows else close.index[-1])

            period_rets: dict[str, float] = {}
            current_holdings: dict[str, list[str]] = {}
            for q in range(N_QUANTILES):
                q_label = f"Q{N_QUANTILES - q}"
                symbols = labels[labels == q].index.tolist()
                current_holdings[q_label] = sorted(symbols)
                if not symbols:
                    period_rets[q_label] = 0.0
                    continue
                s_prices = close.iloc[idx][symbols].dropna()
                e_prices = close.iloc[min(hold_end, n_rows - 1)][symbols].dropna()
                common = s_prices.index.intersection(e_prices.index)
                if common.empty:
                    period_rets[q_label] = 0.0
                    continue
                rets = float((e_prices[common] / s_prices[common] - 1).mean())
                period_rets[q_label] = rets - cost_frac
            latest_portfolio = current_holdings

            for q_label in quintile_navs:
                prev = quintile_navs[q_label][-1]
                quintile_navs[q_label].append(prev * (1 + period_rets.get(q_label, 0.0)))

            ls_ret = period_rets.get(long_q, 0.0) - period_rets.get(short_q, 0.0)
            ls_nav.append(ls_nav[-1] * (1 + ls_ret))
            nav_dates.append(end_date)
            fold_ls_total += ls_ret
            fold_periods += 1
            total_periods += 1

        fold_details.append({
            "fold": fold_idx + 1,
            "is_start": is_start_date, "is_end": is_end_date,
            "oos_start": oos_start_date, "oos_end": oos_end_date,
            "n_factors_kept": len(kept_factors),
            "factors_kept": [f["id"] for f in kept_factors],
            "oos_ls_return": round(fold_ls_total, 4),
            "oos_periods": fold_periods,
        })

    if total_periods == 0:
        raise ValueError("no valid OOS periods across all folds")

    summary: dict[str, dict[str, float]] = {}
    for q_label, nav_list in quintile_navs.items():
        summary[q_label] = _annual_stats(np.array(nav_list), total_periods, rebal_days)
    spread_summary = _annual_stats(np.array(ls_nav), total_periods, rebal_days)

    return WalkForwardResult(
        rebal_days=rebal_days,
        cost_bps=cost_bps,
        is_days=is_days,
        oos_days=oos_days,
        n_folds=len(fold_starts),
        folds=fold_details,
        quintile_returns={k: [round(v, 6) for v in vals] for k, vals in quintile_navs.items()},
        long_short=[round(v, 6) for v in ls_nav],
        dates=nav_dates,
        n_periods=total_periods,
        summary=summary,
        spread_summary=spread_summary,
        long_q=long_q,
        short_q=short_q,
        latest_portfolio=latest_portfolio,
    )
