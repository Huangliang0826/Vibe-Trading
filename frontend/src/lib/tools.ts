/**
 * Single source of truth for tool name → user-facing label.
 */
export const TOOL_LABELS: Record<string, string> = {
  load_skill: "加载策略知识",
  write_file: "生成代码",
  edit_file: "编辑代码",
  read_file: "读取文件",
  run_backtest: "运行回测",
  bash: "执行命令",
  read_url: "读取网页",
  read_document: "读取文档",
  trading_connections: "列出交易连接器",
  trading_select_connection: "选择交易连接器",
  trading_check: "检查交易连接器",
  trading_account: "读取账户信息",
  trading_positions: "读取持仓信息",
  trading_orders: "读取订单信息",
  trading_quote: "读取行情数据",
  trading_history: "读取历史数据",
  compact: "压缩对话",
  create_task: "创建任务",
  update_task: "更新任务",
  spawn_subagent: "启动子智能体",
};

export function localizeToolName(tool: string, fallback?: string): string {
  if (tool in TOOL_LABELS) {
    return TOOL_LABELS[tool];
  }
  if (fallback !== undefined) {
    return fallback;
  }
  return tool;
}
