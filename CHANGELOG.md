# Changelog

All notable changes to Vibe-Trading are documented in this file.
This project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- **统一行情指标口径。** 总览与恒生科技价格图统一由后端计算复权区间收益、每日定投收益、每日定投最大亏损、买入持有最大亏损和最大回撤；`1D` 使用最近交易日昨收，其他区间使用起点前一交易日，前端不再重复实现公式。
- **行情数据质量与缓存。** OHLCV 增加重复日期、非正价格、异常高低价、缺失成交量和数据过期检查；缺失成交量保持为空而非伪造为零，无效数据不生成有效指标，也不能覆盖已有缓存。指标缓存随行情修订、区间起点和公式版本自动失效。
- **模拟盘策略调整。** “一年定投后持有”改为“两年定投后持有”，默认按月分 24 期完成建仓；“攻守轮动”从策略选择、最优策略和多时间段测试候选中移除，旧历史记录仍可兼容读取。
- **多时间段年度滚动。** 模拟盘稳健性测试由每两年移动一次改为 3 年窗口每年滚动，完整保留最多 20 年数据内的年度窗口（如 2012–2015、2013–2016）并继续追加全历史对照。
- **A股重大历史事件。** 总览中的 A 股自选股也可检测重大涨跌并使用联网 DeepSeek 归因，采用沪深 300 作为同期基准；沿用先显示图表、近五年提前归因和本地永久缓存机制。
- **重大事件跨区间缓存。** 首次打开 1Y、3Y 或 5Y 时统一提前归因近 5 年并永久写入本地 SQLite；切换常用区间只按日期过滤，ALL 仅补算五年前缺失事件，已完成的事件不会重复消耗 DeepSeek。
- **总览即时行情与事件分阶段加载。** 指数卡片刷新页面时先恢复浏览器会话快照并在后台静默更新，不再反复显示骨架；重大历史事件先完成本地异动检测并立即绘制涨跌标记，DeepSeek 联网归因在图表显示后继续运行并原位更新总结。
- **重大历史事件快速归因。** 港股和美股历史异动不再逐窗口抓取并堆叠杂乱新闻，改为将当前区间的全部异动一次批量交给启用联网搜索的 `deepseek/deepseek-v4-flash:online` 生成简短中文归因；无法确认时明确标记原因不确定，新版结果继续永久缓存。
- **走势预测稳健策略。** 每只自选股改用模拟盘多时间段平均排名选择策略，最近一年独立样本外验证；策略选择缓存一年，最新交易信号每日刷新，验证未通过时不输出买卖信号。
- **短历史策略降级。** 具有 2～4 年历史的标的改用 1 年滚动窗口和 6 个月样本外验证，并明确标记低可信度；少于 2 年仍不强行推荐。
- **预测图交易标志。** 买卖三角改用走势图当日显示价格定位，Tooltip 保留策略复权成交价；回测结束统计平仓不再画成真实卖出标志。
- **预测页面会话恢复。** 浏览器刷新时立即恢复精简的预测和策略结果，再在后台静默校验更新，避免每次刷新重新出现整页加载状态。
- **策略收益区间。** 走势预测的策略总收益同步显示实际回测跨度，长期历史按年、短期历史按月标注。
- **多时间段测试范围。** 模拟盘稳健性测试自动使用组合共同可用历史，最多回溯 20 年；新上市或历史较短的标的会限制共同起点并在结果中标明。
- **最近策略信号纠正。** 走势预测不再把回测结束时的统计平仓当作真实卖出信号；同日再平衡时展示最后发生的开仓或平仓状态。
- **中文新闻来源修复。** 修复中文媒体来源 ID 冲突和旧数据库迁移，避免多个中文 RSS 互相覆盖；单个失效来源不影响其他新闻刷新。
- **新闻中心语言切换。** 新增中文新闻与英文新闻 Tab，默认显示中文；投资简报、重大新闻、统计和列表随语言同步切换。
- **机会扫描市场与名称。** 移除 A 股扫描入口，保留港股和美股；港股当前结果及历史快照均显示公司名称与股票代码。

### Added
- **深跌分批止盈策略。** 模拟盘新增固定阈值反转策略：相对已知历史最高点回撤 40% 后分六个月等额建仓，持仓相对加权平均成本上涨 30% 后全部卖出；不设置止损，并自动参与最优策略和多时间段测试。
- **回撤加速建仓策略。** 模拟盘采用 T0 投入 25%、剩余 75% 分十二个月固定建仓；月初相对 T0 收盘回撤达到 10% 时当期投入总预算的 20%，达到 20% 时一次性投入全部剩余资金，并自动参与最优策略和多时间段测试。
- **重大历史事件。** 港股和美股自选股价格卡片新增按需加载的历史异动分析，
  使用 1/3/5 日固定阈值与过去波动过滤识别大涨大跌，在图上标记事件区间，
  点击三角即可查看证据、基准对照和置信度；分析结果永久缓存在本地，证据不足时
  明确显示“原因未确认”。港股复用东方财富财经新闻，美股使用 Alpaca 历史新闻；
  通用网页搜索不再参与事件归因。
- **机会与新闻联动。** 今日机会新增“策略信号驱动”“新闻事件驱动”和
  “策略 + 新闻共振”归因，展开后展示策略与新闻贡献及入榜说明；排名公式保持不变，
  没有可靠新闻分析时不会把新闻评分误标为事件驱动。
- **独立新闻中心。** 新增自选股、主要指数与重点行业新闻工作台，提供按日期生成的
  可追溯投资简报、重大新闻置顶、行业/影响方向/关键词/自选股筛选和原文链接；
  复用现有 RSS 去重、本地 SQLite、股票匹配与影响分析，不影响恒生科技原新闻页。
- **机会扫描多市场。** 机会扫描新增美股、A 股和港股切换，分别使用标普 500、
  沪深 300和恒生科技成份股；每个股票池独立保存扫描历史、收益跟踪与质量校准，
  更新按钮只运行当前市场。缺少市场专属因子白名单时自动降级为异常与事件扫描，
  并在页面明确提示。
- **今日机会历史回填。** 新增可重复运行的两年固定自选股月末回放，批量复用
  行情并严格按截面日期执行无未来数据评分，结果直接进入 5/20/60 日质量统计；
  回填样本明确披露当前自选股带来的幸存者偏差。自选股成员变化从现在起按日期
  留档，为未来真实历史名单回放提供基础。
- **今日机会质量校准。** 每日刷新后增量验证历史机会在 5/20/60 个交易日的
  绝对收益和相对基准超额收益，支持“前三名/全部机会”对比，并展示胜率、
  跑赢率、平均收益、平均超额收益和最大亏损。信号统一按下一交易日开盘成交，
  港股对比恒生指数，美股对比标普 500，未成熟样本明确标记为积累中。
- **自选股机会中心。** 总览顶部新增港股/美股每日机会排序，综合无未来数据的
  样本外策略信号、趋势、风险、新闻影响和可用估值，展示优先级、开平仓动作、
  评分历史与可追溯新闻来源；支持市场、信号和等级筛选，并在港股和美股收盘后
  自动刷新。新闻源目录改编自 `investment-news`，完整 MIT 归属见项目 `NOTICE`。
- **HSTECH research workbench.** Added a dedicated 恒生科技 research surface with
  price/valuation charts, TimesFM forecast cone, news, reports, AI summaries,
  factor research panels, and benchmarked Q1/Q2 portfolio views.
- **HSTECH factor portfolio views.** Added current Q1 and Q2 constituents with
  company names, 24-hour cached portfolio results, and separate Q1/Q2
  Walk-Forward validation panels. Q1 Walk-Forward is now pure-long first:
  headline metrics, Q1-only equity curve, and long-short as secondary evidence.
- **Q1 pure-long benchmarking.** Added `Q1 纯多 vs 基准` comparison against
  HSTECH equal-weight, universe equal-weight, 03033.HK ETF, and a DCA baseline.
  The benchmark panel is collapsed by default and calculates only when opened.
- **DCA analytics.** Added DCA baselines to forecast strategy backtests and daily
  DCA return / max-drawdown metrics to price charts for non-`1D` windows,
  including the Overview and HSTECH charts.
- **Forecast and scan result caching.** Added 48-hour disk caching for TimesFM
  forecast charts, 24-hour caching for Q1/Q2 portfolio views, and result caching
  for expensive quintile / walk-forward / benchmark scans.
- **HSTECH smart T strategy.** Added a default-collapsed `智能做T策略`
  backtest panel for trapped-position cost reduction, with current signal,
  cost-basis metrics, realized spread, win rate, trade log, and equity curve.

### Changed
- **HSTECH API routing.** Split the API server surface into focused routers for
  settings, market data, forecast, sessions, live, runs, and scan-related
  endpoints, reducing the `api_server.py` monolith.
- **HSTECH forecast UX.** Forecast refresh still bypasses cache, while normal
  chart loads reuse the two-day forecast cache. Strategy backtests now compare
  against both buy-and-hold and DCA baselines.
- **HSTECH news summaries.** AI summaries in the News tab now summarize only
  same-day news; historical news remains visible in the list but is excluded
  from the daily AI summary prompt.
- **Q1/Q2 factor UX.** Q1 and Q2 controls are now opt-in where expensive:
  benchmark and walk-forward panels stay collapsed until the user opens them,
  reducing accidental long-running scans.

### Fixed
- **Frontend API error handling.** Non-JSON backend responses are now surfaced as
  readable `API returned a non-JSON response` errors instead of crashing on an
  `Unexpected token` parse failure.
- **03033.HK benchmark lookup.** ETF benchmark loading now retries the unpadded
  Hong Kong ticker form when yfinance rejects the padded symbol.
- **Forecast reliability.** The HSTECH forecast request path retries transient
  500 errors and avoids overlapping in-flight forecast requests.

## [0.1.9] — 2026-06-01

### Added
- **Connector-first broker profiles (IBKR + Robinhood).** Trading access now
  starts from a selectable connector profile rather than separate broker/live
  entry points; `vibe-trading connector list/use/check/account/positions/orders/quote/history`
  and the MCP `trading_*` tools share the selected profile, with paper/live as
  a property under the connector. IBKR is usable immediately as a local
  read-only TWS / IB Gateway profile; the official IBKR remote MCP path is
  seeded as an OAuth `mcp.read` probe until stable read tool names ship.
  Robinhood Agentic Trading is a bounded connector behind OAuth, a committed
  mandate, an order guard, an audit ledger, and an instant halt switch.
- **Research Goal runtime.** Long-running, research-only goals with auditable
  checklist criteria, budgets, and a `/goal` CLI command, plus REST + MCP
  endpoints (`start_research_goal`, `get_research_goal`, `add_goal_evidence`,
  `update_research_goal_status`) and a Web `GoalDrawer`.
- **Swarm `retry_run`.** Re-launch a failed/stale/cancelled run with the
  original preset + variables; exposed as both `POST /swarm/runs/{id}/retry`
  and an MCP `retry_run` tool (the `list_runs → retry` loop). 36 MCP tools now.
- **Operator-configured external MCP tools in swarm workers** (#142) and
  **remote MCP transports** for the built-in agent.
- **`mootdx` A-share OHLCV loader** — native 通达信 TCP, no token, sits between
  tushare and akshare in the fallback chain. CCXT loader now reads proxy env
  for restricted networks (#126).
- **Hypothesis Registry CLI** — `list / show / invalidate`.
- **Strict alpha-bench mode** with a mandatory random control (#143).

### Changed
- **CLI split into the `agent/cli/` package** (from a 3216-LOC single file),
  with a refreshed interactive terminal UI (figlet banner + activity rail) and
  a single `cli/_version.py` version source.
- Swarm status reconciles from live task files on every read; `run_swarm`
  sends MCP progress heartbeats, and the stale-run reaper uses per-run
  thresholds (#132).
- Refreshed provider default model ids; bumped `langgraph` for CVE-2026-28277.

### Fixed
- **`--version` no longer drifts (#156).** The version derives from package
  metadata, falling back to reading `pyproject.toml` directly — no hardcoded
  constant left to forget on release.
- **Session running-status indicator** now survives reconnect / page reload /
  sidebar navigation; **swarm DAG** blocks downstream tasks when an upstream
  task fails (#145).
- **Robustness pass:** pre-flight validation for LLM-generated signal engines
  with clean JSON errors (#149), graceful agent-loop exit at the iteration
  budget instead of an output-less `failed` (#148), `flush + fsync` session
  message writes that skip corrupted JSONL lines on read (#147), and IME Enter
  handling in the Web composer (#146).
- **Full Report** link now always renders when a `runId` exists, even cross-browser
  (#150); SSE idle timeout is configurable via `VIBE_TRADING_SSE_TIMEOUT` (#157);
  cross-market correlation normalizes timestamps so crypto-vs-equity pairs align (#158).

## [0.1.8] — 2026-05-17

### Added — Alpha Zoo (450+ pre-built quant alphas)
- `agent/src/factors/` — base operators (`rank`, `scale`, `ts_*`, `delta`,
  `decay_linear`, `signed_power`, `safe_div`, market-aware `vwap`) and a
  registry that AST-extracts metadata from each alpha module without
  importing it. Lookahead is enforced at the operator level
  (`delta(d>=1)`), and registry sanity checks reject `+/-inf` and
  outputs that are more than 95 % NaN.
- 4 zoos shipping 452 alphas total:
  - **qlib158** (154 alphas) — port of Microsoft Qlib's `Alpha158`
    feature handler under Apache-2.0, with pinned commit SHA per file.
  - **alpha101** (101 alphas) — implementation of Kakushadze (2015)
    *"101 Formulaic Alphas"* (arXiv:1601.00991), written from the paper
    appendix; the relevant trademarked string is intentionally absent.
  - **gtja191** (191 alphas) — implementation of Guotai Junan's 2014
    *"191 Short-period Trading Alpha Factors"* research report.
  - **academic** (6 factors) — Fama-French 5 + Carhart momentum, shipped
    as honest price-based proxies (not the canonical FF series).
- `vibe-trading alpha {list,show,bench,compare,export-manifest}` CLI
  subcommand. `show` and `export-manifest` enforce path-traversal guards.
- New agent tools: `AlphaZooTool` (browse) and `AlphaBenchTool`
  (orchestrator with Jinja2 autoescape + strict CSP HTML report).
- `ZooSignalEngine.from_zoo(...)` — composite multi-factor signal engine
  with cross-sectional standardisation, weighting, and optional top-N /
  bottom-N long-short conversion.
- `wiki/scripts/build_alpha_library.py` — Alpha Library renderer.
  Reads `manifest.json` produced by `vibe-trading alpha export-manifest`
  and emits 452 per-alpha HTML pages plus 4 per-zoo overviews, each with
  `script-src 'none'` CSP. The landing page hydrates per-zoo counts
  from `content/index.json`.
- New blog post: *"Which of the 191 GTJA alphas still work in 2026?"*
  with aggregate IC statistics, theme breakdown, and the top alphas
  that survive eight years of out-of-sample data.

### Added — Web UI for Alpha Zoo
- New page at `/alpha-zoo` in the Vite + React frontend with three
  views: browse (4 zoo cards + filter bar + paginated table), detail
  (formula, metadata, collapsible source code), and bench-runner
  (form → SSE-streamed progress + Alive/Reversed/Dead stat cards +
  Top-5-by-IR table + by-theme breakdown chart). "Alpha Zoo" nav
  entry added to the layout.
- Four new REST routes in the FastAPI server:
  - `GET /alpha/list` — filterable alpha catalogue
  - `GET /alpha/{alpha_id}` — meta + source code
  - `POST /alpha/bench` — kicks off a background bench job and
    returns a `job_id`
  - `GET /alpha/bench/{job_id}/stream` — Server-Sent Events with
    `progress`, `result`, `done`, and `error` event types. In-memory
    job state with a 1-hour TTL; no Redis/Celery dependency.
- Bench math is refactored into `agent/src/factors/bench_runner.py`
  so the CLI driver (`agent/scripts/w4a_run_benches.py`) and the new
  API worker share a single implementation.

### Added — Safety floor
- `agent/tests/factors/test_alpha_purity.py` — AST allowlist scan over
  every `zoo/**/*.py` module (whitelist: pandas, numpy, scipy.\*,
  `src.factors.base`, `__future__`, `typing`, `math`, `dataclasses`;
  banned: `os`, `sys`, `subprocess`, `socket`, `urllib`, `requests`,
  `httpx`, `pathlib`, `Path`, `open`, `eval`, `exec`, `compile`,
  `__import__`, and `getattr(_, "__*")`).
- `agent/tests/factors/test_lookahead.py` — sentinel future-row
  injection on a 300-row synthetic panel; corrupting rows after the
  probe must leave the probe value unchanged within 1e-9.
- `tools/ci_grep_gates.sh` — CI gate that rejects `yaml.load(` without
  `safe_load`, any trademarked-name leak in shipped artifacts, and any
  per-stock-code data leak in `wiki/**/*.{json,csv,html}`.
- `agent/tests/factors/conftest.py` — opt-in `pytest-socket` integration
  that hard-fails any test attempting outbound network during the
  factors test suite.

### Added — Community governance
- `CONTRIBUTING.md` — Developer Certificate of Origin sign-off
  requirement and a contributor checklist for new alpha PRs (purity,
  lookahead, `__alpha_meta__` shape, LaTeX-matches-code, per-zoo
  LICENSE.md, DCO).
- `NOTICE` (repo root) — Apache-2.0 attribution for Qlib and a
  declaration that the bundled formulas from Kakushadze, GTJA, and the
  academic baselines are mathematical content (paper prose, tables, and
  figures are not reproduced here).
- Per-zoo `LICENSE.md` for each of `qlib158/`, `alpha101/`, `gtja191/`,
  and `academic/`, plus an upstream `NOTICE` for `qlib158/`.

### Changed
- `agent/src/tools/factor_analysis_tool.py` extracted its IC/IR and
  layered-backtest helpers to `agent/src/factors/factor_analysis_core.py`
  so the new `alpha_bench_tool` reuses the same maths. Public tool
  signature is unchanged; `_compute_ic_series` and `_compute_group_equity`
  remain importable as backward-compatible aliases.
- `agent/cli.py` grew by 7 lines to register the `alpha` subcommand;
  all handler logic lives in `agent/src/factors/cli_handlers.py`.
- Packaging: `pyproject.toml` now ships `zoo/**/*.yaml`, `zoo/**/*.md`,
  and `zoo/**/NOTICE` as package data; `MANIFEST.in` recursively
  includes `agent/src/factors`.

### Known limitations
- The `btc-usdt` universe is single-asset; cross-sectional IC requires
  ≥2 instruments, so the bundled `alpha101_btc` bench run returns
  alive/reversed/dead = 0/0/0 by construction. Use a multi-symbol crypto
  basket (e.g. BTC + ETH + SOL + the top-N perpetuals) for meaningful
  cross-sectional results; a curated `crypto-majors` universe is planned
  for 0.2.

### Internal
- `wiki/alpha-library/manifest.json` and `wiki/alpha-library/content/`
  are generated artifacts and gitignored. Run
  `vibe-trading alpha export-manifest --out wiki/alpha-library/manifest.json
  --force` followed by `python wiki/scripts/build_alpha_library.py` to
  regenerate the static site.
