"""Deterministic portfolio allocation with local data and risk measurement."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf

from src.asset_management.models import (
    AllocationItem,
    AssetCandidate,
    AssetManagementPlan,
    AssetManagementRequest,
    PortfolioMetrics,
)
from src.asset_management.storage import AssetManagementStore
from src.paper_trading.models import PaperHolding
from src.paper_trading.strategies import _to_code

Allocator = Callable[[dict[str, Any]], dict[str, Any]]
HistoryLoader = Callable[[list[str], str, str], dict[str, pd.DataFrame]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _default_history_loader(codes: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    from backtest.loaders.yfinance_loader import DataLoader

    return DataLoader().fetch(codes, start, end, interval="1D")


def _review_model() -> tuple[str, str]:
    return "deterministic", "mean-variance-v1"


def _default_allocator(payload: dict[str, Any]) -> dict[str, Any]:
    assets = payload["assets"]
    count = len(assets)
    expected = np.array([float(item["model_expected_return"]) for item in assets] + [float(payload["cash_assumed_return"])])
    volatilities = np.array([float(item["annual_volatility"]) for item in assets])
    covariance = np.diag(np.square(volatilities))
    symbol_indexes: dict[str, list[int]] = {}
    for position, item in enumerate(assets):
        symbol_indexes.setdefault(str(item["symbol"]), []).append(position)
    for pair in payload.get("correlations", []):
        left_matches = symbol_indexes.get(str(pair["left"]), [])
        right_matches = symbol_indexes.get(str(pair["right"]), [])
        if len(left_matches) == 1 and len(right_matches) == 1:
            left, right = left_matches[0], right_matches[0]
            covariance[left, right] = covariance[right, left] = float(pair["correlation"]) * volatilities[left] * volatilities[right]
    covariance_all = np.zeros((count + 1, count + 1))
    covariance_all[:count, :count] = covariance
    target = float(payload["target_return"])
    volatility_limit = float(payload["max_drawdown"]) / 1.8
    x0 = np.full(count + 1, 1.0 / (count + 1))
    constraints = [
        {"type": "eq", "fun": lambda weights: float(weights.sum() - 1.0)},
        {"type": "ineq", "fun": lambda weights: float(volatility_limit**2 - weights @ covariance_all @ weights)},
        {"type": "ineq", "fun": lambda weights: float(weights @ expected - target)},
    ]
    result = minimize(
        lambda weights: float(weights @ covariance_all @ weights) + 0.01 * float(np.square(weights[:-1]).sum()),
        x0,
        method="SLSQP",
        bounds=[(0.0, 1.0)] * (count + 1),
        constraints=constraints,
        options={"maxiter": 800, "ftol": 1e-11},
    )
    warnings: list[str] = []
    if not result.success:
        fallback = minimize(
            lambda weights: -float(weights @ expected) + 0.05 * float(weights @ covariance_all @ weights),
            x0,
            method="SLSQP",
            bounds=[(0.0, 1.0)] * (count + 1),
            constraints=constraints[:2],
            options={"maxiter": 800, "ftol": 1e-11},
        )
        weights = fallback.x if fallback.success else x0
        warnings.append("当前候选资产可能无法同时满足收益与回撤目标，已返回最接近方案。")
    else:
        weights = result.x
    weights = np.maximum(weights, 0.0)
    weights /= weights.sum()
    allocations = []
    for position, item in enumerate(assets):
        weight = float(weights[position])
        band = max(0.02, weight * 0.20)
        allocations.append({
            "symbol": item["symbol"], "market": item["market"], "weight": weight,
            "range_min": max(0.0, weight - band), "range_max": min(1.0, weight + band),
            "reason": "确定性均值-方差优化器根据收益、波动与相关性计算。",
        })
    cash_weight = float(weights[-1])
    allocations.append({
        "symbol": "CASH", "market": "cash", "weight": cash_weight,
        "range_min": max(0.0, cash_weight - 0.05), "range_max": min(1.0, cash_weight + 0.05),
        "reason": "现金用于降低组合波动并保留流动性。",
    })
    return {
        "summary": "仓位由确定性均值-方差优化器计算，可由用户在回测和追踪前手动调整。",
        "allocations": allocations,
        "warnings": warnings,
    }


def _historical_drawdown(daily_returns: np.ndarray, weights: np.ndarray) -> float:
    series = daily_returns @ weights
    equity = np.cumprod(1.0 + np.clip(series, -0.99, None))
    peak = np.maximum.accumulate(equity)
    return float(np.min(equity / np.maximum(peak, 1e-12) - 1.0))


def _asset_key(market: str, symbol: str) -> tuple[str, str]:
    return market.strip().lower(), symbol.strip().upper()


def _prior_return(asset_type: str) -> float:
    return 0.035 if asset_type == "bond" else 0.060 if asset_type == "fund" else 0.075


def _proxy_volatility(asset_type: str) -> float:
    return 0.08 if asset_type == "bond" else 0.20 if asset_type == "fund" else 0.30


def _parse_decision(
    decision: dict[str, Any],
    candidates: list[AssetCandidate],
) -> tuple[dict[tuple[str, str], dict[str, Any]], str, list[str]]:
    raw_allocations = decision.get("allocations")
    if not isinstance(raw_allocations, list):
        raise ValueError("组合优化器未返回有效的 allocations 数组")

    expected_keys = {_asset_key(item.market, item.symbol) for item in candidates}
    expected_keys.add(("cash", "CASH"))
    parsed: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in raw_allocations:
        if not isinstance(raw, dict):
            raise ValueError("组合优化器返回了无效的仓位条目")
        key = _asset_key(str(raw.get("market", "")), str(raw.get("symbol", "")))
        if key not in expected_keys:
            raise ValueError(f"组合优化器返回了候选池之外的资产：{key[1] or 'unknown'}")
        if key in parsed:
            raise ValueError(f"组合优化器重复返回资产：{key[1]}")
        try:
            weight = float(raw["weight"])
            range_min = float(raw.get("range_min", weight))
            range_max = float(raw.get("range_max", weight))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"组合优化器返回的 {key[1]} 仓位不是有效数字") from exc
        parsed[key] = {
            "weight": weight,
            "range_min": range_min,
            "range_max": range_max,
            "reason": str(raw.get("reason", "组合优化器未提供配置理由")).strip()[:200],
        }

    missing = expected_keys - set(parsed)
    if missing:
        raise ValueError(f"组合优化器未覆盖全部输入资产：{'、'.join(sorted(symbol for _, symbol in missing))}")

    weights = np.array([entry["weight"] for entry in parsed.values()], dtype=float)
    percent_mode = bool((weights > 1.0).any()) and 99.0 <= float(weights.sum()) <= 101.0
    if percent_mode:
        for entry in parsed.values():
            entry["weight"] /= 100.0
            entry["range_min"] /= 100.0
            entry["range_max"] /= 100.0

    for key, entry in parsed.items():
        weight = entry["weight"]
        lower = entry["range_min"]
        upper = entry["range_max"]
        if not all(np.isfinite(value) for value in (weight, lower, upper)):
            raise ValueError(f"组合优化器返回的 {key[1]} 仓位包含无效数值")
        if not 0.0 <= lower <= weight <= upper <= 1.0:
            raise ValueError(f"组合优化器返回的 {key[1]} 仓位或允许区间不合法")

    total = float(sum(entry["weight"] for entry in parsed.values()))
    if not 0.98 <= total <= 1.02:
        raise ValueError(f"组合优化器返回的仓位合计为 {total:.1%}，不是100%")
    # Only correct harmless decimal rounding; this is validation, not optimisation.
    if total != 1.0:
        for entry in parsed.values():
            entry["weight"] /= total

    summary = str(decision.get("summary", "确定性组合优化器已生成资产配置。")).strip()[:300]
    warnings = decision.get("warnings", [])
    clean_warnings = (
        [str(value).strip()[:200] for value in warnings if str(value).strip()]
        if isinstance(warnings, list)
        else []
    )
    return parsed, summary, clean_warnings


class AssetManagementService:
    def __init__(
        self,
        store: AssetManagementStore | None = None,
        *,
        history_loader: HistoryLoader = _default_history_loader,
        allocator: Allocator | None = _default_allocator,
    ) -> None:
        self.store = store or AssetManagementStore()
        self.history_loader = history_loader
        self.allocator = allocator

    def get_latest(self) -> AssetManagementPlan | None:
        return self.store.get_latest()

    def calculate(self, request: AssetManagementRequest) -> AssetManagementPlan:
        if self.allocator is None:
            raise RuntimeError("确定性组合优化器未启用")

        today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
        start = (today - pd.DateOffset(years=request.lookback_years)).date().isoformat()
        end = today.date().isoformat()
        candidates = [item.model_copy(update={"symbol": item.symbol.strip().upper()}) for item in request.candidates]

        code_map: dict[str, AssetCandidate] = {}
        for item in candidates:
            code = _to_code(PaperHolding(symbol=item.symbol, market=item.market, allocation_pct=1.0))
            if code in code_map:
                raise ValueError(f"候选资产重复：{code_map[code].symbol} 与 {item.symbol}")
            code_map[code] = item
        fetched = self.history_loader(list(code_map), start, end)

        closes: dict[str, pd.Series] = {}
        excluded: list[str] = []
        for code, item in code_map.items():
            frame = fetched.get(code)
            if frame is None or frame.empty or "close" not in frame:
                excluded.append(item.symbol)
                continue
            close = pd.to_numeric(frame["close"], errors="coerce").dropna().sort_index()
            if len(close) < 126:
                excluded.append(item.symbol)
                continue
            close.index = pd.to_datetime(close.index).tz_localize(None)
            closes[code] = close[~close.index.duplicated(keep="last")]
        if not closes:
            raise ValueError("候选资产没有足够的历史价格数据")

        prices = pd.concat(closes, axis=1).sort_index().ffill(limit=7)
        prices.columns = list(closes)
        returns = prices.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).fillna(0.0).iloc[1:]
        if len(returns) < 126:
            raise ValueError("候选资产的共同历史区间不足半年")

        available_codes = list(closes)
        available_items = [code_map[code] for code in available_codes]
        matrix = returns.to_numpy(dtype=float)
        covariance_available = LedoitWolf().fit(matrix).covariance_ * 252.0
        historical_returns = np.expm1(np.log1p(np.clip(matrix, -0.99, None)).mean(axis=0) * 252.0)
        expected_available = np.clip(
            0.35 * historical_returns
            + 0.65 * np.array([_prior_return(item.asset_type) for item in available_items]),
            -0.03,
            0.20,
        )

        available_index = {code: index for index, code in enumerate(available_codes)}
        statistics: list[dict[str, Any]] = []
        for code, item in code_map.items():
            index = available_index.get(code)
            if index is None:
                statistics.append({
                    **item.model_dump(mode="json"),
                    "data_available": False,
                    "model_expected_return": _prior_return(item.asset_type),
                    "annual_volatility": _proxy_volatility(item.asset_type),
                })
                continue
            single_returns = matrix[:, index]
            statistics.append({
                **item.model_dump(mode="json"),
                "data_available": True,
                "historical_annual_return": float(historical_returns[index]),
                "model_expected_return": float(expected_available[index]),
                "annual_volatility": float(np.sqrt(max(covariance_available[index, index], 0.0))),
                "historical_max_drawdown": _historical_drawdown(single_returns[:, None], np.array([1.0])),
            })

        correlations: list[dict[str, Any]] = []
        correlation = returns.corr()
        for left in range(len(available_items)):
            for right in range(left + 1, len(available_items)):
                correlations.append({
                    "left": available_items[left].symbol,
                    "right": available_items[right].symbol,
                    "correlation": float(correlation.iloc[left, right]),
                })

        decision = self.allocator({
            "target_return": request.target_return,
            "max_drawdown": request.max_drawdown,
            "lookback_years": request.lookback_years,
            "assets": statistics,
            "correlations": correlations,
            "cash_assumed_return": 0.015,
        })
        parsed, summary, model_warnings = _parse_decision(decision, candidates)

        count = len(candidates)
        cash_return = 0.015
        weights = np.array([
            parsed[_asset_key(item.market, item.symbol)]["weight"] for item in candidates
        ] + [parsed[("cash", "CASH")]["weight"]], dtype=float)
        expected_all = np.array([_prior_return(item.asset_type) for item in candidates] + [cash_return], dtype=float)
        covariance_all = np.zeros((count + 1, count + 1), dtype=float)
        daily_all = np.zeros((len(matrix), count + 1), dtype=float)
        daily_all[:, -1] = cash_return / 252.0

        candidate_code = {
            _asset_key(item.market, item.symbol): code for code, item in code_map.items()
        }
        for left, item in enumerate(candidates):
            code = candidate_code[_asset_key(item.market, item.symbol)]
            available_left = available_index.get(code)
            if available_left is None:
                covariance_all[left, left] = _proxy_volatility(item.asset_type) ** 2
                continue
            expected_all[left] = expected_available[available_left]
            daily_all[:, left] = matrix[:, available_left]
            for right, other in enumerate(candidates):
                other_code = candidate_code[_asset_key(other.market, other.symbol)]
                available_right = available_index.get(other_code)
                if available_right is not None:
                    covariance_all[left, right] = covariance_available[available_left, available_right]

        expected_return = float(weights @ expected_all)
        portfolio_variance = max(float(weights @ covariance_all @ weights), 0.0)
        annual_volatility = float(np.sqrt(portfolio_variance))
        historical_drawdown = _historical_drawdown(daily_all, weights)
        stress_drawdown = -max(abs(historical_drawdown), annual_volatility * 1.8)
        feasible = expected_return >= request.target_return - 0.002 and stress_drawdown >= -request.max_drawdown - 0.005

        risk_contributions = np.zeros(count + 1, dtype=float)
        if portfolio_variance > 1e-12:
            marginal = covariance_all @ weights
            risk_contributions = np.maximum(weights * marginal / portfolio_variance, 0.0)
            total_risk = float(risk_contributions.sum())
            if total_risk > 0:
                risk_contributions /= total_risk

        allocations: list[AllocationItem] = []
        for index, item in enumerate(candidates):
            entry = parsed[_asset_key(item.market, item.symbol)]
            allocations.append(AllocationItem(
                symbol=item.symbol,
                market=item.market,
                name=item.name or item.symbol,
                asset_type=item.asset_type,
                weight=entry["weight"],
                range_min=entry["range_min"],
                range_max=entry["range_max"],
                risk_contribution=float(risk_contributions[index]),
                expected_return=float(expected_all[index]),
                reason=entry["reason"],
            ))
        cash = parsed[("cash", "CASH")]
        allocations.append(AllocationItem(
            symbol="CASH",
            market="cash",
            name="现金",
            asset_type="cash",
            weight=cash["weight"],
            range_min=cash["range_min"],
            range_max=cash["range_max"],
            risk_contribution=0.0,
            expected_return=cash_return,
            reason=cash["reason"],
        ))

        warnings = ["仓位由确定性优化器计算；收益和回撤为基于历史数据的估计，不代表未来表现。"]
        warnings.extend(model_warnings)
        if excluded:
            warnings.append(f"以下资产历史数据不足，相关风险指标使用类型代理估计：{'、'.join(excluded)}")
        if not feasible:
            warnings.append(
                f"优化方案未同时达到所选目标：预计年化 {expected_return:.1%}、压力回撤 {stress_drawdown:.1%}。"
            )

        provider, model = _review_model()
        plan = AssetManagementPlan(
            plan_id=f"asset-{uuid4().hex[:12]}",
            status="feasible" if feasible else "closest",
            created_at=_utc_now(),
            data_through=prices.dropna(how="all").index[-1].date().isoformat(),
            provider=provider,
            model=model,
            request=request,
            allocations=allocations,
            metrics=PortfolioMetrics(
                expected_return=expected_return,
                annual_volatility=annual_volatility,
                historical_max_drawdown=historical_drawdown,
                stress_drawdown=stress_drawdown,
                target_return=request.target_return,
                max_drawdown_limit=request.max_drawdown,
            ),
            summary=summary,
            warnings=list(dict.fromkeys(warnings)),
        )
        return self.store.save_latest(plan)
