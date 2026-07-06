export type ScanUniverse = "sp500" | "hstech";

const MARKET_TIMEZONE: Record<ScanUniverse, string> = {
  sp500: "America/New_York",
  hstech: "Asia/Hong_Kong",
};

// 16:30 当地时间:两个市场都是 16:00 收盘,留 30 分钟给行情数据落地
const CLOSE_WITH_BUFFER_MINUTES = 16 * 60 + 30;

const DAY_MS = 86_400_000;

/** 该市场最近一个已收盘的交易日 (YYYY-MM-DD),不含节假日历,只按周末推算。 */
export function lastClosedTradingDay(universe: ScanUniverse, now: Date = new Date()): string {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: MARKET_TIMEZONE[universe],
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(now)
      .map((p) => [p.type, p.value]),
  );
  // 用市场当地日历日的正午 UTC 做日期运算,避免时区/夏令时边界问题
  let day = new Date(Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day), 12));
  if (Number(parts.hour) * 60 + Number(parts.minute) < CLOSE_WITH_BUFFER_MINUTES) {
    day = new Date(day.getTime() - DAY_MS);
  }
  while (day.getUTCDay() === 0 || day.getUTCDay() === 6) {
    day = new Date(day.getTime() - DAY_MS);
  }
  return day.toISOString().slice(0, 10);
}
