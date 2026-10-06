/** 英语句型 · 学习页:把句型一条条过一遍。
 *
 *  内容一次摊开,没有"先猜再翻"这一步。检索练习归「测试」页——那里是客观
 *  作答、会计时、会推进复习盒子。在这一页藏答案只是多一次点击:反正点开就看,
 *  也没人判你猜得对不对。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight, Bookmark, ChevronDown, Loader2, RotateCcw, Sparkles,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { api, type EnglishPattern, type EnglishState } from "@/lib/api";
import { SpeakButton } from "@/components/SpeakButton";
import { cancelSpeech } from "@/lib/speech";

function Stat({ label, value, suffix }: { label: string; value: number; suffix?: string }) {
  return (
    <div className="rounded-2xl border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">
        {value}
        {suffix && <span className="text-xs font-normal text-muted-foreground"> {suffix}</span>}
      </p>
    </div>
  );
}

function Card({
  item,
  index,
  total,
  onNext,
  onStudied,
  onFavorite,
}: {
  item: EnglishPattern;
  index: number;
  total: number;
  onNext: () => void;
  onStudied: (id: string) => void;
  onFavorite: (id: string, favorite: boolean) => void;
}) {
  // 翻到这张卡就算接触过。
  useEffect(() => {
    onStudied(item.id);
  }, [item.id, onStudied]);

  return (
    <div className="space-y-5 rounded-2xl border bg-card p-5 sm:p-6">
      <div className="flex items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
            {item.group_label}
          </span>
          <span className="rounded-full border px-2.5 py-1 text-xs text-muted-foreground">
            {item.level_label}
          </span>
        </div>
        <span className="text-xs tabular-nums text-muted-foreground">
          {index + 1} / {total}
        </span>
      </div>

      <div>
        <div className="flex items-start gap-2">
          <p className="text-[19px] font-semibold tracking-tight">{item.frame}</p>
          <SpeakButton text={item.frame} label={`朗读句型 ${item.frame}`} className="mt-0.5" />
        </div>
        <p className="mt-1 text-sm text-muted-foreground">{item.meaning}</p>
      </div>

      <ul className="space-y-1.5">
        {item.examples.map((example) => (
          <li key={example} className="flex items-start gap-2">
            <SpeakButton text={example} label={`朗读例句 ${example}`} className="-ml-1" />
            <span className="text-[15px] leading-relaxed text-foreground/85">{example}</span>
          </li>
        ))}
      </ul>

      <p className="text-sm leading-relaxed text-muted-foreground">{item.cue}</p>

      <div className="grid gap-2 sm:grid-cols-2">
        <button
          type="button"
          onClick={() => onFavorite(item.id, !item.favorite)}
          aria-pressed={Boolean(item.favorite)}
          className={cn(
            "inline-flex items-center justify-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-medium transition",
            item.favorite
              ? "border-primary/50 bg-primary/10 text-primary"
              : "text-muted-foreground hover:border-primary/40 hover:text-foreground",
          )}
        >
          <Bookmark className={cn("h-4 w-4", item.favorite && "fill-current")} />
          {item.favorite ? "已收藏" : "收藏"}
        </button>
        <button
          type="button"
          onClick={onNext}
          className="inline-flex items-center justify-center gap-2 rounded-xl border border-primary/40 bg-primary/10 px-4 py-2.5 text-sm font-medium text-primary transition hover:bg-primary/15"
        >
          下一句<ArrowRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

function Catalog({ levels }: { levels: EnglishState["levels"] }) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<EnglishPattern[] | null>(null);

  useEffect(() => {
    if (!open || rows) return;
    void api.getEnglishPatterns().then((d) => setRows(d.patterns)).catch(() => setRows([]));
  }, [open, rows]);

  const byLevel = (key: string) =>
    (rows ?? []).filter((p) => p.level === key).reduce<Record<string, EnglishPattern[]>>(
      (acc, p) => {
        (acc[p.group_label] ??= []).push(p);
        return acc;
      },
      {},
    );

  return (
    <div className="rounded-2xl border bg-card">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 p-5 text-left"
      >
        <span className="text-[15px] font-medium">
          全部 {levels.reduce((n, l) => n + l.total, 0)} 条句型
        </span>
        <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="space-y-6 border-t p-5">
          {rows === null ? (
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          ) : (
            levels.map((level) => (
              <div key={level.key} className="space-y-4">
                <p className="text-sm font-semibold">
                  {level.label}
                  <span className="ml-2 text-xs font-normal text-muted-foreground">
                    {level.total} 条
                  </span>
                </p>
                {Object.entries(byLevel(level.key)).map(([label, items]) => (
                  <div key={label} className="space-y-2">
                    <p className="text-xs font-medium text-primary">{label}</p>
                    <ul className="space-y-1.5">
                      {items.map((p) => (
                        <li key={p.id} className="flex items-baseline justify-between gap-3 text-sm">
                          <span className="min-w-0">
                            <span className="font-medium">{p.frame}</span>
                            <span className="ml-2 text-muted-foreground">{p.meaning}</span>
                          </span>
                          {(p.box ?? -1) >= 0 && (
                            <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                              {p.box === 4 ? "已自动化" : `第 ${(p.box ?? 0) + 1} 盒`}
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

export function EnglishDrill() {
  const [state, setState] = useState<EnglishState | null>(null);
  // 本轮的练习队列是本地的。服务端每次打分都会重算"今天到期"的列表,长度会变;
  // 拿索引去指一个会变长的列表,打完一条就会跳过下一条。
  const [queue, setQueue] = useState<EnglishPattern[]>([]);
  const [cursor, setCursor] = useState(0);
  const [error, setError] = useState<string | null>(null);
  // 本轮已上报过的,避免来回翻卡片时重复请求。
  const studied = useRef<Set<string>>(new Set());

  const load = useCallback(async () => {
    try {
      const next = await api.getEnglish();
      setState(next);
      setQueue(next.session);
      setCursor(0);
      studied.current.clear();
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleFavorite = useCallback((id: string, favorite: boolean) => {
    void api.setEnglishFavorite(id, favorite).then(setState).catch(() => undefined);
    // 本地立即反映,别等往返——收藏是个高频的小动作。
    setQueue((q) => q.map((p) => (p.id === id ? { ...p, favorite } : p)));
  }, []);

  const next = useCallback(() => {
    cancelSpeech();
    setCursor((c) => c + 1);
  }, []);

  // 向右键翻到下一句:连着看几十条时,手不用离开键盘。
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "ArrowRight" || event.metaKey || event.ctrlKey || event.altKey) return;
      // 在输入框里按方向键是移动光标,不该顺手翻页。target 不一定是元素
      // (window、document 都可能),所以不能直接当成 Element 用。
      const target = event.target;
      if (target instanceof Element && target.closest("input, textarea, [contenteditable='true']")) {
        return;
      }
      event.preventDefault();
      next();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [next]);

  const markStudied = useCallback((id: string) => {
    if (studied.current.has(id)) return;
    studied.current.add(id);
    // 用返回的新统计刷新计数,否则"学过"要等到重新加载才会动。
    void api.markEnglishStudied(id).then(setState).catch(() => studied.current.delete(id));
  }, []);

  if (error) {
    return <p className="rounded-2xl border border-dashed p-6 text-center text-sm text-muted-foreground">{error}</p>;
  }
  if (!state) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />载入中…
      </div>
    );
  }

  const { stats } = state;
  const item = queue[cursor];

  const reset = async () => {
    if (!window.confirm("清空 100 条句型的全部练习进度,确定吗?")) return;
    try {
      const next = await api.resetEnglish();
      setState(next);
      setQueue(next.session);
      setCursor(0);
      studied.current.clear();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "重置失败");
    }
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-3 gap-3">
        <Stat label="已收藏" value={stats.favorites} suffix="句" />
        <Stat label="学过" value={stats.started} suffix={`/ ${stats.total}`} />
        <Stat label="考过" value={stats.tested} suffix={`/ ${stats.total}`} />
      </div>

      {item ? (
        <Card
          item={item}
          index={cursor}
          total={queue.length}
          onNext={next}
          onStudied={markStudied}
          onFavorite={toggleFavorite}
        />
      ) : (
        <div className="space-y-2 rounded-2xl border bg-card p-6 text-center">
          <Sparkles className="mx-auto h-5 w-5 text-primary" />
          <p className="text-[15px] font-medium">这一轮都看完了</p>
          <p className="text-sm text-muted-foreground">去「测试」考一遍,记住没记住那里说了算。</p>
          <button
            type="button"
            onClick={() => void load()}
            className="mt-1 rounded-xl border border-primary/40 bg-primary/10 px-4 py-2 text-sm font-medium text-primary transition hover:bg-primary/15"
          >
            再看一轮
          </button>
        </div>
      )}

      {state.favorites.length > 0 && (
        <div className="space-y-3 rounded-2xl border bg-card p-5">
          <h2 className="text-[15px] font-medium">已收藏的句式</h2>
          <ul className="space-y-2">
            {state.favorites.map((row) => (
              <li key={row.id} className="flex items-start justify-between gap-3 text-sm">
                <span className="min-w-0">
                  <span className="font-medium">{row.frame}</span>
                  <span className="ml-2 text-muted-foreground">{row.meaning}</span>
                </span>
                <span className="flex shrink-0 items-center gap-1">
                  <SpeakButton text={row.frame} label={`朗读 ${row.frame}`} />
                  <button
                    type="button"
                    onClick={() => toggleFavorite(row.id, false)}
                    className="text-xs text-muted-foreground transition hover:text-foreground"
                  >
                    取消
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <Catalog levels={state.levels} />

      <button
        type="button"
        onClick={reset}
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition hover:text-foreground"
      >
        <RotateCcw className="h-3 w-3" />清空练习进度
      </button>
    </div>
  );
}
