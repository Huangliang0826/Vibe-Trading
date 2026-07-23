import type { Topic } from "./types";

export const TOPICS: Topic[] = [
  {
    id: "market",
    title: "市场与交易机制",
    subtitle: "撮合、流动性、成本——认清市场这台机器",
    status: "available",
  },
  {
    id: "technical",
    title: "技术分析与量价",
    subtitle: "趋势、量价关系,以及指标的真相与陷阱",
    status: "available",
  },
  {
    id: "quant",
    title: "策略与量化方法",
    subtitle: "因子、回测、过拟合——用科学方法炼金",
    status: "available",
  },
  {
    id: "risk",
    title: "风险管理与仓位",
    subtitle: "活得久,比赚得快重要",
    status: "available",
  },
  {
    id: "psychology",
    title: "交易心理与认知偏差",
    subtitle: "你最大的对手盘,是你自己",
    status: "available",
  },
];
