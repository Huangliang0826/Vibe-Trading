# 今日机会历史回填 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用当前自选股固定样本池回放过去两年月末机会，并写入现有质量校准统计。

**Architecture:** 新增可测试的回填服务和 CLI，批量加载每只股票历史行情后逐月调用现有无未来数据策略、市场上下文和评分函数。结果复用现有 SQLite 快照/结果表，并通过来源字段向 API 和前端披露幸存者偏差。

**Tech Stack:** Python、pandas、SQLite、Pydantic、React、Vitest。

## Global Constraints

- 不使用截面后的数据计算评分。
- 固定当前自选股回放必须明确标记幸存者偏差。
- 不覆盖或提交无关文件。

### Task 1: 来源契约与自选股历史

**Files:** `agent/src/opportunity_center/models.py`, `agent/src/opportunity_center/storage.py`, `agent/src/watchlist.py`, corresponding tests.

- [ ] 写失败测试：结果来源、汇总披露、自选股基线及变更快照。
- [ ] 实现 SQLite 兼容迁移和 `WatchlistStore.get_as_of()`。
- [ ] 运行模型、存储和自选股测试。

### Task 2: 固定样本回填引擎与 CLI

**Files:** create `agent/src/opportunity_center/backfill.py`, create tests.

- [ ] 写失败测试：月末日期、单次行情加载、无未来数据、幂等结果。
- [ ] 实现 `OpportunityBackfillService.run(years=2)` 和命令入口。
- [ ] 运行回填测试。

### Task 3: API 与前端披露

**Files:** opportunity models/storage, `frontend/src/lib/api.ts`, `OpportunityCalibration.tsx`, tests.

- [ ] 写失败测试：汇总返回回填标志，界面显示幸存者偏差。
- [ ] 实现响应字段和提示。
- [ ] 运行后端、前端测试和构建。

### Task 4: 实际回填与验收

- [ ] 运行两年回填命令。
- [ ] 检查结果表、汇总 API、桌面和手机界面。
- [ ] 更新 CHANGELOG，提交代码并保持服务器运行。
