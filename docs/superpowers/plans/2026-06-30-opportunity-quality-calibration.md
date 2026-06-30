# 今日机会质量校准 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每日机会快照增量计算 5/20/60 个交易日绝对收益与基准超额收益，并在总览展示可审计的质量统计。

**Architecture:** 在现有 opportunity-center 包中增加结果契约、SQLite 结果表和独立校准服务。校准服务按股票批量加载 OHLC，严格使用下一交易日开盘入场和目标交易日收盘结算；刷新任务尾部增量执行。FastAPI 提供聚合结果，React 以默认折叠区域展示前三名或全部机会的统计。

**Tech Stack:** Python 3.11+、Pydantic 2、SQLite、pandas、现有 YFinanceLoader、FastAPI、React 19、TypeScript、Vitest。

## Global Constraints

- 港股基准固定为 `^HSI`，美股基准固定为 `^GSPC`。
- 周期固定为 5、20、60 个交易日。
- 入场价使用信号日后下一交易日开盘价，结算价使用第 N 个交易日收盘价。
- 不使用更早价格代替缺失价格，不把最大亏损称为最大回撤。
- 第一版不自动修改机会评分权重，不接交易接口。
- 不修改当前未提交的模拟盘相关文件。

---

### Task 1: 校准契约与 SQLite 存储

**Files:**
- Modify: `agent/src/opportunity_center/models.py`
- Modify: `agent/src/opportunity_center/storage.py`
- Modify: `agent/tests/opportunity_center/test_models.py`
- Modify: `agent/tests/opportunity_center/test_storage.py`

**Interfaces:**
- Produces: `OutcomeStatus = Literal["pending", "completed", "missing"]`。
- Produces: `OpportunityOutcome`，字段包括市场、代码、快照日期、周期、排名、是否前三、入场/结算日期与价格、股票/基准/超额收益、状态、错误和 `calibration_version`。
- Produces: `CalibrationPeriodSummary` 与 `OpportunityCalibrationSummary`。
- Produces: `OpportunityStore.list_calibration_candidates()`、`upsert_outcome()`、`get_calibration_summary(scope)`。

- [ ] **Step 1: 写契约和存储失败测试**

测试分数范围、周期枚举、结果唯一键幂等、成功结果不被失败覆盖，以及 `top3`/`all` 聚合的样本数、胜率、跑赢率、平均收益、平均超额收益和最大亏损。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest agent/tests/opportunity_center/test_models.py agent/tests/opportunity_center/test_storage.py -q`

Expected: 新模型和存储方法不存在。

- [ ] **Step 3: 实现模型和迁移**

新增 `opportunity_outcomes` 表，唯一键为 `(market, code, snapshot_date, horizon_days, calibration_version)`；增加 `status`、排名、价格、收益、时间戳和错误列。聚合只统计 `status='completed'`，待验证数量单独返回。

- [ ] **Step 4: 验证 Task 1**

Run: `uv run pytest agent/tests/opportunity_center/test_models.py agent/tests/opportunity_center/test_storage.py -q`

Expected: PASS。

---

### Task 2: 无未来数据的增量校准计算

**Files:**
- Create: `agent/src/opportunity_center/calibration.py`
- Create: `agent/tests/opportunity_center/test_calibration.py`

**Interfaces:**
- Produces: `CALIBRATION_VERSION = "forward-return-v1"`。
- Produces: `compute_outcomes(frame, benchmark, snapshot_date, horizons, rank, top3) -> list[OpportunityOutcome]`。
- Produces: `OpportunityCalibrationService.refresh(as_of: date | None = None) -> int`。
- Consumes: 可注入 `price_loader(symbol, start_date, end_date) -> pd.DataFrame`，默认使用 `YFinanceLoader.fetch()`。

- [ ] **Step 1: 写计算失败测试**

用明确 OHLC 日期构造测试，验证信号日后第一交易日开盘入场、第 5/20/60 交易日收盘结算、股票与基准按相同日期对齐、未来行不会提前成熟、缺失开盘或基准价格返回 `missing`、重复刷新不重复加载已完成结果。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest agent/tests/opportunity_center/test_calibration.py -q`

Expected: `src.opportunity_center.calibration` 不存在。

- [ ] **Step 3: 实现纯计算与服务**

规范化索引为无时区交易日；定位 `snapshot_date` 之后的首行作为 entry 行，并以 entry 行为第 1 个交易日。只有 `len(rows) >= horizon` 才完成对应周期。服务按市场/代码批量加载，映射港股为 `NNNN.HK`、美股为裸 ticker，并加载 `^HSI`/`^GSPC`。

- [ ] **Step 4: 验证 Task 2**

Run: `uv run pytest agent/tests/opportunity_center/test_calibration.py -q`

Expected: PASS。

---

### Task 3: 刷新集成与 API

**Files:**
- Modify: `agent/src/opportunity_center/service.py`
- Modify: `agent/src/api/opportunity_routes.py`
- Modify: `agent/tests/opportunity_center/test_service_scheduler.py`
- Modify: `agent/tests/opportunity_center/test_routes.py`

**Interfaces:**
- Produces: `GET /opportunities/calibration?scope=top3|all`。
- Consumes: `OpportunityCalibrationService.refresh()` 和 `OpportunityStore.get_calibration_summary(scope)`。

- [ ] **Step 1: 写集成失败测试**

验证刷新任务完成快照后调用一次校准；校准异常只写入任务错误且不丢失机会快照；API 默认 `top3`，接受 `all`，拒绝非法 scope，并为静态路径保留正确路由优先级。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest agent/tests/opportunity_center/test_service_scheduler.py agent/tests/opportunity_center/test_routes.py -q`

Expected: 校准未调用且路由不存在。

- [ ] **Step 3: 实现集成**

通过构造参数向 `OpportunityService` 注入 calibration service；所有股票快照保存完成后使用 `asyncio.to_thread` 执行一次增量校准。新增静态 `/calibration` 路由并放在 `/{market}/{code}` 之前。

- [ ] **Step 4: 验证 Task 3**

Run: `uv run pytest agent/tests/opportunity_center/test_service_scheduler.py agent/tests/opportunity_center/test_routes.py -q`

Expected: PASS。

---

### Task 4: 总览机会质量界面

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/components/opportunities/OpportunityCalibration.tsx`
- Create: `frontend/src/components/opportunities/__tests__/OpportunityCalibration.test.tsx`
- Modify: `frontend/src/components/opportunities/TodayOpportunities.tsx`

**Interfaces:**
- Produces: `api.getOpportunityCalibration(scope)`。
- Produces: `<OpportunityCalibration />`，默认折叠并默认 `top3`。

- [ ] **Step 1: 写界面失败测试**

验证默认只显示“机会质量”标题；展开后显示 5/20/60 日、已验证样本数、胜率、跑赢率、平均收益、平均超额收益、最大亏损；切换“全部机会”重新请求；零成熟样本显示“样本积累中”。

- [ ] **Step 2: 运行测试确认失败**

Run: `npm --prefix frontend run test:run -- src/components/opportunities/__tests__/OpportunityCalibration.test.tsx`

Expected: 组件不存在。

- [ ] **Step 3: 实现界面**

使用 Chevron 图标按钮、`前三名/全部机会` 分段控制和三个紧凑指标行；不新增卡片嵌套。将组件放在今日机会列表与免责声明之间。

- [ ] **Step 4: 验证 Task 4**

Run: `npm --prefix frontend run test:run -- src/components/opportunities`

Expected: PASS。

---

### Task 5: 产品日志与最终验证

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 记录用户可见变化和固定收益口径**

在 Unreleased Added 中说明后台增量校准、5/20/60 日、绝对/超额收益及前三名/全部机会对比。

- [ ] **Step 2: 后端完整验证**

Run: `uv run --with ruff ruff check agent/src/opportunity_center agent/src/api/opportunity_routes.py agent/tests/opportunity_center`

Run: `uv run pytest agent/tests/opportunity_center agent/tests/test_hstech_best_strategy.py agent/tests/test_paper_trading_lookahead.py agent/tests/test_spa_deep_link.py -q`

Expected: 全部通过。

- [ ] **Step 3: 前端完整验证**

Run: `npm --prefix frontend run test:run -- src/components/opportunities src/components/layout/__tests__/Layout.test.tsx src/lib/__tests__/apiAuth.test.ts`

Run: `npm --prefix frontend run build`

Expected: 全部通过。

- [ ] **Step 4: 手工验收**

在桌面和 390px 手机视口验证折叠、scope 切换、样本积累状态、完整指标和无横向溢出；确认 API 重复调用不增加重复结果。
