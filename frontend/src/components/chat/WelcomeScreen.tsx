import { Bot, TrendingUp, Globe, Sparkles, Users, UserCircle2, NotebookPen, Landmark } from "lucide-react";

interface Example {
  title: string;
  desc: string;
  prompt: string;
}

interface Category {
  label: string;
  icon: React.ReactNode;
  color: string;
  examples: Example[];
}

const CATEGORIES: Category[] = [
  {
    label: "多市场回测",
    icon: <TrendingUp className="h-4 w-4" />,
    color: "text-red-400 border-red-500/30 hover:border-red-500/60 hover:bg-red-500/5",
    examples: [
      {
        title: "跨市场组合",
        desc: "A 股 + 加密货币 + 美股，风险平价优化",
        prompt: "Backtest a risk-parity portfolio of 000001.SZ, BTC-USDT, and AAPL for full-year 2024, compare against equal-weight baseline",
      },
      {
        title: "BTC 5 分钟 MACD 策略",
        desc: "分钟级加密货币回测，使用实时 OKX 数据",
        prompt: "Backtest BTC-USDT 5-minute MACD strategy, fast=12 slow=26 signal=9, last 30 days",
      },
      {
        title: "美股科技最大分散化",
        desc: "通过 yfinance 对 FAANG+ 进行组合优化",
        prompt: "Backtest AAPL, MSFT, GOOGL, AMZN, NVDA with max_diversification portfolio optimizer, full-year 2024",
      },
    ],
  },
  {
    label: "研究与分析",
    icon: <Sparkles className="h-4 w-4" />,
    color: "text-amber-400 border-amber-500/30 hover:border-amber-500/60 hover:bg-amber-500/5",
    examples: [
      {
        title: "多因子 Alpha 模型",
        desc: "IC 加权因子合成，覆盖 300 只股票",
        prompt: "Build a multi-factor alpha model using momentum, reversal, volatility, and turnover on CSI 300 constituents with IC-weighted factor synthesis, backtest 2023-2024",
      },
      {
        title: "期权希腊字母分析",
        desc: "Black-Scholes 定价，含 Delta/Gamma/Theta/Vega",
        prompt: "Calculate option Greeks using Black-Scholes: spot=100, strike=105, risk-free rate=3%, vol=25%, expiry=90 days, analyze Delta/Gamma/Theta/Vega",
      },
    ],
  },
  {
    label: "智能体集群",
    icon: <Users className="h-4 w-4" />,
    color: "text-violet-400 border-violet-500/30 hover:border-violet-500/60 hover:bg-violet-500/5",
    examples: [
      {
        title: "投资委员会评审",
        desc: "多智能体辩论：多空对决、风控审核、基金经理决策",
        prompt: "[Swarm Team Mode] Use the investment_committee preset to evaluate whether to go long or short on NVDA given current market conditions",
      },
      {
        title: "量化策略组",
        desc: "筛选 → 因子研究 → 回测 → 风险审计流水线",
        prompt: "[Swarm Team Mode] Use the quant_strategy_desk preset to find and backtest the best momentum strategy on CSI 300 constituents",
      },
    ],
  },
  {
    label: "文档与网络研究",
    icon: <Globe className="h-4 w-4" />,
    color: "text-blue-400 border-blue-500/30 hover:border-blue-500/60 hover:bg-blue-500/5",
    examples: [
      {
        title: "分析财报 PDF",
        desc: "上传 PDF，提问财务数据相关问题",
        prompt: "Summarize the key financial metrics, risks, and outlook from the uploaded earnings report",
      },
      {
        title: "网络研究：宏观展望",
        desc: "读取实时网络来源进行宏观分析",
        prompt: "Read the latest Fed meeting minutes and summarize the key takeaways for equity and crypto markets",
      },
    ],
  },
  {
    label: "交易日志",
    icon: <NotebookPen className="h-4 w-4" />,
    color: "text-orange-400 border-orange-500/30 hover:border-orange-500/60 hover:bg-orange-500/5",
    examples: [
      {
        title: "分析经纪商导出数据",
        desc: "解析同花顺/东财/富途/通用 CSV——持仓天数、胜率、盈亏比、时段分布",
        prompt: "Analyze the trade journal I just uploaded — full profile with holding stats, win rate, top symbols, and hourly distribution",
      },
      {
        title: "诊断行为偏差",
        desc: "处置效应、过度交易、追涨、锚定——量化偏差程度",
        prompt: "Run the 4 behavior diagnostics on my trade journal (disposition, overtrading, chasing, anchoring) and tell me which bias hurts my PnL most",
      },
    ],
  },
  {
    label: "交易连接器",
    icon: <Landmark className="h-4 w-4" />,
    color: "text-cyan-400 border-cyan-500/30 hover:border-cyan-500/60 hover:bg-cyan-500/5",
    examples: [
      {
        title: "检查选定连接器",
        desc: "列出连接器配置并验证当前选定的连接器",
        prompt: "List my trading connector profiles, show which one is selected, then check that selected connector. If it is not ready, tell me exactly what setup step is missing. Do not place or modify orders.",
      },
      {
        title: "分析连接器持仓",
        desc: "从选定连接器读取账户概要与持仓",
        prompt: "Use the selected trading connector profile to summarize my account, positions, concentration, cash, and portfolio risk. Do not place or modify orders.",
      },
      {
        title: "行情与趋势",
        desc: "通过选定连接器获取行情及近期日线数据",
        prompt: "Use the selected trading connector to fetch an AAPL quote and 30 daily bars, then summarize the current quote versus the recent trend. Keep it read-only.",
      },
    ],
  },
  {
    label: "影子账户",
    icon: <UserCircle2 className="h-4 w-4" />,
    color: "text-emerald-400 border-emerald-500/30 hover:border-emerald-500/60 hover:bg-emerald-500/5",
    examples: [
      {
        title: "从日志训练影子账户",
        desc: "从经纪商 CSV 中提取策略规则并持久化影子账户",
        prompt: "Train my shadow account from the trading journal I just uploaded — show the extracted rules and confirm they look like my behavior",
      },
      {
        title: "我损失了多少潜在收益？",
        desc: "回测影子策略，归因与实际 PnL 的差距",
        prompt: "Run a shadow backtest for the last 90 days on the US market and break down where my PnL diverged from the shadow (rule violations, early exits, missed signals)",
      },
      {
        title: "生成影子账户报告",
        desc: "8 节 HTML/PDF——权益曲线、各市场夏普比率、归因瀑布图",
        prompt: "Render the shadow report and give me the URL — lead with the you-vs-shadow delta",
      },
    ],
  },
];

const CAPABILITY_CHIPS = [
  "金融技能库",
  "智能体集群",
  "自动发现工具",
  "三大市场：A股 · 加密货币 · 港美股",
  "交易连接器配置",
  "分钟到日线级别",
  "4 种组合优化器",
  "15+ 风险指标",
  "期权与衍生品",
  "PDF 与网络研究",
  "因子分析与机器学习",
  "交易日志分析",
  "影子账户回测",
  "持久化记忆",
  "会话搜索",
];

interface Props {
  onExample: (s: string) => void;
}

export function WelcomeScreen({ onExample }: Props) {
  return (
    <div className="flex min-h-[62vh] flex-col items-center justify-center space-y-9 py-6 text-center">
      {/* Header */}
      <div className="space-y-4">
        <div className="mx-auto flex h-16 w-16 -rotate-2 items-center justify-center rounded-[22px_22px_22px_8px] bg-primary text-primary-foreground shadow-[0_14px_32px_hsl(var(--primary)/0.2)]">
          <Bot className="h-8 w-8" strokeWidth={1.8} />
        </div>
        <div>
          <p className="page-kicker">AI research workspace</p>
          <h2 className="mt-2 text-[32px] font-semibold tracking-[-0.04em] text-foreground">今天想研究什么？</h2>
          <p className="brand-wordmark mt-2 text-xs">Alpha Mind</p>
          <p className="mx-auto mt-3 max-w-md text-sm leading-6 text-muted-foreground">
            <span className="block">描述一个交易策略即可开始。</span>
            <span className="block">也可以提出研究问题或上传文档。</span>
          </p>
        </div>
      </div>

      {/* Capability chips */}
      <div className="flex max-w-2xl flex-wrap justify-center gap-2">
        {CAPABILITY_CHIPS.map((chip) => (
          <span
            key={chip}
            className="rounded-full border border-border/70 bg-card/65 px-2.5 py-1 text-xs text-muted-foreground"
          >
            {chip}
          </span>
        ))}
      </div>

      {/* Example categories grid */}
      <div className="w-full max-w-3xl space-y-4 text-left">
        <p className="overview-section-title px-1">试试以下示例：</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {CATEGORIES.map((cat) => (
            <div key={cat.label} className="space-y-2">
              <div className={`flex items-center gap-1.5 text-xs font-medium px-1 ${cat.color.split(" ").filter(c => c.startsWith("text-")).join(" ")}`}>
                {cat.icon}
                <span>{cat.label}</span>
              </div>
              <div className="space-y-1.5">
                {cat.examples.map((ex) => (
                  <button
                    key={ex.title}
                    onClick={() => onExample(ex.prompt)}
                    className={`block w-full rounded-2xl border bg-card/70 px-3.5 py-3 text-left shadow-[0_8px_24px_rgba(32,57,58,0.035)] transition-[border-color,background-color,box-shadow] hover:shadow-[0_12px_30px_rgba(32,57,58,0.07)] ${cat.color}`}
                  >
                    <span className="text-sm font-medium text-foreground leading-snug">
                      {ex.title}
                    </span>
                    <span className="block text-xs text-muted-foreground mt-0.5 leading-snug">
                      {ex.desc}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
