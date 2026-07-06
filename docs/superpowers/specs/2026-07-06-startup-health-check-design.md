# 启动与健康检查设计

## 目标与范围

让本地环境可靠启动、诊断并解释前后端连接故障。保持前端 `5899`、后端 `8899`，不修改行情、图表、策略、缓存或交易逻辑。

## 设计

- `scripts/dev up` 清理失效 PID，拒绝被非健康进程占用的固定端口，并在启动后验证后端、前端和前端代理 `/health`。
- 新增 `scripts/dev doctor`，以 `PASS/FAIL` 检查依赖、进程、端口、后端健康、前端页面和代理健康；失败时返回非零状态并指出日志。
- Vite 明确代理 `/health`。
- 新增 `useApiHealth`：首次加载、每 15 秒、窗口聚焦及网络恢复时检查；只接受 2xx JSON 且 `status === "healthy"`。
- `ConnectionBanner` 优先显示 API 故障和重试按钮，聊天 SSE 故障保持原行为。
- 业务 API 收到 HTML 时不展示 HTML，提示运行 `scripts/dev doctor`。

## 验收与回退

pytest 覆盖 doctor 和失效 PID；Vitest 覆盖健康检查、HTML、网络错误、重试和横幅优先级。生产构建必须通过。真实环境中 `8899/health` 与 `5899/health` 均返回健康 JSON，后端停止后横幅出现，恢复后消失。全部改动集中于启动脚本、Vite 代理和独立健康组件，可由单个分支回退。
