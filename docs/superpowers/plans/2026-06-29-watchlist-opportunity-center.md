# 自选股机会中心 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在总览顶部建立每日自选股机会中心，以无未来数据的策略信号为核心，结合趋势、风险、新闻和可用估值，生成可解释、可回看的机会排序。

**Architecture:** 新增独立的 `src.opportunity_center` 包，分离新闻抓取、匹配与分析、市场/策略输入、评分、SQLite 持久化和每日调度。FastAPI router 只负责创建后台刷新任务与读取快照；React 总览组件消费稳定的响应契约并把股票链接到现有走势预测卡片。所有昂贵工作按市场收盘日幂等缓存，失败时保留上一次成功快照并标明过期原因。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic 2、SQLite、httpx、ElementTree、pandas、现有 paper-trading/yfinance 引擎、React 19、TypeScript、ECharts 6、Vitest。

## Global Constraints

- 第一版只处理港股和美股自选股，不接交易接口，不自动下单。
- 综合评分固定权重：策略 40%、趋势 20%、风险 20%、新闻 15%、估值 5%。
- 第一版等级阈值固定为：`优先关注 >= 75`、`值得观察 >= 55`，其余为 `暂不参与`。
- 策略维度缺失、价格过期或策略回测失败时必须返回 `数据不足`，不得用旧信号冒充当日结果。
- 最新动作为平仓/风险退出时，等级最高只能为 `暂不参与`；新闻不能覆盖退出信号。
- 同一文章、股票、分析日期和 prompt 版本只调用一次 AI；同一市场日期、策略版本和评分版本只保存一个快照。
- 页面必须显示数据截至时间、缓存/降级状态和“仅供研究参考，不构成投资建议”。
- 参考 `investment-news` 的来源目录或代码时，必须保留 `Copyright (c) 2026 simonlin1212` 和 MIT License 归属。
- 新 UI 卡片圆角不超过 8px，使用现有 Tailwind、Lucide 和 ECharts，不增加新的前端依赖。

---

## File Map

**Backend package**

- Create `agent/src/opportunity_center/__init__.py`: package exports and score/strategy version constants.
- Create `agent/src/opportunity_center/models.py`: Pydantic contracts shared by storage, service and API.
- Create `agent/src/opportunity_center/storage.py`: one SQLite database for sources, articles, matches, analyses, snapshots and refresh jobs.
- Create `agent/src/opportunity_center/sources.json`: vendored RSS source catalog from `investment-news`.
- Create `agent/src/opportunity_center/THIRD_PARTY_NOTICE.md`: upstream MIT attribution.
- Create `agent/src/opportunity_center/feeds.py`: RSS/Atom parsing, canonicalization, near-duplicate detection and source health.
- Create `agent/src/opportunity_center/matching.py`: company profile construction and direct/industry/macro matching.
- Create `agent/src/opportunity_center/news_analysis.py`: cached batched LLM impact analysis and strict JSON parsing.
- Create `agent/src/opportunity_center/market_context.py`: price, trend, risk and optional HK valuation inputs.
- Create `agent/src/opportunity_center/strategy_context.py`: training-only strategy selection, OOS metrics and current target-weight action.
- Create `agent/src/opportunity_center/scoring.py`: deterministic dimension scores, weight redistribution and risk gates.
- Create `agent/src/opportunity_center/service.py`: refresh orchestration, task progress and snapshot assembly.
- Create `agent/src/opportunity_center/scheduler.py`: HK/US post-close due-date checks and catch-up loop.
- Create `agent/src/api/opportunity_routes.py`: opportunity list/detail/history/refresh endpoints.

**Existing backend integration**

- Modify `agent/api_server.py`: mount router; start and stop the scheduler; expose existing market helper callables through adapters only where needed.
- Modify `agent/src/paper_trading/hstech_best.py`: expose `strategy_params()` as a public catalog helper without changing endpoint output.
- Modify `pyproject.toml`: package opportunity-center JSON and notice files.
- Modify `NOTICE`: record the vendored `investment-news` source catalog.

**Tests**

- Create `agent/tests/opportunity_center/test_storage.py`.
- Create `agent/tests/opportunity_center/test_models.py`.
- Create `agent/tests/opportunity_center/test_feeds.py`.
- Create `agent/tests/opportunity_center/test_matching_analysis.py`.
- Create `agent/tests/opportunity_center/test_market_context.py`.
- Create `agent/tests/opportunity_center/test_strategy_context.py`.
- Create `agent/tests/opportunity_center/test_scoring.py`.
- Create `agent/tests/opportunity_center/test_service_scheduler.py`.
- Create `agent/tests/opportunity_center/test_routes.py`.

**Frontend**

- Modify `frontend/src/lib/api.ts`: opportunity types and API methods.
- Create `frontend/src/components/opportunities/OpportunityHistoryChart.tsx`: compact 30-session score history.
- Create `frontend/src/components/opportunities/TodayOpportunities.tsx`: filters, cards, details, refresh progress and navigation.
- Create `frontend/src/components/opportunities/__tests__/TodayOpportunities.test.tsx`.
- Modify `frontend/src/pages/Overview.tsx`: render opportunity center immediately below the page header/error.
- Modify `frontend/vite.config.ts`: proxy `/opportunities` in development.
- Modify `CHANGELOG.md`: document the user-facing feature and attribution-aware news pipeline.

---

### Task 1: Contracts, Source Catalog, and Attribution

**Files:**
- Create: `agent/src/opportunity_center/__init__.py`
- Create: `agent/src/opportunity_center/models.py`
- Create: `agent/src/opportunity_center/sources.json`
- Create: `agent/src/opportunity_center/THIRD_PARTY_NOTICE.md`
- Modify: `agent/src/paper_trading/hstech_best.py`
- Modify: `pyproject.toml`
- Modify: `NOTICE`
- Test: `agent/tests/opportunity_center/test_models.py`

**Interfaces:**
- Produces: `OpportunityItem`, `OpportunityDetail`, `OpportunityList`, `RefreshJob`, `NewsArticle`, `NewsImpact`, `StockContext`, `StrategyContext`, `MarketContext`.
- Produces: `SCORE_VERSION = "opportunity-v1"`, `STRATEGY_VERSION = "oos-holdout-v1"`.
- Produces: `strategy_params(strategy_name: str) -> dict[str, Any]` from the existing paper strategy catalog.

- [ ] **Step 1: Write the failing contract tests**

```python
from pydantic import ValidationError
import pytest

from src.opportunity_center.models import NewsImpact, OpportunityItem


def test_opportunity_item_rejects_score_outside_range():
    with pytest.raises(ValidationError):
        OpportunityItem(
            market="hk", code="0700", company_name="腾讯控股",
            snapshot_date="2026-06-29", score=101, level="优先关注",
            data_as_of="2026-06-29", score_version="opportunity-v1",
            strategy_version="oos-holdout-v1",
        )


def test_news_impact_uses_closed_direction_vocabulary():
    impact = NewsImpact(
        article_id="a1", market="us", code="NVDA", direction="positive",
        strength=80, confidence=75, horizon="medium", summary="需求改善", rationale="订单增长",
    )
    assert impact.direction == "positive"
```

- [ ] **Step 2: Run the tests and confirm the missing-package failure**

Run: `uv run pytest agent/tests/opportunity_center/test_models.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'src.opportunity_center'`.

- [ ] **Step 3: Add the version constants and strict Pydantic models**

Define these exact enums/fields in `models.py`:

```python
Market = Literal["hk", "us"]
OpportunityLevel = Literal["优先关注", "值得观察", "暂不参与", "数据不足"]
StrategyAction = Literal["entry", "add", "hold", "exit", "risk_exit", "wait", "none"]
MatchLevel = Literal["direct", "industry", "macro"]
ImpactDirection = Literal["positive", "neutral", "negative"]

class DimensionScores(BaseModel):
    strategy: float | None = Field(None, ge=0, le=100)
    trend: float | None = Field(None, ge=0, le=100)
    risk: float | None = Field(None, ge=0, le=100)
    news: float | None = Field(None, ge=0, le=100)
    valuation: float | None = Field(None, ge=0, le=100)

class OpportunityItem(BaseModel):
    market: Market
    code: str
    company_name: str
    snapshot_date: str
    score: float | None = Field(None, ge=0, le=100)
    score_change: float | None = None
    level: OpportunityLevel
    latest_action: StrategyAction = "none"
    signal_date: str | None = None
    strategy_name: str | None = None
    strategy_label: str | None = None
    primary_reason: str = ""
    risk_reasons: list[str] = Field(default_factory=list)
    dimensions: DimensionScores = Field(default_factory=DimensionScores)
    data_as_of: str
    stale: bool = False
    degraded: bool = False
    missing_dimensions: list[str] = Field(default_factory=list)
    score_version: str
    strategy_version: str
```

Also define the remaining contracts named in **Interfaces** and use `Field(ge=0, le=100)` for every score, strength and confidence field. `OpportunityList` must include `items`, `latest_success_at`, `active_job`, and `last_refresh_error`. `RefreshJob` must include `job_id`, `status`, `markets`, `trigger`, `completed`, `total`, timestamps and `error`.

Use these exact additional relationships: `NewsImpact` contains `match_level`; `OpportunityDetail` extends `OpportunityItem` with `news: list[NewsImpact]`, `explanations: list[str]` and `history_available: bool`; `StockContext` contains code/name plus aliases, brands, products, sector and industry; `StrategyContext` contains action, signal date, current weight and OOS metrics; `MarketContext` contains the latest price date, trend/risk inputs and optional valuation percentile.

- [ ] **Step 4: Vendor the source catalog with license data**

Copy `/Users/lianghuang/Desktop/investment-news/sources.json` verbatim to `agent/src/opportunity_center/sources.json`. Add `THIRD_PARTY_NOTICE.md` containing the full upstream MIT license and copyright line. Add this paragraph to root `NOTICE`:

```text
The opportunity-center RSS source catalog is adapted from investment-news,
Copyright (c) 2026 simonlin1212, under the MIT License. See
agent/src/opportunity_center/THIRD_PARTY_NOTICE.md.
```

Add package data:

```toml
"src.opportunity_center" = ["*.json", "*.md"]
```

- [ ] **Step 5: Expose the existing strategy parameter helper**

Rename `_strategy_params()` to `strategy_params()` in `hstech_best.py`, update its internal call, and keep a compatibility alias:

```python
def strategy_params(strategy_name: str) -> dict[str, Any]:
    if strategy_name in {"dca", "smart_dca", "enhanced_dca_trend"}:
        return {"frequency": "monthly"}
    if strategy_name == "grid":
        return {"grid_count": 5}
    return {}

_strategy_params = strategy_params
```

- [ ] **Step 6: Run focused tests**

Run: `uv run pytest agent/tests/opportunity_center/test_models.py agent/tests/test_hstech_best_strategy.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -f agent/src/opportunity_center agent/tests/opportunity_center pyproject.toml NOTICE agent/src/paper_trading/hstech_best.py
git commit -m "feat: define opportunity center contracts"
```

---

### Task 2: SQLite Persistence and Idempotency

**Files:**
- Create: `agent/src/opportunity_center/storage.py`
- Test: `agent/tests/opportunity_center/test_storage.py`

**Interfaces:**
- Consumes: all contracts from Task 1.
- Produces: `OpportunityStore(db_path: Path | None = None)`.
- Produces: `upsert_articles()`, `find_recent_articles()`, `save_matches()`, `get_news_analysis()`, `save_news_analysis()`, `create_job()`, `update_job()`, `get_active_job()`, `upsert_snapshot()`, `list_latest()`, `get_detail()`, `get_history()`, `has_market_refresh()`.

- [ ] **Step 1: Write failing persistence tests**

```python
def test_snapshot_unique_key_is_idempotent(tmp_path):
    store = OpportunityStore(tmp_path / "opportunities.db")
    item = sample_item(score=78)
    store.upsert_snapshot(item, trigger="scheduled", detail={"reason": "first"})
    store.upsert_snapshot(item.model_copy(update={"score": 80}), trigger="manual", detail={"reason": "updated"})
    rows = store.get_history("hk", "0700", limit=20)
    assert len(rows) == 1
    assert rows[0].score == 80


def test_news_analysis_cache_key_includes_stock_date_and_prompt(tmp_path):
    store = OpportunityStore(tmp_path / "opportunities.db")
    store.save_news_analysis(sample_impact(), "2026-06-29", "news-impact-v1")
    assert store.get_news_analysis("a1", "hk", "0700", "2026-06-29", "news-impact-v1") is not None
    assert store.get_news_analysis("a1", "hk", "0700", "2026-06-30", "news-impact-v1") is None
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest agent/tests/opportunity_center/test_storage.py -v`

Expected: FAIL because `OpportunityStore` does not exist.

- [ ] **Step 3: Create the schema in one transaction**

Create tables with these exact uniqueness rules:

```sql
CREATE TABLE IF NOT EXISTS news_sources (
  source_id TEXT PRIMARY KEY, name TEXT NOT NULL, sector TEXT NOT NULL,
  url TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  last_success_at TEXT, last_error TEXT
);
CREATE TABLE IF NOT EXISTS news_articles (
  article_id TEXT PRIMARY KEY, canonical_url TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL, summary TEXT NOT NULL, source_id TEXT NOT NULL,
  sector TEXT NOT NULL, published_at TEXT NOT NULL, fetched_at TEXT NOT NULL,
  title_fingerprint TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS news_matches (
  article_id TEXT NOT NULL, market TEXT NOT NULL, code TEXT NOT NULL,
  match_level TEXT NOT NULL, confidence REAL NOT NULL,
  PRIMARY KEY(article_id, market, code)
);
CREATE TABLE IF NOT EXISTS stock_profiles (
  market TEXT NOT NULL, code TEXT NOT NULL, payload_json TEXT NOT NULL,
  profile_version TEXT NOT NULL, expires_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY(market, code, profile_version)
);
CREATE TABLE IF NOT EXISTS news_analyses (
  article_id TEXT NOT NULL, market TEXT NOT NULL, code TEXT NOT NULL,
  analysis_date TEXT NOT NULL, prompt_version TEXT NOT NULL,
  payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(article_id, market, code, analysis_date, prompt_version)
);
CREATE TABLE IF NOT EXISTS opportunity_snapshots (
  market TEXT NOT NULL, code TEXT NOT NULL, snapshot_date TEXT NOT NULL,
  score_version TEXT NOT NULL, strategy_version TEXT NOT NULL,
  payload_json TEXT NOT NULL, trigger TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY(market, code, snapshot_date, score_version, strategy_version)
);
CREATE TABLE IF NOT EXISTS refresh_jobs (
  job_id TEXT PRIMARY KEY, status TEXT NOT NULL, markets_json TEXT NOT NULL,
  market_dates_json TEXT NOT NULL, trigger TEXT NOT NULL,
  completed INTEGER NOT NULL, total INTEGER NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error TEXT
);
```

Use WAL, `synchronous=NORMAL`, parameterized SQL, `model_dump_json()`, and atomic transactions. `list_latest()` must select the newest snapshot per `(market, code)` and apply filters after Pydantic validation.

- [ ] **Step 4: Add source-health and prior-score behavior tests**

Verify success resets failures to zero; failure increments it; `upsert_snapshot()` computes `score_change` from the previous market/code snapshot before writing.

- [ ] **Step 5: Run tests**

Run: `uv run pytest agent/tests/opportunity_center/test_storage.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/src/opportunity_center/storage.py agent/tests/opportunity_center/test_storage.py
git commit -m "feat: persist opportunity snapshots and news"
```

---

### Task 3: RSS Ingestion, Matching, and Cached AI Analysis

**Files:**
- Create: `agent/src/opportunity_center/feeds.py`
- Create: `agent/src/opportunity_center/matching.py`
- Create: `agent/src/opportunity_center/news_analysis.py`
- Test: `agent/tests/opportunity_center/test_feeds.py`
- Test: `agent/tests/opportunity_center/test_matching_analysis.py`

**Interfaces:**
- Produces: `canonicalize_url(url: str) -> str`, `parse_feed(xml: str, source: NewsSource, now: datetime) -> list[NewsArticle]`.
- Produces: `FeedIngestor(store, source_path, max_concurrency=12).refresh(now) -> list[NewsArticle]`.
- Produces: `build_stock_context(market, code, quote_name, profile) -> StockContext`.
- Produces: `match_articles(context, articles) -> list[NewsMatch]`.
- Produces: `NewsAnalyzer(store, llm_factory=ChatLLM).analyze(context, matches, analysis_date) -> list[NewsImpact]`.

- [ ] **Step 1: Write parser and dedupe tests with local XML**

```python
def test_parse_atom_and_strip_tracking_query():
    rows = parse_feed(ATOM_XML, SOURCE, datetime(2026, 6, 29, tzinfo=timezone.utc))
    assert rows[0].canonical_url == "https://example.com/story"
    assert rows[0].title == "NVIDIA launches platform"


def test_near_duplicate_titles_keep_one_article(tmp_path):
    store = OpportunityStore(tmp_path / "db.sqlite")
    saved = store.upsert_articles([
        article("NVIDIA launches new AI platform"),
        article("Nvidia launches a new AI platform"),
    ])
    assert len(saved) == 1
```

- [ ] **Step 2: Verify failure, then implement safe feed parsing**

Run: `uv run pytest agent/tests/opportunity_center/test_feeds.py -v`

Expected before implementation: FAIL. Implement RSS 2.0 and Atom parsing with `xml.etree.ElementTree`, `httpx.AsyncClient(timeout=15, follow_redirects=True)`, a semaphore of 12, seven-day cutoff, and at most six rows per source. Remove `utm_*`, `ref`, `source` and URL fragments. Near-duplicate titles on the same UTC date use `SequenceMatcher >= 0.92` after lowercase/CJK-alphanumeric normalization.

- [ ] **Step 3: Add direct/industry/macro matching tests**

```python
def test_matching_priority_and_confidence():
    context = StockContext(
        market="us", code="NVDA", company_name="NVIDIA Corporation",
        aliases=["NVIDIA", "英伟达"], brands=["CUDA"], products=["Blackwell"],
        sector="Technology", industry="Semiconductors",
    )
    matches = match_articles(context, [
        article("NVIDIA Blackwell demand rises", sector="semi"),
        article("Semiconductor cycle improves", sector="semi"),
        article("Federal Reserve holds rates", sector="macro"),
    ])
    assert [m.match_level for m in matches] == ["direct", "industry", "macro"]
    assert matches[0].confidence > matches[1].confidence > matches[2].confidence
```

`build_stock_context()` must use symbol, quote name and yfinance profile fields. It may enrich aliases/brands/products with one cached LLM profile extraction, but when LLM is unavailable it must deterministically fall back to code/name/sector/industry.

- [ ] **Step 4: Add strict batched LLM/caching tests**

Use a stub returning this exact JSON shape:

```json
{"items":[{"article_id":"a1","direction":"negative","strength":85,"confidence":80,"horizon":"short","summary":"出口限制扩大","rationale":"直接影响可销售市场"}]}
```

Assert that two calls for the same `(article_id, market, code, analysis_date, prompt_version)` invoke the stub once. Assert malformed output returns no impact, records a warning, and does not manufacture a neutral score.

- [ ] **Step 5: Implement batched analysis**

Analyze at most 18 items per stock/day: 10 direct, 5 industry, 3 macro, newest first. Batch up to 12 items per LLM call. Strip optional markdown fences, parse the entire JSON object, validate each row with `NewsImpact`, and cache valid rows as `NEWS_PROMPT_VERSION = "news-impact-v1"`.

- [ ] **Step 6: Run focused tests**

Run: `uv run pytest agent/tests/opportunity_center/test_feeds.py agent/tests/opportunity_center/test_matching_analysis.py -v`

Expected: PASS without network or real LLM calls.

- [ ] **Step 7: Commit**

```bash
git add agent/src/opportunity_center/feeds.py agent/src/opportunity_center/matching.py agent/src/opportunity_center/news_analysis.py agent/tests/opportunity_center
git commit -m "feat: ingest and analyze watchlist news"
```

---

### Task 4: Market Inputs and No-Lookahead Strategy Context

**Files:**
- Create: `agent/src/opportunity_center/market_context.py`
- Create: `agent/src/opportunity_center/strategy_context.py`
- Modify: `agent/src/paper_trading/hstech_best.py`
- Test: `agent/tests/opportunity_center/test_strategy_context.py`
- Test: `agent/tests/opportunity_center/test_market_context.py`

**Interfaces:**
- Produces: `load_market_context(market: Market, code: str, as_of: date) -> MarketContext`.
- Produces: `evaluate_strategy_context(market: Market, code: str, as_of: date, start_date="2020-01-01") -> StrategyContext`.
- `StrategyContext` includes selected strategy name/label, `action`, `signal_date`, current weight, OOS return/Sharpe/max drawdown and `data_as_of`.

- [ ] **Step 1: Write the future-mutation regression test**

```python
def test_strategy_context_ignores_rows_after_as_of(monkeypatch):
    base = make_ohlcv("2020-01-01", "2026-06-29")
    mutated = append_extreme_future_rows(base, "2026-06-30", periods=30)
    first = evaluate_frame(base, as_of=date(2026, 6, 29))
    second = evaluate_frame(mutated, as_of=date(2026, 6, 29))
    assert second.selected_strategy == first.selected_strategy
    assert second.action == first.action
    assert second.oos_sharpe == pytest.approx(first.oos_sharpe)
```

Also test that a final target-weight change from `0 -> 1` is `entry`, `0.5 -> 1` is `add`, `1 -> 0` is `exit`, unchanged positive is `hold`, and unchanged zero is `wait`. Do not derive the current action from the engine's forced `end_of_backtest` trade.

- [ ] **Step 2: Implement chronological holdout selection**

1. Trim OHLCV to `index.date <= as_of` before any calculation.
2. Require at least 504 trading rows.
3. Use the final 252 rows as OOS; all earlier rows are training.
4. Run every `STRATEGY_NAMES` candidate on training only and choose by existing `(Sharpe, total return, max drawdown)` ordering.
5. Generate the selected strategy's target-weight series over all rows up to `as_of`.
6. Evaluate OOS metrics only on the final 252 rows, with target weights generated from past/current bars.
7. Derive current action from target-weight changes, not forced liquidation records.

Expose a pure `evaluate_frame(frame, holding, as_of)` helper so tests never hit Yahoo.

- [ ] **Step 3: Test and implement deterministic trend/risk inputs**

For daily closes up to `as_of`, calculate:

```python
returns = close.pct_change().dropna()
sma50 = close.rolling(50).mean().iloc[-1]
sma200 = close.rolling(200).mean().iloc[-1]
momentum63 = close.iloc[-1] / close.iloc[-64] - 1
annual_vol = returns.tail(63).std() * math.sqrt(252)
downside_vol = returns.tail(63).clip(upper=0).std() * math.sqrt(252)
max_drawdown = (close / close.cummax() - 1).min()
volume_ratio = volume.tail(20).mean() / volume.tail(60).mean()
```

HK valuation: request five-year PE history through a focused helper adapted from `_fetch_valuation_history`; use PB only when PE has fewer than 30 positive points. Score input is the percentile rank of the latest positive value. US valuation remains `None` in v1 rather than inventing a comparison baseline.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest agent/tests/opportunity_center/test_strategy_context.py agent/tests/opportunity_center/test_market_context.py agent/tests/test_paper_trading_lookahead.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/src/opportunity_center/market_context.py agent/src/opportunity_center/strategy_context.py agent/tests/opportunity_center agent/src/paper_trading/hstech_best.py
git commit -m "feat: build no-lookahead opportunity inputs"
```

---

### Task 5: Deterministic Scoring and Risk Gates

**Files:**
- Create: `agent/src/opportunity_center/scoring.py`
- Test: `agent/tests/opportunity_center/test_scoring.py`

**Interfaces:**
- Consumes: `StrategyContext`, `MarketContext`, `list[NewsImpact]`, previous score.
- Produces: `score_opportunity(...) -> OpportunityDetail`.
- Produces pure helpers: `score_strategy`, `score_trend`, `score_risk`, `score_news`, `score_valuation`, `weighted_score`, `apply_risk_gates`.

- [ ] **Step 1: Write exact formula tests**

```python
def test_missing_valuation_redistributes_weight():
    values = DimensionScores(strategy=80, trend=70, risk=60, news=50, valuation=None)
    assert weighted_score(values) == pytest.approx(
        (80 * .40 + 70 * .20 + 60 * .20 + 50 * .15) / .95
    )


def test_exit_signal_caps_high_raw_score():
    detail = score_fixture(action="exit", raw_dimensions=(95, 95, 95, 95, 95))
    assert detail.level == "暂不参与"
    assert detail.score == pytest.approx(95)


def test_missing_strategy_is_data_insufficient():
    detail = score_fixture(strategy=None)
    assert detail.level == "数据不足"
    assert detail.score is None
```

- [ ] **Step 2: Implement exact dimension formulas**

Use `clamp(0, 100)` around every formula:

```python
ACTION_BASE = {"entry": 90, "add": 85, "hold": 72, "wait": 45, "exit": 20, "risk_exit": 10, "none": 40}
strategy_quality = clamp(50 + 20 * oos_sharpe + 40 * oos_return + 50 * oos_max_drawdown)
strategy_score = clamp(0.70 * ACTION_BASE[action] + 0.30 * strategy_quality)

trend_score = clamp(
    50
    + (15 if close > sma200 else -15)
    + (10 if sma50 > sma200 else -10)
    + clamp(momentum63 * 100, -15, 15)
    + volume_confirmation
)

risk_score = clamp(100 - min(annual_vol, 1) * 45
                         - min(abs(max_drawdown), 1) * 40
                         - min(downside_vol, 1) * 15)
valuation_score = 100 * (1 - valuation_percentile)
```

For news, map positive/neutral/negative to `+1/0/-1`; weight match levels `1.0/0.4/0.2`; use recency decay `exp(-age_days / 3)`; multiply by strength and confidence; set `news_score = clamp(50 + weighted_mean_signed_strength / 2)`. No matched news is neutral `50`; matched news with unavailable analysis is `None`. Set `volume_confirmation` to `+10` when 63-session momentum is positive and `volume_ratio >= 1.2`, `-10` when momentum is negative and `volume_ratio >= 1.2`, otherwise `0`.

- [ ] **Step 3: Implement gates and explanations**

Apply in order: stale/failed strategy -> `数据不足`; exit/risk-exit -> `暂不参与`; direct negative news with strength >= 80 and confidence >= 75 -> lower one level; annual volatility >= 0.80 or 20-session return <= -0.20 -> lower one level. Persist every gate reason. Generate `primary_reason` from the largest positive/negative contribution, never from free-form AI text alone.

- [ ] **Step 4: Run scoring tests**

Run: `uv run pytest agent/tests/opportunity_center/test_scoring.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/src/opportunity_center/scoring.py agent/tests/opportunity_center/test_scoring.py
git commit -m "feat: score watchlist opportunities"
```

---

### Task 6: Refresh Orchestration and Market-Close Scheduler

**Files:**
- Create: `agent/src/opportunity_center/service.py`
- Create: `agent/src/opportunity_center/scheduler.py`
- Test: `agent/tests/opportunity_center/test_service_scheduler.py`

**Interfaces:**
- Produces: `OpportunityService.start_refresh(markets, trigger, force=False) -> RefreshJob`.
- Produces: `OpportunityService.run_job(job_id) -> None`, `get_list()`, `get_detail()`, `get_history()`.
- Produces: `due_market_dates(now: datetime) -> dict[Market, date]`.
- Produces: `OpportunityScheduler.start()`, `stop()`, `run_once(now=None)`.

- [ ] **Step 1: Write orchestration tests with fake providers**

Verify one feed refresh per job, one strategy evaluation per watchlist stock, partial stock failure creates `数据不足` without failing successful stocks, and a concurrent request returns the active job instead of starting duplicate work. A later same-day manual request creates a new incremental job but upserts the same snapshot keys and reuses same-day AI analyses.

```python
job = service.start_refresh(["hk", "us"], trigger="manual")
await service.run_job(job.job_id)
assert store.list_latest(market=None, signal=None, level=None)[0].code == "0700"
assert fake_news.refresh_calls == 1
```

- [ ] **Step 2: Implement bounded background orchestration**

Use one process-wide `asyncio.Lock`; strategy calculations run sequentially through `asyncio.to_thread()` so 25-strategy pools do not monopolize the backend. News network fetching remains bounded at 12 concurrent feeds. Update job progress after every stock. Preserve the latest successful snapshot when a refresh fails and record the new job error separately. Deduplicate only currently queued/running jobs; a later manual refresh must run again. `force=True` bypasses feed/market freshness caches, but never bypasses same-day AI-analysis or snapshot uniqueness.

Order for each job:

1. Read codes from `WatchlistStore` for requested markets.
2. Refresh feeds once and upsert articles/source health.
3. For each stock, resolve quote/profile, market context and OOS strategy context.
4. Match and analyze only relevant uncached articles.
5. Score and upsert the daily snapshot.
6. Complete the job with per-stock errors retained in structured form.

`get_list()` sorts stocks with an actionable signal from the latest seven calendar days first (`entry/add/exit/risk_exit`, newest signal first), then sorts all remaining stocks by score descending. Each stock appears once.

- [ ] **Step 3: Write timezone/DST scheduler tests**

```python
def test_hk_due_after_close_and_us_not_yet_due():
    now = datetime(2026, 6, 29, 9, 0, tzinfo=timezone.utc)  # 17:00 HK, 05:00 NY
    assert due_market_dates(now) == {"hk": date(2026, 6, 29)}


def test_us_close_uses_new_york_dst():
    now = datetime(2026, 6, 29, 20, 30, tzinfo=timezone.utc)  # 16:30 EDT
    assert due_market_dates(now)["us"] == date(2026, 6, 29)
```

- [ ] **Step 4: Implement scheduler catch-up**

Use `ZoneInfo("Asia/Hong_Kong")` and `ZoneInfo("America/New_York")`, close cutoff `16:15`, and the most recent weekday. Poll every 300 seconds. `run_once()` checks `has_market_refresh(market, market_date)` before scheduling, so restarts after close catch up once and weekends do not repeat jobs.

- [ ] **Step 5: Run tests**

Run: `uv run pytest agent/tests/opportunity_center/test_service_scheduler.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/src/opportunity_center/service.py agent/src/opportunity_center/scheduler.py agent/tests/opportunity_center/test_service_scheduler.py
git commit -m "feat: refresh opportunities after market close"
```

---

### Task 7: FastAPI Router and Structured Errors

**Files:**
- Create: `agent/src/api/opportunity_routes.py`
- Modify: `agent/api_server.py`
- Test: `agent/tests/opportunity_center/test_routes.py`

**Interfaces:**
- `GET /opportunities?market=&signal=&level=` -> `OpportunityList`.
- `GET /opportunities/{market}/{code}?date=` -> `OpportunityDetail`.
- `GET /opportunities/{market}/{code}/history?limit=30` -> list of dated score points.
- `POST /opportunities/refresh` body `{ "markets": ["hk", "us"], "force": false }` -> `RefreshJob` with HTTP 202.
- `GET /opportunities/refresh/{job_id}` -> `RefreshJob`.

- [ ] **Step 1: Write isolated router tests**

```python
def _app(fake_service):
    app = FastAPI()
    register_opportunity_routes(app, require_auth=lambda: None, service=fake_service, start_scheduler=False)
    return app


def test_refresh_returns_json_job(fake_service):
    response = TestClient(_app(fake_service)).post("/opportunities/refresh", json={"markets": ["hk"]})
    assert response.status_code == 202
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["status"] == "queued"
```

Cover invalid market/code (422/400), missing detail/job (404), and provider failure returned as `{ "detail": "..." }`, never HTML.

- [ ] **Step 2: Implement dependency-injected router**

`register_opportunity_routes()` accepts optional service and scheduler instances for tests. Register `/opportunities/refresh` and `/opportunities/refresh/{job_id}` before `/opportunities/{market}/{code}` so `refresh` cannot be consumed as a market value. Protect list/detail/history/refresh endpoints with `require_local_or_auth`. Set `Cache-Control: no-store` because application-level snapshots control staleness. The POST route stores the returned `asyncio.Task` in a runtime task map and removes it in a done callback; never leave an unreferenced background task.

- [ ] **Step 3: Wire lifecycle in `api_server.py`**

Mount after authentication helpers are defined:

```python
from src.api.opportunity_routes import register_opportunity_routes

_opportunity_runtime = register_opportunity_routes(app, require_auth=require_local_or_auth)
```

Start scheduler from the existing startup hook after preflight and add a shutdown hook that awaits `scheduler.stop()`. Avoid duplicate scheduler tasks under repeated test startup.

- [ ] **Step 4: Run API tests and OpenAPI smoke test**

Run: `uv run pytest agent/tests/opportunity_center/test_routes.py agent/tests/test_spa_deep_link.py -v`

Expected: PASS and `/opportunities` appears in `app.openapi()["paths"]`.

- [ ] **Step 5: Commit**

```bash
git add agent/src/api/opportunity_routes.py agent/api_server.py agent/tests/opportunity_center/test_routes.py
git commit -m "feat: expose opportunity center API"
```

---

### Task 8: Frontend API Contracts

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/vite.config.ts`
- Test: `frontend/src/lib/__tests__/apiAuth.test.ts` (regression only)

**Interfaces:**
- Produces TypeScript mirrors: `OpportunityItem`, `OpportunityDetail`, `OpportunityList`, `OpportunityHistoryPoint`, `OpportunityRefreshJob`.
- Produces API methods: `getOpportunities`, `getOpportunityDetail`, `getOpportunityHistory`, `refreshOpportunities`, `getOpportunityRefreshJob`.

- [ ] **Step 1: Add exact TypeScript types**

```typescript
export type OpportunityLevel = "优先关注" | "值得观察" | "暂不参与" | "数据不足";
export type OpportunityAction = "entry" | "add" | "hold" | "exit" | "risk_exit" | "wait" | "none";

export interface OpportunityItem {
  market: "hk" | "us";
  code: string;
  company_name: string;
  snapshot_date: string;
  score: number | null;
  score_change: number | null;
  level: OpportunityLevel;
  latest_action: OpportunityAction;
  signal_date: string | null;
  strategy_label: string | null;
  primary_reason: string;
  risk_reasons: string[];
  dimensions: Record<"strategy" | "trend" | "risk" | "news" | "valuation", number | null>;
  data_as_of: string;
  stale: boolean;
  degraded: boolean;
  missing_dimensions: string[];
}
```

- [ ] **Step 2: Add URLSearchParams-based methods**

```typescript
getOpportunities: (filters: OpportunityFilters = {}) => {
  const q = new URLSearchParams();
  if (filters.market && filters.market !== "all") q.set("market", filters.market);
  if (filters.signal && filters.signal !== "all") q.set("signal", filters.signal);
  if (filters.level && filters.level !== "all") q.set("level", filters.level);
  return request<OpportunityList>(`/opportunities${q.size ? `?${q}` : ""}`);
},
refreshOpportunities: (markets: Array<"hk" | "us">, force = false) =>
  request<OpportunityRefreshJob>("/opportunities/refresh", {
    method: "POST", body: JSON.stringify({ markets, force }),
  }),
```

Add `"/opportunities": apiProxy` to Vite proxy config.

- [ ] **Step 3: Type-check and run the API regression tests**

Run: `npm --prefix frontend run build`

Expected: PASS.

Run: `npm --prefix frontend run test:run -- src/lib/__tests__/apiAuth.test.ts`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts frontend/vite.config.ts
git commit -m "feat: add opportunity center client"
```

---

### Task 9: Today Opportunities UI and Forecast Navigation

**Files:**
- Create: `frontend/src/components/opportunities/OpportunityHistoryChart.tsx`
- Create: `frontend/src/components/opportunities/TodayOpportunities.tsx`
- Create: `frontend/src/components/opportunities/__tests__/TodayOpportunities.test.tsx`
- Modify: `frontend/src/pages/Overview.tsx`

**Interfaces:**
- `TodayOpportunities` owns list/detail/history/refresh state.
- `OpportunityHistoryChart({ points, height: 160 })` renders score and 55/75 threshold guides.
- Stock link target is `/forecast#forecast-card-${market}-${code.toUpperCase()}`.

- [ ] **Step 1: Write user-visible behavior tests**

Mock `api` and assert:

```typescript
it("renders action-first ordering and links to forecast card", async () => {
  render(<MemoryRouter><TodayOpportunities /></MemoryRouter>);
  expect(await screen.findByText("腾讯控股")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /腾讯控股/ })).toHaveAttribute(
    "href", "/forecast#forecast-card-hk-0700"
  );
});

it("polls a refresh job and reloads after completion", async () => {
  await userEvent.click(screen.getByRole("button", { name: "刷新机会" }));
  expect(api.refreshOpportunities).toHaveBeenCalledWith(["hk", "us"], false);
  await waitFor(() => expect(api.getOpportunities).toHaveBeenCalledTimes(2));
});
```

Also cover filters, expansion fetching history, `数据不足`, stale timestamp, partial degradation and readable API failure.

- [ ] **Step 2: Implement the compact history chart**

Use the shared ECharts wrapper and theme. Render one gray score line, horizontal dashed guides at 55 and 75, fixed 0-100 y-axis, no toolbox/zoom, and a concise tooltip containing date, score and level.

- [ ] **Step 3: Implement the opportunity surface**

Layout order inside the component:

1. Header, data timestamp and icon refresh button with tooltip.
2. Market segmented control; signal and level menus.
3. Recent actionable names first, then remaining rows by score.
4. Each 8px-radius row shows company/code, level, score/change, latest strategy action/date and primary reason.
5. Expanded row shows five dimension bars, risk reasons, up to five relevant news links, missing/degraded labels and 30-session history chart.

Use red for entry/add, emerald for exit/risk exit, neutral gray for hold/wait. Do not use nested cards; expanded details are an unframed section inside the row.

- [ ] **Step 4: Mount below the Overview header**

Import and render:

```tsx
<TodayOpportunities />
```

Place it after the page-level error and before index sections, so it is the first decision surface without replacing existing watchlists or charts.

- [ ] **Step 5: Run component tests and build**

Run: `npm --prefix frontend run test:run -- src/components/opportunities/__tests__/TodayOpportunities.test.tsx`

Expected: PASS.

Run: `npm --prefix frontend run build`

Expected: PASS with no unused TypeScript symbols.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/opportunities frontend/src/pages/Overview.tsx
git commit -m "feat: show daily watchlist opportunities"
```

---

### Task 10: End-to-End Verification, Product Log, and Visual QA

**Files:**
- Modify: `CHANGELOG.md`
- Modify as defects require: only files introduced or integrated by Tasks 1-9.

**Interfaces:**
- Validates the completed feature; introduces no new product scope.

- [ ] **Step 1: Add the changelog entry**

Document: daily opportunity ranking, strategy-first score, post-close refresh, local history, relevant-news attribution, structured degradation, and research-only disclaimer.

- [ ] **Step 2: Run all focused backend tests**

Run:

```bash
uv run pytest agent/tests/opportunity_center agent/tests/test_hstech_best_strategy.py agent/tests/test_paper_trading_lookahead.py agent/tests/test_spa_deep_link.py -v
```

Expected: PASS.

- [ ] **Step 3: Run lint and frontend verification**

Run:

```bash
uv run ruff check agent/src/opportunity_center agent/src/api/opportunity_routes.py agent/tests/opportunity_center
npm --prefix frontend run test:run -- src/components/opportunities src/lib/__tests__/apiAuth.test.ts
npm --prefix frontend run build
```

Expected: all commands PASS.

- [ ] **Step 4: Run local manual acceptance**

Start the API and Vite using the existing `scripts/dev`. In the browser verify:

1. At least three HK and three US watchlist stocks produce snapshots.
2. Repeating refresh on the same day does not duplicate articles, AI analyses or snapshots.
3. A recent action appears once per stock and its link scrolls to the correct forecast card.
4. Disconnect/disable LLM config: relevant raw news remains, news dimension degrades, other scores remain visible.
5. Simulate one failed feed and one failed stock: the page remains usable and shows exact failure/time.
6. Check desktop 1440x900 and mobile 390x844: no overlapping text, clipped buttons, nested cards or horizontal overflow.

- [ ] **Step 5: Inspect the local database invariants**

Run a read-only SQLite query against `~/.vibe-trading/opportunity_center.db` and confirm unique counts for snapshots and analyses equal their composite distinct keys. Confirm source failures and last-success timestamps update.

- [ ] **Step 6: Final regression smoke test**

Run: `uv run pytest agent/tests/test_price_history_periods.py agent/tests/test_forecast_strategy.py -v`

Expected: PASS; opportunity integration must not alter existing chart history or forecast strategy behavior.

- [ ] **Step 7: Commit verification/docs fixes**

```bash
git add CHANGELOG.md agent frontend
git commit -m "docs: record opportunity center release"
```

---

## Execution Notes

- Implement tasks in order; Tasks 3 and 4 may be developed in parallel only after Tasks 1-2 are merged because they share contracts/storage.
- Keep every network and LLM test stubbed. Real RSS/Yahoo/LLM calls belong only in manual acceptance.
- Never expose the local `/Users/lianghuang/Desktop/investment-news` path at runtime; it is an implementation-time source for the vendored catalog only.
- When a task reveals an existing unrelated failure, record it separately and do not widen this feature's scope.
