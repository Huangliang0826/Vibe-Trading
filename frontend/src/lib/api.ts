import { authHeaders, withAuthQuery } from "@/lib/apiAuth";

const BASE = "";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export const AUTH_REQUIRED_MESSAGE =
  "Remote API access requires an API key. Add it in Settings, or run the backend on localhost for local-only use.";

export function isAuthRequiredError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

async function errorFromResponse(res: Response): Promise<ApiError> {
  let detail = `HTTP ${res.status}`;
  try {
    const body = await res.json();
    detail = formatApiErrorDetail(body.detail || body.message || detail);
  } catch { /* ignore */ }
  if (res.status === 401 || res.status === 403) {
    detail = AUTH_REQUIRED_MESSAGE;
  }
  return new ApiError(detail, res.status);
}

function formatApiErrorDetail(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          const record = item as Record<string, unknown>;
          const loc = Array.isArray(record.loc) ? record.loc.join(".") : "";
          const msg = typeof record.msg === "string" ? record.msg : JSON.stringify(record);
          return loc ? `${loc}: ${msg}` : msg;
        }
        return String(item);
      })
      .join("; ");
  }
  if (value && typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const { headers, ...rest } = options ?? {};
  const mergedHeaders: Record<string, string> = { "Content-Type": "application/json", ...authHeaders() };
  if (headers) {
    new Headers(headers).forEach((value, key) => {
      mergedHeaders[key] = value;
    });
  }
  const res = await fetch(`${BASE}${path}`, {
    ...rest,
    headers: mergedHeaders,
    // Live trading data — always bypass the browser HTTP cache so a stale or
    // empty response can never be replayed for a given URL.
    cache: "no-store",
  });
  if (!res.ok) {
    throw await errorFromResponse(res);
  }
  const text = await res.text();
  if (!text) return {} as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    const preview = text.replace(/\s+/g, " ").slice(0, 160);
    if (/^\s*(?:<!doctype\s+html|<html\b)/i.test(text)) {
      throw new ApiError("后端 API 未连接，请运行 scripts/dev doctor 检查服务。", res.status);
    }
    throw new ApiError(`API returned a non-JSON response: ${preview || "empty response"}`, res.status);
  }
}

export interface UploadResult {
  status: string;
  file_path: string;
  filename: string;
}

async function uploadFile(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/upload`, { method: "POST", headers: authHeaders(), body: form });
  if (!res.ok) {
    throw await errorFromResponse(res);
  }
  return res.json();
}

function appendQueryParam(url: string, key: string, value: string): string {
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}${encodeURIComponent(key)}=${encodeURIComponent(value)}`;
}

export const api = {
  uploadFile,
  listRuns: () => request<RunListItem[]>("/runs"),
  getRun: (id: string) => request<RunData>(`/runs/${id}`),
  getRunCode: (id: string) => request<Record<string, string>>(`/runs/${id}/code`),
  getRunPine: (id: string) => request<PineScriptResult>(`/runs/${id}/pine`),
  listSessions: () => request<SessionItem[]>("/sessions"),
  createSession: (title?: string) => request<SessionItem>("/sessions", { method: "POST", body: JSON.stringify({ title: title || "" }) }),
  deleteSession: (sid: string) => request<{ status: string }>(`/sessions/${sid}`, { method: "DELETE" }),
  renameSession: (sid: string, title: string) => request<{ status: string }>(`/sessions/${sid}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  sendMessage: (sid: string, content: string) => request<{ message_id: string; attempt_id: string }>(`/sessions/${sid}/messages`, { method: "POST", body: JSON.stringify({ content }) }),
  cancelSession: (sid: string) => request<{ status: string }>(`/sessions/${sid}/cancel`, { method: "POST" }),
  getSessionMessages: (sid: string) => request<MessageItem[]>(`/sessions/${sid}/messages`),
  createGoal: (sid: string, body: CreateGoalRequest) =>
    request<GoalSnapshot>(`/sessions/${sid}/goal`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getGoal: (sid: string) => request<GoalSnapshot>(`/sessions/${sid}/goal`),
  updateGoal: (sid: string, body: UpdateGoalRequest) =>
    request<UpdateGoalResponse>(`/sessions/${sid}/goal`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  addGoalEvidence: (sid: string, body: AddGoalEvidenceRequest) =>
    request<AddGoalEvidenceResponse>(`/sessions/${sid}/goal/evidence`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateGoalStatus: (sid: string, body: UpdateGoalStatusRequest) =>
    request<UpdateGoalStatusResponse>(`/sessions/${sid}/goal/status`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  sseUrl: (sid: string, options?: { replay?: "active" }) => {
    let url = withAuthQuery(`${BASE}/sessions/${sid}/events`);
    if (options?.replay) url = appendQueryParam(url, "replay", options.replay);
    return url;
  },

  // Swarm API
  listSwarmPresets: () => request<SwarmPreset[]>("/swarm/presets"),
  createSwarmRun: (preset_name: string, user_vars: Record<string, string>) =>
    request<{ id: string; status: string }>("/swarm/runs", {
      method: "POST",
      body: JSON.stringify({ preset_name, user_vars }),
    }),
  listSwarmRuns: () => request<SwarmRunSummary[]>("/swarm/runs"),
  getSwarmRun: (id: string) => request<Record<string, unknown>>(`/swarm/runs/${id}`),
  swarmSseUrl: (id: string) => withAuthQuery(`${BASE}/swarm/runs/${id}/events`),
  cancelSwarmRun: (id: string) =>
    request<{ status: string }>(`/swarm/runs/${id}/cancel`, { method: "POST" }),
  retrySwarmRun: (id: string) =>
    request<{ id: string; status: string; preset_name: string }>(`/swarm/runs/${id}/retry`, { method: "POST" }),
  getLLMSettings: () => request<LLMSettings>("/settings/llm"),
  updateLLMSettings: (settings: UpdateLLMSettingsRequest) =>
    request<LLMSettings>("/settings/llm", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),
  getDataSourceSettings: () => request<DataSourceSettings>("/settings/data-sources"),
  updateDataSourceSettings: (settings: UpdateDataSourceSettingsRequest) =>
    request<DataSourceSettings>("/settings/data-sources", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),

  // 投研分析
  createResearchAnalysisRun: (body: ResearchAnalysisCreate) =>
    request<ResearchAnalysisRun>("/research-analysis/runs", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getResearchAnalysisRun: (runId: string) =>
    request<ResearchAnalysisRun>(`/research-analysis/runs/${encodeURIComponent(runId)}`),
  listResearchAnalysisRuns: (params: ResearchAnalysisListParams = {}) => {
    const q = new URLSearchParams();
    if (params.symbol) q.set("symbol", params.symbol);
    if (params.market && params.market !== "all") q.set("market", params.market);
    if (params.rating && params.rating !== "all") q.set("rating", params.rating);
    if (params.query) q.set("query", params.query);
    if (params.date) q.set("date", params.date);
    if (params.limit) q.set("limit", String(params.limit));
    const qs = q.toString();
    return request<ResearchAnalysisList>(`/research-analysis/runs${qs ? `?${qs}` : ""}`);
  },
  deleteResearchAnalysisRun: (runId: string) =>
    request<{ status: string; run_id: string }>(`/research-analysis/runs/${encodeURIComponent(runId)}`, {
      method: "DELETE",
    }),

  // 模拟盘 (Paper Trading)
  createPaperTradingRun: (body: PaperTradingCreate) =>
    request<PaperTradingRun>("/paper-trading/runs", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listPaperTradingRuns: () =>
    request<PaperTradingList>("/paper-trading/runs"),
  getPaperTradingRun: (runId: string) =>
    request<PaperTradingRun>(`/paper-trading/runs/${encodeURIComponent(runId)}`),
  deletePaperTradingRun: (runId: string) =>
    request<{ status: string; run_id: string }>(`/paper-trading/runs/${encodeURIComponent(runId)}`, {
      method: "DELETE",
    }),
  robustOptimizePaperTrading: (body: RobustOptimizeRequest) =>
    request<RobustOptimizeResult>("/paper-trading/robust-optimize", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // Scanner API
  runScan: (universe = "sp500", top = 20) =>
    request<any>(`/scan/run?universe=${encodeURIComponent(universe)}&top=${top}`, {
      method: "POST",
    }),
  getScanLatest: (universe = "sp500") =>
    request<any>(`/scan/latest?universe=${encodeURIComponent(universe)}`),
  getScanDates: (universe = "sp500") =>
    request<{ dates: string[] }>(`/scan/dates?universe=${encodeURIComponent(universe)}`),
  getScanByDate: (asof: string, universe = "sp500") =>
    request<any>(`/scan/history/${asof}?universe=${encodeURIComponent(universe)}`),
  getScanTracking: (asof: string, universe = "sp500") =>
    request<any>(`/scan/tracking/${asof}?universe=${encodeURIComponent(universe)}`),
  getScanCalibration: (universe = "sp500") =>
    request<any>(`/scan/calibration?universe=${encodeURIComponent(universe)}`),
  getScanAccuracy: (universe = "sp500", provider?: string) =>
    request<ScanAccuracy>(`/scan/accuracy?universe=${encodeURIComponent(universe)}${provider ? `&provider=${encodeURIComponent(provider)}` : ""}`),
  getScanQuintile: (universe = "hstech", period = "2022-2025", rebalDays = 21, costBps = 30, refined = false) =>
    request<QuintileResponse>(`/scan/quintile?universe=${universe}&period=${period}&rebal_days=${rebalDays}&cost_bps=${costBps}&refined=${refined}`),
  getScanWalkforward: (universe = "hstech", period = "2022-2025", rebalDays = 21, costBps = 30) =>
    request<WalkForwardResponse>(`/scan/quintile/walkforward?universe=${universe}&period=${period}&rebal_days=${rebalDays}&cost_bps=${costBps}`),
  getScanPortfolio: (universe = "hkconnect", period = "2024-2026") =>
    request<ScanPortfolioResponse>(`/scan/quintile/portfolio?universe=${universe}&period=${period}`),

  getNewsCenterDates: () => request<string[]>("/news-center/dates"),
  getNewsCenterArticles: (filters: NewsCenterFilters = {}) => {
    const params = new URLSearchParams();
    if (filters.date) params.set("date", filters.date);
    if (filters.sector) params.set("sector", filters.sector);
    if (filters.direction) params.set("direction", filters.direction);
    if (filters.query) params.set("query", filters.query);
    if (filters.symbol) params.set("symbol", filters.symbol);
    if (filters.watchlistOnly) params.set("watchlist_only", "true");
    if (filters.language) params.set("language", filters.language);
    return request<NewsCenterList>(`/news-center/articles?${params}`);
  },
  getNewsCenterDigest: (date: string, language: "zh" | "en" = "zh") =>
    request<NewsCenterDigest>(`/news-center/digest?date=${encodeURIComponent(date)}&language=${language}`),
  refreshNewsCenter: () => request<NewsCenterRefreshResult>("/news-center/refresh", { method: "POST" }),
  generateNewsAiDigest: (date: string, language: "zh" | "en" = "zh", force = false) =>
    request<NewsCenterDigest>(
      `/news-center/ai-digest?date=${encodeURIComponent(date)}&language=${language}${force ? "&force=true" : ""}`,
      { method: "POST" },
    ),

  // 行业研报库
  getIndustryReports: () =>
    request<IndustryReportsResponse>("/research/industry-reports"),

  // 恒生科技研报库
  getHSTechReports: () =>
    request<IndustryReportsResponse>("/research/hstech-reports"),

  // 恒生科技新闻
  getHSTechNews: (refresh = false) =>
    request<{ items: NewsItem[]; cached: boolean }>(`/hstech/news${refresh ? "?refresh=true" : ""}`),
  getHSTechNewsArchiveDates: () =>
    request<{ dates: string[] }>("/hstech/news/archive/dates"),
  getHSTechNewsArchive: (date: string) =>
    request<{ date: string; items: NewsItem[] }>(`/hstech/news/archive?date=${encodeURIComponent(date)}`),

  // 走势预测
  getForecast: (market: string, code: string, months = 6, context = 0, nocache = 0, displayHistory = -1) =>
    request<ForecastResponse>(`/forecast/${market}/${encodeURIComponent(code)}?months=${months}&context=${context}&display_history=${displayHistory}${nocache ? "&nocache=1" : ""}`),
  getForecastCalibration: (market: string, code: string, context = 0) =>
    request<CalibrationResponse>(`/forecast/${market}/${encodeURIComponent(code)}/calibration?context=${context}`),
  // costBps omitted → backend resolves the market's real per-side cost
  // (slippage + commission + stamp duty) from its global cost model.
  getForecastStrategy: (market: string, code: string, context = 0, costBps?: number) =>
    request<StrategyResponse>(`/forecast/${market}/${encodeURIComponent(code)}/strategy?context=${context}${costBps != null ? `&cost_bps=${costBps}` : ""}`),
  getStrategyRobustness: (codes: string, context = 0, costBps?: number) =>
    request<RobustnessResponse>(`/forecast/robustness?codes=${encodeURIComponent(codes)}&context=${context}${costBps != null ? `&cost_bps=${costBps}` : ""}`),
  getHSTechSmartT: (period = "ALL", refresh = false) =>
    request<SmartTResponse>(`/hstech/smart-t?period=${period}${refresh ? "&refresh=true" : ""}`),
  getHSTechBestPaperStrategy: (refresh = false, startDate = "2020-01-01") =>
    request<HSTechBestStrategyResponse>(`/hstech/best-paper-strategy?start_date=${startDate}${refresh ? "&refresh=true" : ""}`),
  getForecastBestPaperStrategy: (market: string, code: string, refresh = false, startDate = "2020-01-01", strategy = "") =>
    request<HSTechBestStrategyResponse>(`/forecast/${market}/${encodeURIComponent(code)}/best-paper-strategy?start_date=${startDate}${refresh ? "&refresh=true" : ""}${strategy ? `&strategy=${encodeURIComponent(strategy)}` : ""}`),

  // Alpha Zoo API
  listAlphas: (params: AlphaListParams = {}) => {
    const q = new URLSearchParams();
    if (params.zoo) q.set("zoo", params.zoo);
    if (params.theme) q.set("theme", params.theme);
    if (params.universe) q.set("universe", params.universe);
    if (params.limit !== undefined) q.set("limit", String(params.limit));
    const qs = q.toString();
    return request<AlphaListResponse>(`/alpha/list${qs ? `?${qs}` : ""}`);
  },
  getAlpha: (alphaId: string) =>
    request<AlphaDetailResponse>(`/alpha/${encodeURIComponent(alphaId)}`),
  createAlphaBench: (body: AlphaBenchRequest) =>
    request<{ status: string; job_id: string }>("/alpha/bench", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  alphaBenchStreamUrl: (jobId: string) =>
    withAuthQuery(`${BASE}/alpha/bench/${encodeURIComponent(jobId)}/stream`),
  createAlphaCompare: (body: AlphaCompareRequest) =>
    request<{ status: string; job_id: string }>("/alpha/compare", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  alphaCompareStreamUrl: (jobId: string) =>
    withAuthQuery(`${BASE}/alpha/compare/${encodeURIComponent(jobId)}/stream`),

  // Connector runtime channel — privileged surface actions (NOT agent tools).
  // commit is the ONLY action that writes a mandate; halt trips the kill switch.
  commitMandate: (body: CommitMandateRequest) =>
    request<CommitMandateResponse>("/mandate/commit", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  haltLive: (session_id?: string, broker?: string, reason?: string) =>
    request<HaltLiveResponse>("/live/halt", {
      method: "POST",
      body: JSON.stringify({ session_id, broker, reason }),
    }),
  // Read the persistent runtime status across all authorized brokers (SPEC §7.5).
  // Polled by the RunnerStatus panel; a plain authenticated GET, never a chat message.
  getLiveStatus: () => request<LiveStatus>("/live/status"),
  authorizeLive: (broker: string) =>
    request<LiveAuthorizeResponse>("/live/authorize", {
      method: "POST",
      body: JSON.stringify({ broker }),
    }),
  // Start/stop the persistent runner (SPEC §7.5). Privileged surface actions, not agent tools.
  startLiveRunner: (broker: string) =>
    request<LiveRunnerResponse>("/live/runner/start", {
      method: "POST",
      body: JSON.stringify({ broker }),
    }),
  stopLiveRunner: (broker: string) =>
    request<LiveRunnerResponse>("/live/runner/stop", {
      method: "POST",
      body: JSON.stringify({ broker }),
    }),

  // 行情看板 — major index quotes (A-share + US)
  getMarketIndices: () => request<MarketIndex[]>("/market-indices"),

  // 自选股持久化
  getWatchlistCodes: (market: WatchlistMarket) =>
    request<{ market: string; codes: string[] }>(`/watchlist/codes?market=${market}`),
  setWatchlistCodes: (market: WatchlistMarket, codes: string[]) =>
    request<{ market: string; codes: string[] }>(`/watchlist/codes?market=${market}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ codes }),
    }),
  addWatchlistCode: (market: WatchlistMarket, code: string) =>
    request<{ market: string; codes: string[] }>(
      `/watchlist/codes/add?market=${market}&code=${encodeURIComponent(code)}`,
      { method: "POST" },
    ),
  removeWatchlistCode: (market: WatchlistMarket, code: string) =>
    request<{ market: string; codes: string[] }>(
      `/watchlist/codes/remove?market=${market}&code=${encodeURIComponent(code)}`,
      { method: "DELETE" },
    ),

  // 自选股行情
  getWatchlistQuote: (codes: string[], market: WatchlistMarket) =>
    request<WatchlistQuote[]>(`/watchlist/quote?codes=${encodeURIComponent(codes.join(","))}&market=${market}`),

  // 自选股历史走势
  getWatchlistHistory: (code: string, period: string, market?: WatchlistMarket) =>
    request<WatchlistHistoryResponse>(
      `/watchlist/history?code=${encodeURIComponent(code)}&period=${encodeURIComponent(period)}` +
        (market ? `&market=${market}` : "")
    ),

  // 自选股估值走势（市盈率/市净率/总市值）
  getWatchlistValuation: (code: string, market: WatchlistMarket, metric: ValuationMetric, period: ValuationPeriod) =>
    request<ValuationResponse>(
      `/watchlist/valuation?code=${encodeURIComponent(code)}&market=${market}&metric=${metric}&period=${period}`
    ),

  getStockCapital: (code: string) =>
    request<StockCapitalResponse>(`/stock/${encodeURIComponent(code)}/capital`),

  getStockEvents: (code: string) =>
    request<StockEventsResponse>(`/stock/${encodeURIComponent(code)}/events`),

  // 自选股机会中心
  getOpportunities: (filters: OpportunityFilters = {}) => {
    const q = new URLSearchParams();
    if (filters.market && filters.market !== "all") q.set("market", filters.market);
    if (filters.signal && filters.signal !== "all") q.set("signal", filters.signal);
    if (filters.level && filters.level !== "all") q.set("level", filters.level);
    const query = q.toString();
    return request<OpportunityList>(`/opportunities${query ? `?${query}` : ""}`);
  },
  getOpportunityDetail: (market: "hk" | "us", code: string, snapshotDate?: string) =>
    request<OpportunityDetail>(
      `/opportunities/${market}/${encodeURIComponent(code)}` +
        (snapshotDate ? `?date=${encodeURIComponent(snapshotDate)}` : "")
    ),
  getOpportunityHistory: (market: "hk" | "us", code: string, limit = 30) =>
    request<OpportunityHistoryPoint[]>(
      `/opportunities/${market}/${encodeURIComponent(code)}/history?limit=${limit}`
    ),
  refreshOpportunities: (markets: Array<"hk" | "us">, force = false) =>
    request<OpportunityRefreshJob>("/opportunities/refresh", {
      method: "POST",
      body: JSON.stringify({ markets, force }),
    }),
  getOpportunityRefreshJob: (jobId: string) =>
    request<OpportunityRefreshJob>(`/opportunities/refresh/${encodeURIComponent(jobId)}`),
  getOpportunityCalibration: (scope: "top3" | "all" = "top3") =>
    request<OpportunityCalibrationSummary>(`/opportunities/calibration?scope=${scope}`),

  startHistoricalEventRun: (market: "cn" | "hk" | "us", code: string, companyName: string, period: HistoricalEventPeriod, force = false) =>
    request<HistoricalEventRun>("/historical-events/runs", {
      method: "POST",
      body: JSON.stringify({ market, code, company_name: companyName, period, force }),
    }),
  getHistoricalEventRun: (runId: string) =>
    request<HistoricalEventRun>(`/historical-events/runs/${encodeURIComponent(runId)}`),
  getHistoricalEvents: (market: "cn" | "hk" | "us", code: string, period: HistoricalEventPeriod) =>
    request<HistoricalEvent[]>(`/historical-events/${market}/${encodeURIComponent(code)}?period=${period}`),

};

// --- 行情看板 types ---

export type WatchlistMarket = "cn" | "hk" | "us";
export type HistoricalEventPeriod = "1Y" | "3Y" | "5Y" | "ALL";

export interface HistoricalEventEvidence {
  title: string;
  url: string;
  snippet: string;
  source: string;
  published_at: string | null;
  evidence_type: string;
}

export interface HistoricalEvent {
  event_id: string;
  market: "cn" | "hk" | "us";
  symbol: string;
  company_name: string;
  start_date: string;
  end_date: string;
  direction: "up" | "down";
  return_pct: number;
  trigger_windows: number[];
  volatility_filter_available: boolean;
  benchmark_symbol: string;
  benchmark_return_pct: number | null;
  relative_return_pct: number | null;
  market_context: string;
  driver_type: string;
  primary_driver: string;
  narrative: string;
  confidence: "高" | "中" | "低";
  evidence: HistoricalEventEvidence[];
  alternative_factors: string[];
  causality_note: string;
  detector_version: string;
  analysis_version: string;
  analyzed_at: string;
}

export interface HistoricalEventRun {
  run_id: string;
  market: "cn" | "hk" | "us";
  symbol: string;
  company_name: string;
  period: HistoricalEventPeriod;
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  stage: string;
  cached: boolean;
  event_count: number;
  error: string | null;
}

export interface NewsCenterMatch {
  market: string; code: string; match_level: string; confidence: number;
  direction?: "positive" | "neutral" | "negative" | null; strength?: number | null;
}
export interface NewsCenterArticle {
  article_id: string; source: string; title: string; url: string; published_at: string;
  summary: string; sector: string; matches: NewsCenterMatch[]; importance: number; major: boolean;
  language?: "zh" | "en";
}
export interface NewsCenterList { items: NewsCenterArticle[]; total: number; sectors: string[]; }
export interface NewsAiMajorItem { title: string; summary: string; impact: "positive" | "negative" | "neutral"; }
export interface NewsCenterDigest {
  date: string; article_count: number; watchlist_count: number; positive_count: number;
  negative_count: number; summary: string; major_items: NewsCenterArticle[];
  ai_summary?: string | null; ai_major?: NewsAiMajorItem[];
  ai_generated_at?: string | null; ai_model?: string | null;
}
export interface NewsCenterRefreshResult { fetched: number; total: number; latest_date?: string | null; }
export interface NewsCenterFilters {
  date?: string; sector?: string; direction?: string; query?: string;
  symbol?: string; watchlistOnly?: boolean;
  language?: "zh" | "en";
}

export type PriceHistoryPeriod = "1D" | "1M" | "YTD" | "1Y" | "3Y" | "5Y" | "ALL";

export interface PriceHistoryBar {
  date: string;
  close: number;
  volume: number;
}

export interface WatchlistHistoryResponse {
  code: string;
  name: string;
  period: PriceHistoryPeriod;
  bars: PriceHistoryBar[];
}

export type ValuationMetric = "pe" | "pb" | "mktcap";
export type ValuationPeriod = "1Y" | "3Y" | "5Y" | "10Y" | "ALL";

export interface ValuationPoint {
  date: string;
  value: number;
}

export interface ValuationResponse {
  code: string;
  market: WatchlistMarket;
  metric: ValuationMetric;
  period: ValuationPeriod;
  points: ValuationPoint[];
}

export interface StockCapitalResponse {
  code: string;
  error?: string;
  margin: { date: string; rzye: number; rzmre: number; rqye: number; rzrqye: number }[];
  holders: { date: string; holder_num: number; change_ratio: number; avg_shares: number }[];
  block_trades: { date: string; price: number; premium_pct: number; amount: number; buyer: string; seller: string }[];
  dividends: { date: string; bonus_rmb: number; transfer_ratio: number; bonus_ratio: number }[];
  fund_flow: { date: string; main_net: number; super_net: number }[];
  fund_flow_20d_main_net: number;
}

export interface LockupRow { date: string; type: string; shares: number; ratio: number }
export interface LhbRecord { date: string; reason: string; net_buy_wan: number; turnover: number }
export interface LhbSeat { name: string; buy_wan: number; sell_wan: number; net_wan: number }

export interface StockEventsResponse {
  code: string;
  error?: string;
  asof: string;
  lockup: { history: LockupRow[]; upcoming: LockupRow[] };
  dragon_tiger: { records: LhbRecord[]; seats: { buy: LhbSeat[]; sell: LhbSeat[] } };
}

export interface WatchlistQuote {
  code: string;
  name: string;
  price: number;
  change_pct: number;
  prev_close: number;
  error?: string;
}

export type OpportunityLevel = "优先关注" | "值得观察" | "暂不参与" | "数据不足";
export type OpportunityAction = "entry" | "add" | "hold" | "exit" | "risk_exit" | "wait" | "none";
export type OpportunityDimension = "strategy" | "trend" | "risk" | "news" | "valuation";
export type OpportunityDriver = "strategy" | "news" | "mixed";

export interface OpportunityItem {
  market: "hk" | "us";
  code: string;
  company_name: string;
  snapshot_date: string;
  score: number | null;
  score_change: number | null;
  level: OpportunityLevel;
  latest_action: OpportunityAction;
  signal_date: string | null;
  strategy_name: string | null;
  strategy_label: string | null;
  primary_reason: string;
  risk_reasons: string[];
  dimensions: Record<OpportunityDimension, number | null>;
  data_as_of: string;
  stale: boolean;
  degraded: boolean;
  missing_dimensions: string[];
  score_version: string;
  strategy_version: string;
  driver_type?: OpportunityDriver;
  driver_summary?: string;
  strategy_contribution?: number | null;
  news_contribution?: number | null;
}

export interface OpportunityNewsImpact {
  article_id: string;
  market: "hk" | "us";
  code: string;
  direction: "positive" | "neutral" | "negative";
  strength: number | null;
  confidence: number | null;
  horizon: string;
  summary: string;
  rationale: string;
  match_level: "direct" | "industry" | "macro";
  published_at: string | null;
  title: string;
  source: string;
  url: string;
}

export interface OpportunityDetail extends OpportunityItem {
  news: OpportunityNewsImpact[];
  explanations: string[];
  history_available: boolean;
}

export type OpportunityHistoryPoint = OpportunityItem;

export interface OpportunityRefreshJob {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  markets: Array<"hk" | "us">;
  trigger: string;
  completed: number;
  total: number;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string | null;
  error: string | null;
}

export interface OpportunityList {
  items: OpportunityItem[];
  latest_success_at: string | null;
  active_job: OpportunityRefreshJob | null;
  last_refresh_error: string | null;
}

export interface OpportunityCalibrationPeriod {
  horizon_days: 5 | 20 | 60;
  completed_samples: number;
  pending_samples: number;
  missing_samples: number;
  win_rate: number | null;
  outperformance_rate: number | null;
  average_return: number | null;
  average_excess_return: number | null;
  max_loss: number | null;
}

export interface OpportunityCalibrationSummary {
  scope: "top3" | "all";
  periods: OpportunityCalibrationPeriod[];
  calculated_at: string | null;
  contains_fixed_universe_backfill: boolean;
  methodology_note: string;
}

export interface OpportunityFilters {
  market?: "all" | "hk" | "us";
  signal?: "all" | OpportunityAction;
  level?: "all" | OpportunityLevel;
}

export interface FactorScreening {
  id: string;
  zoo: string;
  ir: number;
  mono: number;
  q_means: number[];
  kept: boolean;
}

export interface ScanAccuracyHorizon {
  n: number;
  mean?: number;
  hit_rate?: number;
  top_q_mean?: number;
  bottom_q_mean?: number;
  spread?: number;
  ic?: number;
}
export interface ScanAccuracy {
  universe: string;
  provider?: string | null;
  total_tracked: number;
  horizons: { fwd_1d: ScanAccuracyHorizon; fwd_5d: ScanAccuracyHorizon; fwd_10d: ScanAccuracyHorizon; fwd_20d: ScanAccuracyHorizon };
  timeseries: { date: string; n: number; mean_1d: number }[];
}

export interface QuintileResponse {
  rebal_days: number;
  cost_bps: number;
  n_periods: number;
  quintile_returns: Record<string, number[]>;
  long_short: number[];
  dates: string[];
  summary: Record<string, { total_return: number; annual_return: number; annual_vol: number; sharpe: number; max_drawdown: number }>;
  spread_summary: { total_return: number; annual_return: number; annual_vol: number; sharpe: number; max_drawdown: number };
  long_q?: string;
  short_q?: string;
  screening?: FactorScreening[];
}

export interface WalkForwardFold {
  fold: number;
  is_start: string;
  is_end: string;
  oos_start: string;
  oos_end: string;
  n_factors_kept: number;
  factors_kept: string[];
  oos_ls_return: number;
  oos_periods?: number;
}

export interface WalkForwardResponse {
  rebal_days: number;
  cost_bps: number;
  is_days: number;
  oos_days: number;
  n_folds: number;
  folds: WalkForwardFold[];
  quintile_returns: Record<string, number[]>;
  long_short: number[];
  dates: string[];
  n_periods: number;
  summary: Record<string, { total_return: number; annual_return: number; annual_vol: number; sharpe: number; max_drawdown: number }>;
  spread_summary: { total_return: number; annual_return: number; annual_vol: number; sharpe: number; max_drawdown: number };
  long_q?: string;
  short_q?: string;
}

export interface ScanPortfolioResponse {
  universe: string;
  as_of: string;
  n_stocks: number;
  n_factors_used: number;
  factors_used: string[];
  portfolio: Record<string, string[]>;
  q1_count: number;
  q1_details?: { symbol: string; score: number }[];
  cached?: boolean;
}

export interface MarketIndex {
  code: string;
  name: string;
  market: string;
  price: number;
  change_pct: number;
  prev_close: number;
}

export interface NewsItem {
  title: string;
  summary: string;
  time: string;
  source: string;
  url: string;
}

export interface IndustryReport {
  date: string;
  org: string;
  title: string;
  segment: string;
  url: string;
  source?: string;
}

export interface IndustryReportsResponse {
  reports: IndustryReport[];
  cached: boolean;
  stale?: boolean;
  error?: string;
  begin: string;
  end: string;
}

export type ResearchAnalysisRating = "buy" | "hold" | "sell";
export type ResearchAnalysisStatus = "queued" | "running" | "completed" | "failed";
export type ResearchAnalysisMarket = "auto" | "us" | "hk";

export interface ResearchAnalysisCreate {
  symbol: string;
  market?: ResearchAnalysisMarket;
  analysis_date?: string | null;
}

export interface ResearchAnalysisReport {
  rating: ResearchAnalysisRating;
  confidence: number;
  horizon: string;
  summary: string;
  bull_case: string;
  bear_case: string;
  technical_view: string;
  fundamental_view: string;
  sentiment_news_view: string;
  risk_factors: string[];
  suggested_action: string;
  disclaimer: string;
  structured: boolean;
}

export interface ResearchAnalysisRun {
  run_id: string;
  symbol: string;
  market: string;
  company_name?: string | null;
  analysis_date: string;
  created_at: string;
  updated_at: string;
  status: ResearchAnalysisStatus;
  rating?: ResearchAnalysisRating | null;
  confidence?: number | null;
  summary: string;
  report?: ResearchAnalysisReport | null;
  report_markdown: string;
  raw_decision?: unknown;
  error?: string | null;
  analysis_config: Record<string, unknown>;
}

export interface ResearchAnalysisList {
  items: ResearchAnalysisRun[];
}

export interface ResearchAnalysisListParams {
  symbol?: string;
  market?: "all" | "us" | "hk";
  rating?: "all" | ResearchAnalysisRating;
  query?: string;
  date?: string;
  limit?: number;
}

// ── Paper Trading types ──────────────────────────────────────────────────────

export interface PaperHolding {
  symbol: string;
  market: "us" | "hk" | "cn";
  allocation_pct: number;
}

export interface PaperStrategyConfig {
  name:
    | "buy_and_hold"
    | "dca"
    | "grid"
    | "momentum_breakout"
    | "moving_average_cross"
    | "rsi_reversion"
    | "volatility_target"
    | "drawdown_rebalance"
    | "smart_dca"
    | "dca_then_hold"
    | "dca_two_year_then_hold"
    | "trend_volatility_filter"
    | "donchian_breakout"
    | "bollinger_reversion"
    | "trailing_stop"
    | "monthly_rebalance"
    | "macd_divergence"
    | "dual_momentum"
    | "atr_trend_stop"
    | "mean_reversion_scaleout"
    | "enhanced_dca_trend"
    | "breakout_pullback"
    | "quality_momentum"
    | "low_volatility_rotation"
    | "volatility_squeeze_breakout"
    | "risk_parity"
    | "price_volume_efficiency"
    | "accelerated_dca_entry"
    | "deep_drawdown_recovery"
    | "ma200_timing"
    | "value_averaging";
  params: Record<string, unknown>;
}

export interface PaperTradingCreate {
  title?: string;
  holdings: PaperHolding[];
  strategy: PaperStrategyConfig;
  start_date: string;
  end_date: string;
  initial_usd?: number;
  initial_hkd?: number;
}

export interface RobustOptimizeRequest {
  holdings: PaperHolding[];
  strategies: { name: string; params: Record<string, unknown> }[];
  start_date?: string;
  end_date: string;
  initial_usd?: number;
  initial_hkd?: number;
  window_years?: number;
  step_years?: number;
}

export interface RobustWindow {
  label: string;
  start: string;
  end: string;
  is_full: boolean;
}

export interface RobustCell {
  status: "ok" | "failed";
  rank?: number;
  score?: number;
  total_return?: number;
  max_loss?: number;
}

export interface RobustBeatCount {
  beating: number;
  total: number;
}

export interface RobustStrategyRow {
  name: string;
  cells: RobustCell[];
  mean_rank: number;
  worst_rank: number;
  rank_std: number;
  ok_count: number;
  mean_score: number | null;
  mean_return: number;
  mean_max_loss: number;
  mean_excess_vs_hold?: number | null;
  windows_beating_hold?: RobustBeatCount | null;
}

export interface RobustBaseline {
  name: string;
  mean_rank: number;
  mean_return: number;
  mean_max_loss: number;
  mean_score: number | null;
}

export interface RobustEnsemble {
  members: string[];
  cells: RobustCell[];
  ok_count: number;
  mean_score: number;
  mean_return: number;
  mean_max_loss: number;
  beats_winner: boolean;
  mean_excess_vs_hold: number | null;
  windows_beating_hold: RobustBeatCount | null;
}

export interface RobustParamVariant {
  param: string;
  value: number;
  mean_score: number | null;
  beats_hold: boolean | null;
}

export interface RobustParamSensitivity {
  name: string;
  verdict: "robust" | "sensitive" | "no_params";
  base_score: number | null;
  variants: RobustParamVariant[];
  worst_score: number | null;
}

export interface RobustOptimizeResult {
  windows: RobustWindow[];
  strategies: RobustStrategyRow[];
  best_strategy: string | null;
  baseline?: RobustBaseline | null;
  ensemble?: RobustEnsemble | null;
  param_sensitivity?: RobustParamSensitivity[];
  window_years: number;
  step_years: number;
  data_start: string;
  data_end: string;
  limiting_symbols: string[];
  history_cap_years: number;
}

export interface PaperTradingRun {
  run_id: string;
  title: string;
  holdings: PaperHolding[];
  strategy: PaperStrategyConfig;
  start_date: string;
  end_date: string;
  initial_usd: number;
  initial_hkd: number;
  initial_total_usd: number;
  status: "queued" | "running" | "completed" | "failed";
  created_at: string;
  updated_at: string;
  metrics: Record<string, unknown> | null;
  equity_curve: EquityPoint[] | null;
  trades: PaperTrade[] | null;
  error: string | null;
}

export interface PaperTrade {
  symbol: string;
  direction: number;
  entry_price: number;
  exit_price: number;
  entry_time: string;
  exit_time: string;
  size: number;
  pnl: number;
  pnl_pct: number;
  exit_reason: string;
  holding_bars: number;
  commission: number;
}

export interface PaperTradingList {
  items: PaperTradingRun[];
}

export interface HSTechBestStrategyCandidate {
  strategy: { name: string; label?: string; params?: Record<string, unknown> };
  status: "completed" | "failed";
  metrics: {
    total_return?: number | null;
    sharpe?: number | null;
    max_loss?: number | null;
    max_drawdown?: number | null;
    trade_count?: number | null;
  } | null;
  error?: string | null;
}

export interface StrategyBacktestMetrics extends Record<string, unknown> {
  total_return?: number | null;
  annual_return?: number | null;
  sharpe?: number | null;
  max_loss?: number | null;
  max_drawdown?: number | null;
  trade_count?: number | null;
}

export interface HSTechBestStrategyRun {
  run_id: string;
  title: string;
  status: "completed" | "failed";
  strategy: { name: string; label?: string; params?: Record<string, unknown> };
  start_date: string;
  end_date: string;
  metrics: StrategyBacktestMetrics | null;
  equity_curve: EquityPoint[];
  trades: TradeSignal[];
  paper_trades?: PaperTrade[];
  error: string | null;
}

export interface HSTechBestStrategyResponse {
  code: string;
  name: string;
  market: string;
  start_date: string;
  end_date: string;
  initial_total_usd: number;
  best: HSTechBestStrategyRun;
  candidates: HSTechBestStrategyCandidate[];
  summary: string;
  cached?: boolean;
  reliable?: boolean;
  signal_as_of?: string;
  selection_cached?: boolean;
  signal_cached?: boolean;
  robust_recommended?: string;  // the validated pick, even when overridden
  user_selected?: boolean;       // true when a manual strategy override is active
  selection?: {
    selected_strategy: string;
    selected_at?: string;
    valid_until?: string;
    reliable: boolean;
    training_end?: string;
    confidence_level?: "standard" | "low";
    history_note?: string;
    history_bars?: number;
  };
  oos_validation?: {
    start_date: string;
    end_date: string;
    passed: boolean;
    metrics?: {
      total_return?: number | null;
      sharpe?: number | null;
      max_loss?: number | null;
      max_drawdown?: number | null;
      trade_count?: number | null;
    };
  };
}

export interface ForecastResponse {
  code: string;
  name: string;
  market: string;
  horizon: number;
  history: PriceHistoryBar[];
  future_dates: string[];
  model: { point: number[]; p10: number[]; p50: number[]; p90: number[] } | null;
  model_available: boolean;
  model_error?: string | null;
  conformal_q?: number | null;
  context_used?: number | null;
  context_available?: number | null;
  baselines: { random_walk: number[]; drift: number[] };
  cached?: boolean;
}

export interface CalibrationResponse {
  code: string;
  name: string;
  market: string;
  model_available: boolean;
  n_folds: number;
  bt_horizon: number;
  context_used?: number | null;
  directional_accuracy?: { model: number | null; drift: number; n: number };
  mae?: { model: number | null; random_walk: number | null; drift: number | null };
  skill_vs_random_walk?: number | null;
  interval_coverage_80?: number | null;
  interval_score?: { model: number | null; random_walk: number | null };
  interval_score_skill?: number | null;
  mean_interval_width_pct?: number | null;
  conformal?: {
    target: number;
    coverage_raw: number;
    coverage_conformal: number;
    width_ratio: number | null;
  } | null;
  overlay?: {
    context_dates: string[];
    context: number[];
    future_dates: string[];
    p10: number[];
    p50: number[];
    p90: number[];
    realized: number[];
    q?: number | null;
  } | null;
}

export interface StrategyLikeMetrics {
  total_return: number;
  annual_return: number;
  annual_vol: number;
  sharpe: number;
  max_drawdown: number;
  calmar: number;
}

export interface StrategyMetrics {
  total_return: number;
  annual_return: number;
  annual_vol: number;
  max_drawdown: number;
  sharpe: number;
  win_rate: number;
  trade_count: number;
  excess_return: number;
  information_ratio: number;
  [k: string]: number;
}

export interface TradeSignal {
  entry_date: string;
  exit_date: string;
  entry_price: number;
  exit_price: number;
  pnl_pct: number;
  holding_bars: number;
  exit_reason: string;
}

export interface StrategyLeg {
  label?: string;
  metrics: StrategyMetrics;
  equity: [string, number][];
  trades?: TradeSignal[];
}

export interface StrategyResponse {
  code: string;
  name: string;
  market: string;
  model_available: boolean;
  params?: { rebalance: number; cost_bps: number; lead: number; eval_days: number; n_days: number };
  strategies?: { band_reversion: StrategyLeg; median_trend: StrategyLeg; vol_target: StrategyLeg };
  buy_and_hold?: StrategyLeg;
  dca?: StrategyLeg | null;
  beats_buy_and_hold?: boolean;
  best_excess_return?: number;
  vol_target_calmar_better?: boolean;
  cached?: boolean;
  error?: string;
}

export interface RobustnessAgg {
  median: number | null;
  mean: number | null;
  pct_positive: number | null;
}

export interface RobustnessRow {
  code: string;
  market: string;
  bh_return: number;
  band_reversion_excess: number;
  median_trend_excess: number;
  vol_target_excess: number;
  band_reversion_max_dd: number;
  vol_target_max_dd: number;
  [k: string]: number | string;
}

export interface RobustnessResponse {
  summary: {
    n: number;
    per_name: RobustnessRow[];
    excess: { band_reversion: RobustnessAgg; median_trend: RobustnessAgg; vol_target: RobustnessAgg };
    vol_target_dd_better_pct: number | null;
  };
  errors: { code: string; market: string; error: string }[];
  params: { context: number; rebalance: number; cost_bps: number };
}

export interface SmartTEvent {
  date: string;
  action: string;
  price: number;
  cash: number;
  shares: number;
  pnl: number;
  effective_cost: number;
  position_ratio: number;
  reason: string;
}

export interface SmartTResponse {
  code: string;
  name: string;
  market: string;
  period: string;
  params: {
    initial_position: number;
    core_position: number;
    tranche: number;
    buy_gap: number;
    sell_rebound: number;
    cost_take_profit: number;
    max_trades_per_month: number;
  };
  current_signal: {
    action: string;
    reason: string;
    suggested_cash: number;
    price: number;
    effective_cost: number;
    trapped_gap: number;
    position_ratio: number;
    cash_ratio: number;
    rsi: number | null;
  };
  summary: {
    final_value: number;
    cash: number;
    shares: number;
    realized_profit: number;
    effective_cost: number;
    cost_reduction: number;
    trade_count: number;
    sell_count: number;
    win_rate: number;
  };
  metrics: {
    smart_t: StrategyLikeMetrics;
    buy_and_hold: StrategyLikeMetrics;
  };
  smart_t: { label: string; equity: [string, number][] };
  buy_and_hold: { label: string; equity: [string, number][] };
  events: SmartTEvent[];
  cached?: boolean;
}

// --- Swarm types ---

export interface SwarmPreset {
  name: string;
  title: string;
  description: string;
  agent_count: number;
  variables: { name: string; description: string; required: boolean }[];
}

export interface SwarmRunSummary {
  id: string;
  preset_name: string;
  status: string;
  created_at: string;
  task_count: number;
  completed_count: number;
}

export interface LLMProviderOption {
  name: string;
  label: string;
  api_key_env?: string | null;
  base_url_env: string;
  default_model: string;
  default_base_url: string;
  api_key_required: boolean;
  auth_type?: string;
  login_command?: string | null;
}

export interface LLMSettings {
  provider: string;
  model_name: string;
  base_url: string;
  api_key_env?: string | null;
  api_key_configured: boolean;
  api_key_hint?: string | null;
  api_key_required: boolean;
  temperature: number;
  timeout_seconds: number;
  max_retries: number;
  reasoning_effort: string;
  sse_timeout_seconds: number;
  env_path: string;
  providers: LLMProviderOption[];
}

export interface UpdateLLMSettingsRequest {
  provider: string;
  model_name: string;
  base_url: string;
  api_key?: string;
  clear_api_key?: boolean;
  temperature: number;
  timeout_seconds: number;
  max_retries: number;
  reasoning_effort?: string;
}

export interface DataSourceSettings {
  tushare_token_configured: boolean;
  tushare_token_hint?: string | null;
  baostock_supported: boolean;
  baostock_installed: boolean;
  baostock_message: string;
  env_path: string;
}

export interface UpdateDataSourceSettingsRequest {
  tushare_token?: string;
  clear_tushare_token?: boolean;
}

// --- Types matching backend API contracts ---

export interface RunListItem {
  run_id: string;
  status: string;
  created_at: string;
  prompt?: string;
  total_return?: number;
  sharpe?: number;
  codes?: string[];
  start_date?: string;
  end_date?: string;
}

export interface PriceBar {
  time: string;
  timestamp?: string;
  code?: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface TradeMarker {
  time: string;
  timestamp?: string;
  code?: string;
  side: "BUY" | "SELL";
  price: number;
  qty?: number;
  reason?: string;
  text?: string;
}

export interface EquityPoint {
  time: string;
  equity: string | number;
  drawdown: string | number;
}

export interface ValidationData {
  monte_carlo?: {
    actual_sharpe: number;
    actual_max_dd: number;
    p_value_sharpe: number;
    p_value_max_dd: number;
    simulated_sharpe_mean: number;
    simulated_sharpe_std: number;
    simulated_sharpe_p5: number;
    simulated_sharpe_p95: number;
    n_simulations: number;
    n_trades: number;
    error?: string;
  };
  bootstrap?: {
    observed_sharpe: number;
    ci_lower: number;
    ci_upper: number;
    median_sharpe: number;
    prob_positive: number;
    confidence: number;
    n_bootstrap: number;
    error?: string;
  };
  walk_forward?: {
    n_windows: number;
    windows: Array<{
      window: number;
      start: string;
      end: string;
      return: number;
      sharpe: number;
      max_dd: number;
      trades: number;
      win_rate: number;
    }>;
    profitable_windows: number;
    consistency_rate: number;
    return_mean: number;
    return_std: number;
    sharpe_mean: number;
    sharpe_std: number;
    error?: string;
  };
}

export interface RunData {
  status: string;
  run_id: string;
  prompt?: string;
  elapsed_seconds?: number;
  run_directory?: string;
  run_stage?: string;
  run_context?: Record<string, unknown>;

  metrics?: BacktestMetrics;
  artifacts?: ArtifactInfo[];
  run_card?: RunCard;
  validation?: ValidationData;

  price_series?: Record<string, PriceBar[]>;
  indicator_series?: Record<string, Record<string, IndicatorPoint[]>>;
  trade_markers?: TradeMarker[];
  equity_curve?: EquityPoint[];
  trade_log?: Array<Record<string, string>>;
  run_logs?: Array<{ source?: string; line_number?: number; message?: string }>;
}

export interface RunCard {
  schema_version?: string;
  generated_at?: string;
  run_dir?: string;
  backtest?: Record<string, unknown>;
  reproducibility?: Record<string, unknown>;
  data_sources?: string[];
  metrics?: Record<string, unknown>;
  validation?: unknown;
  warnings?: string[];
  artifacts?: RunCardArtifact[];
  [key: string]: unknown;
}

export interface RunCardArtifact {
  path: string;
  size_bytes: number;
  sha256: string;
}

export interface BacktestMetrics {
  final_value: number;
  total_return: number;
  annual_return: number;
  max_drawdown: number;
  sharpe: number;
  win_rate: number;
  trade_count: number;
  [key: string]: number;
}


export interface IndicatorPoint {
  time: string;
  value: number;
}

export interface ArtifactInfo {
  name: string;
  path: string;
  type: string;
  size: number;
  exists: boolean;
}

export interface PineScriptResult {
  exists: boolean;
  content: string | null;
}

export interface SessionItem {
  session_id: string;
  title?: string;
  status?: string;
  created_at?: string;
  updated_at?: string;
  last_attempt_id?: string;
}

// --- Goal types ---

export type GoalStatus =
  | "active"
  | "paused"
  | "waiting_user"
  | "needs_refresh"
  | "insufficient_evidence"
  | "compliance_blocked"
  | "blocked"
  | "budget_limited"
  | "usage_limited"
  | "complete"
  | "cancelled"
  | "superseded";

export type GoalRiskTier =
  | "research_general"
  | "market_specific_short_term"
  | "personalized_advice_or_position_sizing";

export interface GoalRecord {
  goal_id: string;
  session_id: string;
  status: GoalStatus;
  objective: string;
  ui_summary: string;
  source: string;
  protocol: string;
  risk_tier: GoalRiskTier;
  token_budget?: number | null;
  tokens_used: number;
  turn_budget?: number | null;
  turns_used: number;
  time_budget_seconds?: number | null;
  time_used_seconds: number;
  budget_wrapup_sent: boolean;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  recap?: string | null;
}

export interface GoalClaim {
  claim_id: string;
  goal_id: string;
  session_id: string;
  claim_type: string;
  text: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface GoalCriterion {
  criterion_id: string;
  goal_id: string;
  session_id: string;
  text: string;
  required: boolean;
  status: string;
  freshness_requirement?: string | null;
  protocol_step?: string | null;
  created_at: string;
  updated_at: string;
}

export interface GoalEvidence {
  evidence_id: string;
  goal_id: string;
  session_id: string;
  text: string;
  criterion_id?: string | null;
  claim_id?: string | null;
  evidence_type: string;
  tool_call_id?: string | null;
  run_id?: string | null;
  source_provider?: string | null;
  source_type?: string | null;
  source_uri?: string | null;
  symbol_universe: string[];
  benchmark: string[];
  timeframe?: string | null;
  method?: string | null;
  assumptions: Record<string, unknown>;
  artifact_path?: string | null;
  artifact_hash?: string | null;
  retrieved_at: string;
  data_as_of?: string | null;
  freshness_status: string;
  verification_status: string;
  confidence?: string | null;
  caveat?: string | null;
  contradicts_claim_ids: string[];
  created_at: string;
}

export interface GoalSnapshot {
  goal: GoalRecord;
  claims: GoalClaim[];
  criteria: GoalCriterion[];
  evidence: GoalEvidence[];
  evidence_count: number;
}

export interface CreateGoalRequest {
  objective: string;
  criteria?: string[];
  ui_summary?: string;
  protocol?: string;
  risk_tier?: GoalRiskTier;
  token_budget?: number;
  turn_budget?: number;
  time_budget_seconds?: number;
}

export interface AddGoalEvidenceRequest {
  goal_id: string;
  expected_goal_id: string;
  text: string;
  criterion_id?: string | null;
  claim_id?: string | null;
  evidence_type?: string;
  tool_call_id?: string | null;
  run_id?: string | null;
  source_provider?: string | null;
  source_type?: string | null;
  source_uri?: string | null;
  symbol_universe?: string[];
  benchmark?: string[];
  timeframe?: string | null;
  method?: string | null;
  assumptions?: Record<string, unknown>;
  artifact_path?: string | null;
  artifact_hash?: string | null;
  data_as_of?: string | null;
  confidence?: string | null;
  caveat?: string | null;
  contradicts_claim_ids?: string[];
}

export interface UpdateGoalRequest {
  goal_id: string;
  expected_goal_id: string;
  objective?: string;
  ui_summary?: string;
}

export interface UpdateGoalResponse {
  goal: GoalRecord;
  snapshot: GoalSnapshot;
}

export interface AddGoalEvidenceResponse {
  evidence: GoalEvidence;
  snapshot: GoalSnapshot;
}

export interface GoalAuditRowRequest {
  criterion_id: string;
  result: string;
  evidence_ids?: string[];
  notes?: string;
}

export interface UpdateGoalStatusRequest {
  goal_id: string;
  expected_goal_id: string;
  status: GoalStatus;
  audit?: GoalAuditRowRequest[];
  recap?: string | null;
}

export interface UpdateGoalStatusResponse {
  goal: GoalRecord;
  snapshot: GoalSnapshot;
}

// --- Alpha Zoo types ---

export interface AlphaListParams {
  zoo?: string;
  theme?: string;
  universe?: string;
  limit?: number;
}

export interface AlphaSummary {
  id: string;
  zoo: string;
  theme: string[];
  universe: string[];
  nickname?: string;
  decay_horizon?: number | null;
  min_warmup_bars?: number | null;
  requires_sector?: boolean;
}

export interface AlphaListResponse {
  status: string;
  alphas: AlphaSummary[];
  total: number;
  returned: number;
  truncated: boolean;
}

export interface AlphaDetail {
  id: string;
  zoo: string;
  module_path?: string;
  meta: Record<string, unknown>;
}

export interface AlphaDetailResponse {
  status: string;
  alpha: AlphaDetail;
  source_code: string;
}

export interface AlphaBenchRequest {
  zoo: string;
  universe: string;
  period: string;
  top?: number;
}

export interface AlphaBenchTopRow {
  id: string;
  ic_mean: number;
  ir: number;
  theme: string[];
  formula_latex: string;
  category: "alive" | "reversed" | "dead";
}

export interface AlphaBenchResult {
  alive: number;
  reversed: number;
  dead: number;
  skipped?: number;
  top5_by_ir: AlphaBenchTopRow[];
  dead_examples: AlphaBenchTopRow[];
  by_theme: Record<string, { alive: number; reversed: number; dead: number }>;
}

export interface AlphaCompareRequest {
  alpha_ids: string[];
  universe: string;
  period: string;
  /** One of: ir | ic_mean | ic_positive_ratio | ic_count (default ir). */
  sort?: string;
}

export interface AlphaCompareRow {
  rank: number;
  id: string;
  zoo: string;
  ic_mean: number;
  ic_std: number;
  ir: number;
  ic_positive_ratio: number;
  ic_count: number;
  /** `delta_<sort>_vs_best` — gap to the top-ranked alpha on the active metric. */
  [deltaKey: string]: number | string;
}

export interface AlphaCompareSkip {
  id: string;
  reason: string;
}

export interface AlphaCompareResult {
  universe: string;
  period: string;
  sort: string;
  n_compared: number;
  n_skipped: number;
  winner: string;
  ranking: AlphaCompareRow[];
  skipped: AlphaCompareSkip[];
}

// --- Connector runtime channel types ---

/** One mandate profile inside a `mandate.proposal` event (SPEC Consent §1). */
export interface MandateProfile {
  ordinal: number;
  label: string;
  /** Concrete ticker list, or a structural universe descriptor (e.g. "tech_sector"). */
  universe: string[] | string;
  max_order_usd: number;
  daily_trade_cap: number;
  /** "none" for cash-only, otherwise a leverage descriptor/multiple. */
  leverage: string | number;
  instruments: string[];
  notes?: string;
}

/** Account block of a `mandate.proposal` event. */
export interface MandateProposalAccount {
  broker: string;
  type: string;
  funded_by: string;
}

/** Payload of the `mandate.proposal` SSE event (SPEC Consent §1). */
export interface MandateProposal {
  type?: string;
  proposal_id: string;
  session_id?: string;
  intent_normalized?: string;
  account?: MandateProposalAccount;
  ceilings_ref?: string;
  profiles: MandateProfile[];
  funding_note?: string;
  halt_note?: string;
  /** Present only when this proposal was triggered by a mandate breach (SPEC Consent §3). */
  reauth_for?: { breach_id?: string } | null;
}

/** Payload of the `mandate.committed` SSE event (SPEC Consent §1 COMMIT). */
export interface MandateCommitted {
  proposal_id?: string;
  mandate_id?: string;
  consent_record_id?: string;
  selected_ordinal?: number;
  broker?: string;
  /** Resolved limits, surfaced for the compact active-mandate badge. */
  max_order_usd?: number;
  daily_trade_cap?: number;
  expires_at?: string;
}

/** Payload of the `live.halted` SSE event (SPEC Consent §4). */
export interface LiveHalted {
  broker?: string | null;
  tripped_at?: string;
  by?: string;
  reason?: string;
}

/** Payload of the `live.action` SSE event (SPEC Consent §5 audit notify). */
export interface LiveAction {
  audit_id?: string;
  ts?: string;
  kind: string;
  intent_normalized?: string;
  outcome?: string;
  broker?: string;
  remote_tool?: string;
  error?: string | null;
}

export interface CommitMandateRequest {
  broker: string;
  proposal_id: string;
  selected_ordinal: number;
  /** Present only on the adjust path (SPEC Consent §3); null otherwise. */
  adjustments?: Record<string, unknown> | null;
  /** Explicit affirmative consent; the surface sets it on the user's click. */
  consent_ack: boolean;
  session_id?: string;
  account_ref?: string;
  lifetime_days?: number;
}

export interface CommitMandateResponse {
  mandate_id: string;
  consent_record_id: string;
  selected_ordinal?: number;
  broker?: string;
  max_order_usd?: number;
  daily_trade_cap?: number;
  expires_at?: string;
}

export interface HaltLiveResponse {
  halted: boolean;
  broker?: string | null;
  reason: string;
  sentinel: string;
}

export interface LiveAuthorizeRequest {
  broker: string;
}

export interface LiveAuthorizeResponse {
  broker: string;
  connector_profile: string;
  oauth_token_present: boolean;
  instruction: string;
  note?: string;
}

/** Mandate limits surfaced inside a `GET /live/status` broker entry (SPEC §7.5). */
export interface LiveMandateLimits {
  max_order_notional_usd?: number;
  max_total_exposure_usd?: number;
  max_leverage?: number;
  max_trades_per_day?: number;
  allowed_instruments?: string[];
  account_funding_usd?: number;
  [key: string]: unknown;
}

/** Active mandate block of a `GET /live/status` broker entry. */
export interface LiveMandateStatus {
  broker?: string;
  mandate_id?: string;
  account_ref?: string;
  created_at?: string;
  limits?: LiveMandateLimits;
  /** ISO timestamp the mandate auto-expires (SPEC §7.5 #7 proactive expiry). */
  expires_at?: string;
  expires_in_seconds?: number | null;
  expired?: boolean;
}

/** Runner liveness block of a `GET /live/status` broker entry (SPEC §7.5 #3). */
export interface LiveRunnerLiveness {
  broker?: string;
  alive: boolean;
  /** Unix epoch seconds of the last heartbeat tick; null if the runner never started. */
  last_tick?: number | string | null;
  last_tick_age_seconds?: number | null;
}

export interface LiveBrokerAuthStatus {
  broker: string;
  oauth_token_present: boolean;
  is_live_broker: boolean;
}

/** One broker entry in the `GET /live/status` response. */
export interface LiveBrokerStatus {
  auth: LiveBrokerAuthStatus;
  mandate?: LiveMandateStatus | null;
  runner: LiveRunnerLiveness;
  halted: boolean;
}

/** Response of `GET /live/status` (SPEC §7.5 runner status panel + C2). */
export interface LiveStatus {
  brokers: LiveBrokerStatus[];
  global_halted: boolean;
}

/** Response of `POST /live/runner/start|stop`. */
export interface LiveRunnerResponse {
  broker: string;
  started?: boolean;
  already_running?: boolean;
  stopped?: boolean;
  was_running?: boolean;
}

export interface MessageItem {
  message_id: string;
  session_id: string;
  role: string;
  content: string;
  created_at: string;
  linked_attempt_id?: string;
  metadata?: Record<string, unknown>;
}
