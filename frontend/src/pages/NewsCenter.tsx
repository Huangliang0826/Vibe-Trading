import { useCallback, useEffect, useRef, useState } from "react";
import { ExternalLink, Loader2, Newspaper, RefreshCw, Search, Sparkles } from "lucide-react";
import { api, type NewsCenterArticle, type NewsCenterDigest, type NewsCenterList } from "@/lib/api";
import { cn } from "@/lib/utils";

const NEWS_AUTO_REFRESH_KEY = "news-auto-refresh";

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
  const [autoRefreshing, setAutoRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  // One auto-generation attempt per date+language per mount; failures don't retry on filter changes.
  const aiAttempted = useRef(new Set<string>());
  const currentViewKey = useRef("");

  const generateAi = useCallback(async (selectedDate: string, lang: "zh" | "en", force = false) => {
    const key = `${selectedDate}:${lang}`;
    if (!force && aiAttempted.current.has(key)) return;
    aiAttempted.current.add(key);
    setAiLoading(true);
    setAiError(null);
    try {
      const result = await api.generateNewsAiDigest(selectedDate, lang, force);
      // Only apply if the user hasn't navigated to another day/language meanwhile.
      if (currentViewKey.current === key) setDigest(result);
    } catch (reason) {
      if (currentViewKey.current === key) setAiError(reason instanceof Error ? reason.message : "AI 总结生成失败");
    } finally {
      setAiLoading(false);
    }
  }, []);

  const load = useCallback(async (selectedDate: string) => {
    if (!selectedDate) return;
    setLoading(true);
    setError(null);
    currentViewKey.current = `${selectedDate}:${language}`;
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
      // 中文当天先生成本地快速摘要，再由后端在后台联网核实。
      // 历史日期只展示已经缓存的版本，避免用今天的搜索结果回填历史。
      const today = new Date().toISOString().slice(0, 10);
      if (language === "zh" && selectedDate === today && daily.ai_source !== "web") {
        void generateAi(selectedDate, language);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "新闻加载失败");
    } finally {
      setLoading(false);
    }
  }, [sector, direction, query, watchlistOnly, language, generateAi]);

  useEffect(() => {
    api.getNewsCenterDates().then((items) => {
      setDates(items);
      const today = new Date().toISOString().slice(0, 10);
      const latest = items[0] || "";
      // 每天首次打开且今天还没抓过新闻时,自动抓一次(每设备每天一次)
      const stale = latest < today;
      const marker = localStorage.getItem(NEWS_AUTO_REFRESH_KEY);
      if (stale && marker !== today) {
        localStorage.setItem(NEWS_AUTO_REFRESH_KEY, today);
        setAutoRefreshing(true);
        void refresh().finally(() => setAutoRefreshing(false));
        return;
      }
      setDate((current) => current || latest || today);
    }).catch((reason) => setError(reason instanceof Error ? reason.message : "日期加载失败"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { void load(date); }, [date, load]);

  useEffect(() => {
    if (!date || language !== "zh" || !digest?.ai_enriching) return;
    const key = `${date}:${language}`;
    const timer = window.setInterval(async () => {
      try {
        const next = await api.getNewsCenterDigest(date, language);
        if (currentViewKey.current === key) setDigest(next);
      } catch {
        // Keep the fast local digest visible if a background status poll fails.
      }
    }, 5000);
    return () => window.clearInterval(timer);
  }, [date, language, digest?.ai_enriching]);

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
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold">今日投资简报</h2>
            {digest?.ai_summary && (
              <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] text-primary"><Sparkles className="h-3 w-3" />{digest.ai_source === "web" ? "AI 联网总结" : "AI 快速总结"}</span>
            )}
            {digest?.ai_summary && !aiLoading && (
              <button aria-label="重新生成 AI 简报" title="重新生成" onClick={() => void generateAi(date, language, true)} className="text-muted-foreground hover:text-foreground"><RefreshCw className="h-3 w-3" /></button>
            )}
          </div>
          <span className="text-xs text-muted-foreground">{digest?.article_count ?? 0} 条新闻</span>
        </div>
        <p className="mt-3 max-w-3xl text-sm leading-7 text-foreground">
          {digest?.ai_summary
            || digest?.summary
            || (autoRefreshing ? "正在获取今日新闻…(每天首次打开自动更新)" : loading ? "正在整理今日新闻…" : "当日暂无已收录新闻。")}
        </p>
        {language === "zh" && aiLoading && <p className="mt-2 inline-flex items-center gap-1.5 text-xs text-muted-foreground"><Loader2 className="h-3 w-3 animate-spin" />AI 正在快速总结已收录新闻…</p>}
        {language === "zh" && !aiLoading && digest?.ai_enriching && <p className="mt-2 inline-flex items-center gap-1.5 text-xs text-muted-foreground"><Loader2 className="h-3 w-3 animate-spin" />快速摘要已完成，正在后台联网核实…</p>}
        {language === "zh" && aiError && !aiLoading && <p className="mt-2 text-xs text-amber-600">AI 总结暂不可用：{aiError}</p>}
        {digest && <div className="mt-3 flex gap-4 text-xs text-muted-foreground"><span>自选股 {digest.watchlist_count}</span><span className="text-red-500">利好 {digest.positive_count}</span><span className="text-emerald-600">利空 {digest.negative_count}</span></div>}
      </section>

      {digest && (digest.ai_major?.length ?? 0) > 0 ? (
        <section className="border-b py-6">
          <div className="mb-3 flex items-center gap-2"><h2 className="text-sm font-semibold">今日重大新闻</h2><span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] text-primary"><Sparkles className="h-3 w-3" />{digest.ai_source === "web" ? "AI 联网总结" : "AI 快速总结"}</span></div>
          <div className="divide-y">
            {digest.ai_major!.map((item, index) => (
              <article key={index} className="py-3">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="text-sm font-medium">{item.title}</p>
                    {item.summary && <p className="mt-1 text-xs leading-5 text-muted-foreground">{item.summary}</p>}
                  </div>
                  <div className="shrink-0 text-[11px]">
                    {item.impact === "positive" ? <span className="text-red-500">利好</span>
                      : item.impact === "negative" ? <span className="text-emerald-600">利空</span>
                      : <span className="text-muted-foreground">中性</span>}
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : digest && digest.major_items.length > 0 ? (
        <section className="border-b py-6"><h2 className="mb-3 text-sm font-semibold">今日重大新闻</h2><div className="divide-y">{digest.major_items.map((item) => <NewsRow key={item.article_id} item={item} compact />)}</div></section>
      ) : null}

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
  return <article className={cn("py-4", compact && "py-3")}><div className="flex items-start justify-between gap-4"><div className="min-w-0"><a href={item.url} target="_blank" rel="noreferrer" className="inline-flex items-start gap-1.5 text-sm font-normal hover:underline">{item.title}<ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0" /></a><div className="mt-1 flex flex-wrap gap-2 text-[11px] text-muted-foreground"><span>{item.source}</span><span>{item.published_at.slice(0, 16).replace("T", " ")}</span>{item.sector && <span>{SECTOR_LABELS[item.sector] || item.sector}</span>}{item.matches.map((match) => <span key={`${match.market}-${match.code}`} className="font-mono text-foreground">{match.code}</span>)}</div>{!compact && item.summary && <p className="mt-2 line-clamp-2 text-xs leading-5 text-muted-foreground">{item.summary}</p>}</div><div className="shrink-0 text-[11px]">{directions.has("positive") ? <span className="text-red-500">利好</span> : directions.has("negative") ? <span className="text-emerald-600">利空</span> : item.major ? <span className="text-amber-600">重要</span> : null}</div></div></article>;
}
