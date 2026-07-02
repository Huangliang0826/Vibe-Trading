import { useCallback, useEffect, useState } from "react";
import { ExternalLink, Loader2, Newspaper, RefreshCw, Search } from "lucide-react";
import { api, type NewsCenterArticle, type NewsCenterDigest, type NewsCenterList } from "@/lib/api";
import { cn } from "@/lib/utils";

const SECTOR_LABELS: Record<string, string> = {
  ai: "AI / 大模型", semi: "半导体", robot: "机器人", auto: "汽车 / 新能源车",
  energy: "能源", bio: "医药健康", space: "航天", security: "网络安全",
  tech: "科技互联网", consumer: "消费电子", macro: "财经宏观", science: "前沿科学",
};

export function NewsCenter() {
  const [language, setLanguage] = useState<"zh" | "en">("zh");
  const [dates, setDates] = useState<string[]>([]);
  const [date, setDate] = useState("");
  const [sector, setSector] = useState("");
  const [direction, setDirection] = useState("");
  const [query, setQuery] = useState("");
  const [watchlistOnly, setWatchlistOnly] = useState(false);
  const [data, setData] = useState<NewsCenterList | null>(null);
  const [digest, setDigest] = useState<NewsCenterDigest | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (selectedDate: string) => {
    if (!selectedDate) return;
    setLoading(true);
    setError(null);
    try {
      const [articles, daily] = await Promise.all([
        api.getNewsCenterArticles({
          date: selectedDate, sector: sector || undefined, direction: direction || undefined,
          query: query || undefined, watchlistOnly,
          language,
        }),
        api.getNewsCenterDigest(selectedDate, language),
      ]);
      setData(articles);
      setDigest(daily);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "新闻加载失败");
    } finally {
      setLoading(false);
    }
  }, [sector, direction, query, watchlistOnly, language]);

  useEffect(() => {
    api.getNewsCenterDates().then((items) => {
      setDates(items);
      setDate((current) => current || items[0] || new Date().toISOString().slice(0, 10));
    }).catch((reason) => setError(reason instanceof Error ? reason.message : "日期加载失败"));
  }, []);
  useEffect(() => { void load(date); }, [date, load]);

  const refresh = async () => {
    setRefreshing(true);
    setError(null);
    try {
      const result = await api.refreshNewsCenter();
      const nextDates = await api.getNewsCenterDates();
      setDates(nextDates);
      const nextDate = result.latest_date || nextDates[0] || date;
      setDate(nextDate);
      await load(nextDate);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "新闻刷新失败");
    } finally {
      setRefreshing(false);
    }
  };

  const sectors = data?.sectors ?? [];
  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <header className="flex flex-wrap items-start justify-between gap-4 border-b pb-5">
        <div className="flex items-center gap-3">
          <Newspaper className="h-6 w-6" />
          <div><h1 className="text-xl font-bold">新闻中心</h1><p className="text-xs text-muted-foreground">自选股、主要指数与重点行业</p></div>
        </div>
        <div className="flex items-center gap-2">
          <select aria-label="新闻日期" value={date} onChange={(event) => setDate(event.target.value)} className="h-9 rounded border bg-background px-3 text-xs">
            {dates.map((item) => <option key={item}>{item}</option>)}
          </select>
          <button aria-label="刷新新闻" onClick={() => void refresh()} disabled={refreshing} className="inline-flex h-9 items-center gap-2 rounded border px-3 text-xs disabled:opacity-50">
            {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}{refreshing ? "刷新中" : "刷新"}
          </button>
        </div>
      </header>

      {error && <p className="mt-4 rounded border border-red-500/30 bg-red-500/5 px-3 py-2 text-xs text-red-600">{error}</p>}

      <div role="tablist" aria-label="新闻语言" className="mt-5 inline-flex border-b">
        {([['zh', '中文新闻'], ['en', '英文新闻']] as const).map(([value, label]) => (
          <button
            key={value}
            role="tab"
            type="button"
            aria-selected={language === value}
            onClick={() => setLanguage(value)}
            className={cn(
              "h-9 border-b-2 px-4 text-sm font-medium",
              language === value ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <section className="border-b py-6">
        <div className="flex items-center justify-between"><h2 className="text-sm font-semibold">今日投资简报</h2><span className="text-xs text-muted-foreground">{digest?.article_count ?? 0} 条新闻</span></div>
        <p className="mt-3 max-w-3xl text-sm leading-7 text-foreground">{digest?.summary || (loading ? "正在整理今日新闻…" : "当日暂无已收录新闻。")}</p>
        {digest && <div className="mt-3 flex gap-4 text-xs text-muted-foreground"><span>自选股 {digest.watchlist_count}</span><span className="text-red-500">利好 {digest.positive_count}</span><span className="text-emerald-600">利空 {digest.negative_count}</span></div>}
      </section>

      {digest && digest.major_items.length > 0 && <section className="border-b py-6"><h2 className="mb-3 text-sm font-semibold">重大新闻</h2><div className="divide-y">{digest.major_items.map((item) => <NewsRow key={item.article_id} item={item} compact />)}</div></section>}

      <section className="py-6">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[220px] flex-1"><Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" /><input aria-label="搜索新闻" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索标题、摘要或来源" className="h-9 w-full rounded border bg-background pl-9 pr-3 text-xs" /></div>
          <select aria-label="行业筛选" value={sector} onChange={(event) => setSector(event.target.value)} className="h-9 rounded border bg-background px-3 text-xs"><option value="">全部行业</option>{sectors.map((item) => <option key={item} value={item}>{SECTOR_LABELS[item] || item}</option>)}</select>
          <select aria-label="影响筛选" value={direction} onChange={(event) => setDirection(event.target.value)} className="h-9 rounded border bg-background px-3 text-xs"><option value="">全部影响</option><option value="positive">利好</option><option value="neutral">中性</option><option value="negative">利空</option></select>
          <label className="inline-flex h-9 items-center gap-2 rounded border px-3 text-xs"><input type="checkbox" checked={watchlistOnly} onChange={(event) => setWatchlistOnly(event.target.checked)} />仅自选股</label>
        </div>
        <div className="mt-4 divide-y border-y">{loading ? <div className="py-12 text-center text-sm text-muted-foreground">加载中…</div> : data?.items.length ? data.items.map((item) => <NewsRow key={item.article_id} item={item} />) : <div className="py-12 text-center text-sm text-muted-foreground">没有符合条件的新闻</div>}</div>
      </section>
    </div>
  );
}

function NewsRow({ item, compact = false }: { item: NewsCenterArticle; compact?: boolean }) {
  const directions = new Set(item.matches.map((match) => match.direction).filter(Boolean));
  return <article className={cn("py-4", compact && "py-3")}><div className="flex items-start justify-between gap-4"><div className="min-w-0"><a href={item.url} target="_blank" rel="noreferrer" className="inline-flex items-start gap-1.5 text-sm font-medium hover:underline">{item.title}<ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0" /></a><div className="mt-1 flex flex-wrap gap-2 text-[11px] text-muted-foreground"><span>{item.source}</span><span>{item.published_at.slice(0, 16).replace("T", " ")}</span>{item.sector && <span>{SECTOR_LABELS[item.sector] || item.sector}</span>}{item.matches.map((match) => <span key={`${match.market}-${match.code}`} className="font-mono text-foreground">{match.code}</span>)}</div>{!compact && item.summary && <p className="mt-2 line-clamp-2 text-xs leading-5 text-muted-foreground">{item.summary}</p>}</div><div className="shrink-0 text-[11px]">{directions.has("positive") ? <span className="text-red-500">利好</span> : directions.has("negative") ? <span className="text-emerald-600">利空</span> : item.major ? <span className="text-amber-600">重要</span> : null}</div></div></article>;
}
