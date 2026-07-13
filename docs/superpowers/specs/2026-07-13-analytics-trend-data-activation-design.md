# Analytics 趋势数据激活设计

## 目标

让现有数据洞察页面从“已具备展示能力”进入“启动后自动拥有可信趋势”的状态。系统应从本地已有研究产物中回填最多 90 天的质量观测，之后持续增量同步，并在每个视图中明确展示数据截至时间、覆盖率和缺失原因。

本阶段优先激活研究质量趋势，同时改善功能使用和系统健康聚合的新鲜度。所有处理保持本地、幂等、可关闭，并且不得阻塞 Scanner、Forecast、Backtest 或 Paper Trading 主流程。

## 已选择的方案

采用“来源适配器 + 幂等协调器”的方案：每个业务域只负责把已有权威产物映射为统一 `quality` 事件；`QualityBackfillCoordinator` 负责扫描、去重、记录来源状态和触发聚合。

不采用以下方案：

- 不用合成数据填满图表，因为它会让趋势失去决策价值。
- 不在 Analytics 中重新计算金融指标；收益、Sharpe、回撤和校准继续以现有业务模块为权威。
- 不为了补 Forecast 历史而批量调用外部模型或行情接口。没有持久化产物时明确显示 `source_unavailable`，从现在开始持续积累。

## 数据来源

### Scanner

读取 `~/.vibe-trading/tracking/<universe>/<date>/tracking.json`。按日期和成熟周期过滤记录，避免使用在当日尚不可知的前瞻收益。每个可用日期生成累计到该日的 1、5、10、20 日胜率、平均前瞻收益、分层 spread 和 rank IC。

### Forecast

继续读取已经产生的 Forecast calibration 质量事件。新的 calibration 结果仍由现有 hook 自动入库。本阶段不主动重新运行历史预测；当历史事件为空时返回可解释的来源状态，而不是伪造零值。

### Backtest

只读扫描 `agent/runs/*` 中成功运行的 `run_card.json`、`artifacts/metrics.csv` 和可选 equity 数据。事件日期使用运行完成时间或文件修改时间，指标直接采用持久化结果中的 total return、Sharpe、max loss、max drawdown、win rate 和 trade count。

### Paper Trading

通过 `PaperTradingStore.list_runs` 读取完成状态的运行。事件日期使用 `updated_at`，指标直接读取 `run.metrics`。新完成的运行在下一次增量同步时进入 Analytics。

## 模块边界

- `quality_sources.py`：定义来源报告、Scanner/Backtest/Paper Trading 只读来源以及异常隔离。
- `quality_adapters.py`：保留 Scanner/Forecast 适配，并增加 Backtest/Paper Trading 标量指标映射。
- `quality_backfill.py`：协调最多 90 天回填，生成稳定事件 ID，写入来源同步状态。
- `store.py`：新增来源状态表，保存最近尝试、最近成功、扫描数量、写入数量和机器可读原因。
- `runtime.py`：启动时执行一次回填，之后每小时先同步来源、再刷新日聚合。
- `service.py`：为 usage、system-health、research-quality 统一增加 `freshness` 和 `coverage` 响应字段。
- `ResearchQualityView.tsx` 与 Analytics 页面：展示数据截至时间、覆盖天数、最后同步时间和缺失原因。

来源之间不能相互依赖。单一来源文件损坏只影响自己的报告，并返回 `partial`；其他来源继续同步。

## 来源状态契约

每个来源保存并返回：

- `source`: `scanner`, `forecast`, `backtest`, `paper_trading`, `product_events` 或 `system_events`
- `status`: `available`, `partial`, `no_data`, `source_unavailable`, `error`
- `last_attempted_at`
- `last_success_at`
- `data_through`
- `records_scanned`
- `events_written`
- `coverage_days`
- `reason`

API 顶层增加：

- `freshness`: `fresh`, `stale`, `no_data`
- `coverage`: 请求窗口天数、拥有数据的日期数、覆盖率和来源报告

研究质量的 `status` 继续表达指标是否可用；`freshness` 表达数据是否新；两者不可混为一个字段。超过 48 小时未成功同步的本地来源标记为 `stale`，但历史值仍可展示并带警告。

## 幂等与时间语义

- 事件 ID 包含来源、原始记录 ID、指标、公式版本和观测日期，重复启动不会重复写入。
- 回填默认只扫描最近 90 天；长期保留已经写入的质量事件。
- Scanner 的 horizon 成熟规则沿用 tracking 模块的可用性时间垫，避免回看偏差。
- Backtest/Paper Trading 使用运行完成日期，不把回测样本结束日期伪装成系统当时已经知道结果的日期。
- 每次同步后补算最近 90 天日聚合；product/system 的常规小时任务仍只需要补算最近两天。

## 功能使用冷启动

历史功能使用无法从不存在的埋点中可靠恢复，因此不进行推断。改为确保：

1. Analytics Runtime 启动后立即 flush 当前队列并聚合当天数据。
2. 页面访问和核心旅程事件继续从现在开始记录。
3. 空状态显示“采集已启动时间”和当前覆盖天数，不再只是“暂无数据”。

## 错误处理

- 回填是 best-effort；异常只记录异常类型和来源，不记录业务载荷。
- 单个 run 或 tracking 文件解析失败时计入 `partial`，继续处理剩余文件。
- 数据库写入仍使用现有事务和 `INSERT OR IGNORE`。
- Analytics 被禁用时不启动回填，也不改变任何业务响应。
- 来源为空与来源不可访问必须区分，前端给出不同提示。

## 测试

### 后端

- Scanner 回填只使用在观测日已成熟的 horizon 数据。
- Backtest/Paper Trading 适配器读取现有指标且不重新计算。
- 重复回填写入数为零，事件数不增长。
- 单个损坏文件产生 `partial`，有效文件仍入库。
- 来源状态表迁移、更新和查询正确。
- Runtime 启动回填失败不阻塞 collector 与 API。
- API 正确报告覆盖率、fresh/stale/no-data 和机器可读原因。

### 前端

- available、partial、stale、no-data 四种状态均有明确文案。
- 展示覆盖天数、数据截至时间、样本量和公式版本。
- 不可用值不显示为零。
- 7、30、90 天切换会同步更新覆盖率。

## 验收标准

1. 启动后无需打开各业务页面，已有 Scanner、Backtest 和 Paper Trading 本地产物会在一次同步内进入研究质量趋势。
2. Forecast 没有历史持久化产物时明确显示来源限制；新 calibration 会持续积累。
3. 重启或重复同步不会产生重复观测。
4. 每个研究 Tab 都能解释“数据到哪一天、覆盖多少天、为什么缺失”。
5. 单个来源损坏不影响其他来源，也不影响核心业务启动。
6. 针对性测试、后端完整测试、前端完整测试和生产构建全部通过。

