# 机会扫描多市场 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为机会扫描增加美股、A 股和恒生科技三个独立股票池，并保证同日结果和跟踪数据互不覆盖。

**Architecture:** 存储路径以 `universe` 为一级目录，读取接口显式接收股票池并兼容旧目录。前端用市场分段控件驱动当前股票池的日期、历史、跟踪、校准和刷新请求。

**Tech Stack:** FastAPI、Python pathlib/JSON、React、TypeScript、Vitest、pytest。

## Global Constraints

- 固定映射：美股 `sp500`、A 股 `csi300`、港股 `hstech`。
- 更新只扫描当前市场，返回前 20 名。
- 保留旧扫描和旧跟踪文件，不删除用户数据。
- A 股配置错误必须以可读错误显示。

---

### Task 1: 按股票池隔离扫描存储

**Files:**
- Modify: `agent/src/scanner/store.py`
- Test: `agent/tests/scanner/test_store.py`

**Interfaces:**
- Produces: `save_scan(result)`, `list_scan_dates(universe)`, `load_by_date(asof, universe)`, `load_latest(universe)`。

- [ ] 写失败测试：同日 `sp500/csi300/hstech` 保存后分别读取；旧 `{asof}/run.json` 仍可按文件内股票池读取。
- [ ] 运行 `uv run pytest agent/tests/scanner/test_store.py -q`，确认测试因现有路径覆盖而失败。
- [ ] 将新文件写入 `{root}/{universe}/{asof}/run.json`，读取时合并新目录与匹配股票池的旧目录。
- [ ] 重跑测试确认通过。
- [ ] 提交 `feat: isolate scanner history by universe`。

### Task 2: 按股票池隔离跟踪与校准

**Files:**
- Modify: `agent/src/scanner/tracking.py`
- Test: `agent/tests/scanner/test_tracking.py`

**Interfaces:**
- Produces: `save_tracking(..., universe)`, `load_tracking(asof, universe)`, `load_all_tracking(universe)`。

- [ ] 写失败测试：同日不同股票池跟踪记录可并存且校准读取互不混合。
- [ ] 运行跟踪测试确认失败。
- [ ] 增加 `universe` 参数和分目录；`sp500` 读取时兼容旧跟踪目录。
- [ ] 重跑测试确认通过。
- [ ] 提交 `feat: isolate scanner tracking by universe`。

### Task 3: 扩展多市场扫描 API

**Files:**
- Modify: `agent/src/api/scan_routes.py`
- Test: `agent/tests/scanner/test_scan_routes.py`

**Interfaces:**
- Consumes: Task 1/2 的 universe-aware 存储函数。
- Produces: `/scan/dates?universe=...`、`/scan/latest?universe=...`、`/scan/history/{asof}?universe=...`、跟踪与校准同类参数。

- [ ] 写失败测试：每个读取接口透传股票池；非法股票池返回 400。
- [ ] 运行路由测试确认失败。
- [ ] 增加 `Literal["sp500", "csi300", "hstech"]` 参数并透传存储层。
- [ ] 重跑路由测试确认通过。
- [ ] 提交 `feat: expose scanner market universes`。

### Task 4: 前端市场切换

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/pages/Scanner.tsx`
- Test: `frontend/src/pages/__tests__/Scanner.test.tsx`

**Interfaces:**
- Consumes: Task 3 的 universe 查询参数。
- Produces: `美股/A股/港股` 分段控件及当前市场独立刷新流程。

- [ ] 写失败测试：切换 A 股请求 `csi300`，切换港股请求 `hstech`，更新只运行当前股票池。
- [ ] 运行 Scanner 测试确认失败。
- [ ] 为 API 方法增加 universe 参数；Scanner 状态以当前市场重载日期、最新、历史、跟踪和校准。
- [ ] 重跑 Scanner 测试确认通过。
- [ ] 提交 `feat: add scanner market selector`。

### Task 5: 集成验证

**Files:**
- Modify: `CHANGELOG.md`

- [ ] 运行 `uv run pytest agent/tests/scanner -q`。
- [ ] 运行 `npm --prefix frontend run test:run -- src/pages/__tests__/Scanner.test.tsx`。
- [ ] 运行 `npm --prefix frontend run build` 和 `git diff --check`。
- [ ] 在本地页面确认三个市场控件、空状态和更新状态可见。
- [ ] 更新产品日志并提交 `docs: record multi-market opportunity scanner`。
