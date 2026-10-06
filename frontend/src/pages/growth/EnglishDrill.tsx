/** 英语句型练习:100 个高频框架,练到能脱口而出。
 *
 *  练法是**检索练习**:先只给中文情境,自己把英文说出来,再看答案。只看英文
 *  觉得"认识"是识别,而真实对话里卡住的是产出那一层——所以答案默认是藏起来的。
 *
 *  评分不是对错,是"取回这句话花了多久"。只有连续"脱口而出"才能走到最后一盒,
 *  这正是自动化的定义:不是答得对,是答得不用想。
 */
import { useCallback, useEffect, useState } from "react";
import { ChevronDown, Eye, Loader2, RotateCcw, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import {
  api, type EnglishGrade, type EnglishPattern, type EnglishState,
} from "@/lib/api";

const GRADE_META: { grade: EnglishGrade; label: string; hint: string }[] = [
  { grade: "again", label: "想不起来", hint: "退回第一盒,今天再来一次" },
  { grade: "slow", label: "卡了一下", hint: "留在原处,过几天再见" },
  { grade: "instant", label: "脱口而出", hint: "进下一盒" },
];

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
  onGrade,
}: {
  item: EnglishPattern;
  index: number;
  total: number;
  onGrade: (grade: EnglishGrade) => Promise<void>;
}) {
  // 新句型没见过,无从检索,所以直接摊开让人先读熟;复习的则必须先自己产出。
  const [revealed, setRevealed] = useState(item.status === "new");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setRevealed(item.status === "new");
  }, [item.id, item.status]);

  const grade = async (g: EnglishGrade) => {
    setBusy(true);
    try {
      await onGrade(g);
    } finally {
      setBusy(false);
    }
  };

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
          {item.status === "new" ? "新句型" : `第 ${(item.box ?? 0) + 1} 盒`} · {index + 1} / {total}
        </span>
      </div>

      <div className="space-y-2">
        <p className="text-xs text-muted-foreground">
          {item.status === "new" ? "先读两遍,再用它造一句自己的话" : "先把英文说出来,再看答案"}
        </p>
        <p className="text-[17px] font-medium leading-relaxed">{item.cue}</p>
      </div>

      {revealed ? (
        <div className="space-y-4 border-t pt-5">
          <div>
            <p className="text-[19px] font-semibold tracking-tight">{item.frame}</p>
            <p className="mt-1 text-sm text-muted-foreground">{item.meaning}</p>
          </div>
          <ul className="space-y-1.5">
            {item.examples.map((example) => (
              <li key={example} className="text-[15px] leading-relaxed text-foreground/85">
                {example}
              </li>
            ))}
          </ul>

          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">刚才取回它花了多久?</p>
            <div className="grid gap-2 sm:grid-cols-3">
              {GRADE_META.map((g) => (
                <button
                  key={g.grade}
                  type="button"
                  disabled={busy}
                  onClick={() => grade(g.grade)}
                  className={cn(
                    "rounded-xl border px-3 py-2 text-sm transition-colors disabled:opacity-50",
                    g.grade === "instant"
                      ? "border-primary/40 bg-primary/10 text-primary hover:bg-primary/15"
                      : "hover:border-primary/40 hover:text-foreground",
                  )}
                >
                  <span className="block font-medium">{g.label}</span>
                  {/* 提示写成可见副标题而不是 title:手机上没有 hover,而且 title
                      会把按钮的无障碍名字整个盖掉。 */}
                  <span className="mt-0.5 block text-[11px] font-normal text-muted-foreground">
                    {g.hint}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setRevealed(true)}
          className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-primary/40 bg-primary/10 px-4 py-2.5 text-sm font-medium text-primary transition hover:bg-primary/15"
        >
          <Eye className="h-4 w-4" />看答案
        </button>
      )}
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

  const load = useCallback(async () => {
    try {
      const next = await api.getEnglish();
      setState(next);
      setQueue(next.session);
      setCursor(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

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

  const onGrade = async (grade: EnglishGrade) => {
    try {
      // 只从响应里取进度;队列由本地推进。
      setState(await api.reviewEnglish(item.id, grade));
      // 想不起来的排到本轮队尾,过几条再考一次,而不是立刻重看答案。
      if (grade === "again") {
        setQueue((q) => [...q, { ...item, status: "review" }]);
      }
      setCursor((c) => c + 1);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "记录失败");
    }
  };

  const reset = async () => {
    if (!window.confirm("清空 100 条句型的全部练习进度,确定吗?")) return;
    try {
      const next = await api.resetEnglish();
      setState(next);
      setQueue(next.session);
      setCursor(0);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "重置失败");
    }
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-3 gap-3">
        <Stat label="已自动化" value={stats.automatic} suffix={`/ ${stats.total}`} />
        <Stat label="练过" value={stats.started} suffix={`/ ${stats.total}`} />
        <Stat label="今天练了" value={stats.reviewed_today} suffix="条" />
      </div>

      {item ? (
        <Card item={item} index={cursor} total={queue.length} onGrade={onGrade} />
      ) : (
        <div className="space-y-2 rounded-2xl border bg-card p-6 text-center">
          <Sparkles className="mx-auto h-5 w-5 text-primary" />
          <p className="text-[15px] font-medium">今天的练习做完了</p>
          <p className="text-sm text-muted-foreground">
            {stats.due_today > 0
              ? `还有 ${stats.due_today} 条到期的,可以再练一轮。`
              : stats.started < stats.total
                ? `还有 ${stats.total - stats.started} 条没见过,明天继续。`
                : "100 条都练过了,接下来就是把它们一盒一盒推到自动化。"}
          </p>
          {stats.due_today > 0 && (
            <button
              type="button"
              onClick={() => void load()}
              className="mt-1 rounded-xl border border-primary/40 bg-primary/10 px-4 py-2 text-sm font-medium text-primary transition hover:bg-primary/15"
            >
              再练一轮
            </button>
          )}
        </div>
      )}

      {state.shaky.length > 0 && (
        <div className="space-y-3 rounded-2xl border bg-card p-5">
          <div>
            <h2 className="text-[15px] font-medium">还在卡壳的</h2>
            <p className="mt-1 text-sm text-muted-foreground">练了多次仍然想不起来——这几条值得单独多说几遍。</p>
          </div>
          <ul className="space-y-1.5">
            {state.shaky.map((row) => (
              <li key={row.id} className="flex items-baseline justify-between gap-3 text-sm">
                <span>
                  <span className="font-medium">{row.frame}</span>
                  <span className="ml-2 text-muted-foreground">{row.meaning}</span>
                </span>
                <span className="shrink-0 text-xs tabular-nums text-muted-foreground">练过 {row.seen} 次</span>
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
