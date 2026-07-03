import type { PaperHolding, PaperStrategyConfig, PaperTradingCreate } from "./api";

type RobustWinnerRunInput = {
  bestStrategy: PaperStrategyConfig["name"] | null;
  winnerParams: Record<string, unknown>;
  holdings: PaperHolding[];
  startDate: string;
  endDate: string;
  initialUsd: number;
  initialHkd: number;
};

export function buildRobustWinnerRunRequest(input: RobustWinnerRunInput): PaperTradingCreate {
  if (!input.bestStrategy) throw new Error("No robust winner available");
  return {
    title: `多时间段最稳健 - ${input.bestStrategy}`,
    holdings: input.holdings,
    strategy: { name: input.bestStrategy, params: input.winnerParams },
    start_date: input.startDate,
    end_date: input.endDate,
    initial_usd: input.initialUsd,
    initial_hkd: input.initialHkd,
  };
}
