import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp, ExternalLink, Loader2, RefreshCw, X } from "lucide-react";
import { api, type HistoricalEvent, type HistoricalEventPeriod, type PriceHistoryBar } from "@/lib/api";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useDarkMode } from "@/hooks/useDarkMode";
import { cn } from "@/lib/utils";

const PERIODS: HistoricalEventPeriod[] = ["1Y", "3Y", "5Y", "ALL"];

interface Props {
  market: "hk" | "us";
  code: string;
  companyName: string;
  period: HistoricalEventPeriod;
  bars: PriceHistoryBar[];
  onPeriodChange: (period: HistoricalEventPeriod) => void;
}

export function HistoricalEventsView({ market, code, companyName, period, bars, onPeriodChange }: Props) {
  const chartRef = useRef<HTMLDivElement>(null);
  const [events, setEvents] = useState<HistoricalEvent[]>([]);
  const [selected, setSelected] = useState<HistoricalEvent | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [cached, setCached] = useState(false);
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState("等待开始");
  const [error, setError] = useState<string | null>(null);
  const { dark } = useDarkMode();

  const load = useCallback(async (force = false) => {
    setLoading(true);
    setError(null);
    setSelected(null);
    try {
      let run = await api.startHistoricalEventRun(market, code, companyName, period, force);
      setCached(run.cached);
      setProgress(run.progress);
      setStage(run.stage);
      while (run.status === "pending" || run.status === "running") {
        await new Promise((resolve) => window.setTimeout(resolve, 800));
        run = await api.getHistoricalEventRun(run.run_id);
        setProgress(run.progress);
        setStage(run.stage);
      }
      if (run.status === "failed") throw new Error(run.error || "重大历史事件分析失败");
      setEvents(await api.getHistoricalEvents(market, code, period));
    } catch (value) {
      setEvents([]);
      setError(value instanceof Error ? value.message : "重大历史事件分析失败");
    } finally {
      setLoading(false);
    }
  }, [market, code, companyName, period]);

  useEffect(() => { void load(false); }, [load]);

  useEffect(() => {
    if (!chartRef.current || bars.length < 2) return;
    const theme = getChartTheme();
    const chart = echarts.init(chartRef.current);
    const dates = bars.map((bar) => bar.date.slice(0, 10));
    const nearestDate = (target: string) => dates.find((date) => date >= target) || dates[dates.length - 1];
    const closeByDate = new Map(bars.map((bar) => [bar.date.slice(0, 10), bar.close]));
    const markers = events.map((event) => {
      const date = nearestDate(event.end_date);
      return {
        name: event.event_id, eventId: event.event_id,
        coord: [date, closeByDate.get(date)],
        value: `${event.return_pct > 0 ? "+" : ""}${event.return_pct.toFixed(1)}%`,
        symbol: "triangle", symbolRotate: event.direction === "down" ? 180 : 0,
        itemStyle: { color: event.direction === "up" ? theme.upColor : theme.downColor },
      };
    });
    chart.setOption({
      animation: false,
      grid: { left: 52, right: 12, top: 24, bottom: 32 },
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: dates, axisLabel: { color: theme.textColor, hideOverlap: true }, axisLine: { lineStyle: { color: theme.axisColor } } },
      yAxis: { type: "value", scale: true, axisLabel: { color: theme.textColor }, splitLine: { lineStyle: { color: theme.gridColor } } },
      series: [{
        type: "line", data: bars.map((bar) => bar.close), showSymbol: false,
        lineStyle: { width: 1.5, color: theme.textColor },
        markPoint: { symbolSize: 34, label: { color: theme.textColor, fontSize: 10, position: "top" }, data: markers },
        markArea: { silent: true, itemStyle: { color: "rgba(148, 163, 184, 0.14)" }, data: events.map((event) => [{ xAxis: nearestDate(event.start_date) }, { xAxis: nearestDate(event.end_date) }]) },
      }],
    });
    chart.on("click", (params) => {
      const data = params.data as { eventId?: string } | null | undefined;
      if (params.componentType !== "markPoint" || !data?.eventId) return;
      setSelected(events.find((event) => event.event_id === data.eventId) || null);
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [bars, events, dark]);

  const upCount = events.filter((event) => event.direction === "up").length;
  const downCount = events.length - upCount;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
          <span>{events.length} 次重大波动</span><span>{upCount} 次大涨</span><span>{downCount} 次大跌</span>
          {cached && <span className="font-medium text-foreground">本地缓存</span>}
        </div>
        <div className="flex items-center gap-1">
          {PERIODS.map((value) => <button key={value} type="button" onClick={() => onPeriodChange(value)} className={cn("h-7 px-2 text-xs", value === period ? "font-semibold text-foreground" : "text-muted-foreground")}>{value}</button>)}
          <button type="button" aria-label="重新分析重大历史事件" title="重新分析" onClick={() => void load(true)} disabled={loading} className="flex h-7 w-7 items-center justify-center rounded-md hover:bg-muted disabled:opacity-50"><RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} /></button>
        </div>
      </div>

      {loading && <div className="flex h-[260px] flex-col items-center justify-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-5 w-5 animate-spin" /><span>{stage} · {progress}%</span></div>}
      {!loading && error && <div className="flex h-[180px] items-center justify-center text-xs text-red-500">{error}</div>}
      {!loading && !error && bars.length < 2 && <div className="flex h-[180px] items-center justify-center text-xs text-muted-foreground">暂无价格数据</div>}
      {!loading && !error && bars.length >= 2 && (
        <div className="relative">
          <div ref={chartRef} style={{ height: 260 }} />
          {selected && <EventSummary event={selected} onClose={() => setSelected(null)} onExpand={() => setExpandedId(selected.event_id)} />}
        </div>
      )}

      {!loading && !error && events.length === 0 && bars.length >= 2 && <p className="text-xs text-muted-foreground">当前区间没有达到阈值的重大波动。</p>}
      {events.length > 0 && <div className="divide-y border-t">{events.map((event) => {
        const expanded = expandedId === event.event_id;
        return <div key={event.event_id} className="py-2">
          <button type="button" aria-label={`打开${event.start_date}重大事件`} onClick={() => { setSelected(event); setExpandedId(expanded ? null : event.event_id); }} className="flex w-full items-center justify-between gap-3 text-left text-xs">
            <span><strong className={event.direction === "up" ? "text-red-500" : "text-emerald-600"}>{event.return_pct > 0 ? "+" : ""}{event.return_pct.toFixed(1)}%</strong><span className="ml-2 text-muted-foreground">{event.start_date} 至 {event.end_date} · {event.driver_type}</span></span>
            {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>
          {expanded && <FullReport event={event} />}
        </div>;
      })}</div>}
    </div>
  );
}

function EventSummary({ event, onClose, onExpand }: { event: HistoricalEvent; onClose: () => void; onExpand: () => void }) {
  return <div className="absolute right-2 top-2 z-10 w-[min(360px,calc(100%-16px))] border bg-background p-3 shadow-lg">
    <div className="flex items-start justify-between gap-2"><div><p className="text-xs font-semibold">{event.start_date} 至 {event.end_date} · {event.return_pct > 0 ? "+" : ""}{event.return_pct.toFixed(1)}%</p><p className="mt-0.5 text-[11px] text-muted-foreground">{event.driver_type} · 置信度{event.confidence} · {event.market_context}</p></div><button type="button" aria-label="关闭事件摘要" onClick={onClose}><X className="h-4 w-4" /></button></div>
    <p className="mt-2 text-xs font-medium">{event.primary_driver}</p>
    {event.benchmark_return_pct != null && <p className="mt-1 text-[11px] text-muted-foreground">同期基准 {event.benchmark_return_pct > 0 ? "+" : ""}{event.benchmark_return_pct.toFixed(1)}%</p>}
    <EvidenceLinks event={event} limit={3} />
    <button type="button" onClick={onExpand} className="mt-2 text-xs font-medium underline">查看完整分析</button>
  </div>;
}

function EvidenceLinks({ event, limit }: { event: HistoricalEvent; limit?: number }) {
  if (!event.evidence.length) return <p className="mt-2 text-[11px] text-muted-foreground">未找到足够可靠的同期证据。</p>;
  return <ul className="mt-2 space-y-1">{event.evidence.slice(0, limit).map((item) => <li key={item.url}><a href={item.url} target="_blank" rel="noreferrer" className="flex items-start gap-1 text-[11px] text-foreground hover:underline">{item.title}<ExternalLink className="mt-0.5 h-3 w-3 shrink-0" /></a></li>)}</ul>;
}

function FullReport({ event }: { event: HistoricalEvent }) {
  return <div className="mt-2 border-l-2 border-foreground/20 pl-3 text-xs"><p className="font-medium">{event.primary_driver}</p><p className="mt-1 leading-5 text-muted-foreground">{event.narrative}</p><p className="mt-1 text-muted-foreground">股票 {event.return_pct > 0 ? "+" : ""}{event.return_pct.toFixed(1)}% · 基准 {event.benchmark_return_pct == null ? "—" : `${event.benchmark_return_pct > 0 ? "+" : ""}${event.benchmark_return_pct.toFixed(1)}%`} · {event.market_context}</p><EvidenceLinks event={event} /><p className="mt-2 text-[11px] text-muted-foreground">{event.causality_note}</p></div>;
}
