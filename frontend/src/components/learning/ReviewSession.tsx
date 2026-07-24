import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, X, ArrowRight, ChevronLeft, Sparkles, HelpCircle, GraduationCap, Wand2, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { TOPICS } from "@/lib/learning/topics";
import { CARDS_BY_TOPIC, ALL_CARDS, getCard } from "@/lib/learning/content";
import type { TopicId, KnowledgeCard } from "@/lib/learning/types";
import type { LearningProgress } from "@/lib/learning/progress";
import { recordQuizResult } from "@/lib/learning/progress";
import { buildSessionQueue, countPracticeable, countDueReviews, shuffledOptions, type ReviewItem } from "@/lib/learning/review";
import { TOPIC_THEME } from "@/lib/learning/theme";
import { loadAiQuizCache, mergeIntoAiQuizCache, type AiQuizCache } from "@/lib/learning/aiquiz-cache";

const PREFETCH_BATCH = 10;

const SESSION_MAX = 10;

const QUIZ_TYPE_LABEL: Record<string, string> = {
  choice: "选择题",
  judge: "判断题",
  scenario: "情景题",
};

type Scope = TopicId | "all";

interface Answered {
  correct: boolean;
}

export function ReviewSession({
  progress,
  update,
  onDone,
}: {
  progress: LearningProgress;
  update: (fn: (p: LearningProgress) => LearningProgress) => void;
  onDone: () => void;
}) {
  const [scope, setScope] = useState<Scope>("all");
  const [queue, setQueue] = useState<ReviewItem[] | null>(null);
  const [index, setIndex] = useState(0);
  const [confident, setConfident] = useState(true);
  const [picked, setPicked] = useState<number | null>(null);
  const [results, setResults] = useState<Answered[]>([]);
  // AI 出题:打开即在后台批量预生成并缓存,做完自动补下一批,源源不断
  const [aiMode, setAiMode] = useState(false);
  const [cache, setCache] = useState<AiQuizCache>(() => loadAiQuizCache());
  const [busy, setBusy] = useState(false); // 是否有一批正在生成
  const [batchError, setBatchError] = useState(false);
  const cacheRef = useRef(cache);
  cacheRef.current = cache;
  const busyRef = useRef(busy);
  busyRef.current = busy;

  const learnedCount = useMemo(() => ALL_CARDS.filter((c) => progress.read[c.id]).length, [progress.read]);

  // 后台批量预生成:挑一组尚未缓存的卡片,一次调用生成整批并写入缓存
  const runPrefetch = useCallback((cards: KnowledgeCard[]) => {
    if (busyRef.current) return;
    const candidates = cards.filter((c) => !cacheRef.current[c.id]).slice(0, PREFETCH_BATCH);
    if (candidates.length === 0) return;
    setBusy(true);
    setBatchError(false);
    api
      .generateQuizBatch({
        items: candidates.map((c) => ({
          id: c.id,
          topic_title: TOPICS.find((t) => t.id === c.topicId)?.title ?? "",
          title: c.title,
          core: c.core,
          example: c.example,
          pitfall: c.pitfall,
        })),
      })
      .then((res) => setCache((prev) => mergeIntoAiQuizCache(prev, res.results)))
      .catch(() => setBatchError(true))
      .finally(() => setBusy(false));
  }, []);

  // 当前复习范围对应的候选卡池(用于预取即将练到的题;取较大范围保证源源不断)
  const poolFor = useCallback(
    (s: Scope): KnowledgeCard[] => {
      const cards = s === "all" ? ALL_CARDS : CARDS_BY_TOPIC[s];
      return buildSessionQueue(progress, cards, s, 40).map((i) => i.card);
    },
    [progress],
  );

  const cachedCount = useMemo(
    () => poolFor("all").filter((c) => cache[c.id]).length,
    [poolFor, cache],
  );

  // 各范围可练习的卡片数(学过的即可练;到期数单独用红点标示)
  const scopeCounts = useMemo(() => {
    const counts: Record<string, number> = { all: 0 };
    counts.all = countPracticeable(progress, ALL_CARDS, "all");
    for (const t of TOPICS) {
      counts[t.id] = countPracticeable(progress, CARDS_BY_TOPIC[t.id], t.id);
    }
    return counts;
  }, [progress]);

  const totalDue = useMemo(() => countDueReviews(progress, ALL_CARDS), [progress]);
  const dueByTopic = useMemo(() => {
    const m: Record<string, number> = {};
    for (const t of TOPICS) m[t.id] = countDueReviews(progress, CARDS_BY_TOPIC[t.id]);
    return m;
  }, [progress]);

  const start = (s: Scope) => {
    const cards = s === "all" ? ALL_CARDS : CARDS_BY_TOPIC[s];
    const q = buildSessionQueue(progress, cards, s, SESSION_MAX);
    setScope(s);
    setQueue(q);
    setIndex(0);
    setPicked(null);
    setConfident(true);
    setResults([]);
    // 确保本组题已(或正在)预生成
    if (aiMode) runPrefetch(q.map((i) => i.card));
  };

  // 打开 AI 出题的那一刻:立即在后台批量预生成一批题并缓存
  useEffect(() => {
    if (aiMode && learnedCount > 0) runPrefetch(poolFor("all"));
    // 仅在开关切换时触发一次预取
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aiMode]);

  // 做完一组后自动补下一批,保持"源源不断"
  const finished = queue !== null && index >= queue.length;
  useEffect(() => {
    if (aiMode && finished && learnedCount > 0) runPrefetch(poolFor("all"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aiMode, finished]);

  // ── 尚未开始:选择范围 ──
  if (!queue) {
    if (learnedCount === 0) {
      return (
        <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed bg-card/60 px-6 py-16 text-center">
          <div className="grid h-12 w-12 place-items-center rounded-2xl bg-primary/10 text-primary">
            <GraduationCap className="h-5 w-5" strokeWidth={1.8} />
          </div>
          <p className="text-sm font-medium">还没有可复习的知识</p>
          <p className="max-w-sm text-xs leading-5 text-muted-foreground">
            复习只考你学过的内容。先去「学习」tab 学几条,回来就能通过选择题、判断题和情景题检验掌握程度。
          </p>
        </div>
      );
    }
    return (
      <div className="space-y-4">
        {/* AI 出题开关 */}
        <div className="flex items-center gap-3 rounded-2xl border bg-card px-4 py-3">
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
            <Wand2 className="h-[18px] w-[18px]" strokeWidth={1.8} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-1.5 text-sm font-medium">
              AI 出题
              <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary">DeepSeek</span>
              {aiMode && busy && (
                <span className="inline-flex items-center gap-1 text-[10px] font-normal text-primary">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  准备中
                </span>
              )}
            </p>
            <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
              {aiMode
                ? busy
                  ? "正在后台批量生成题目并缓存,做完自动续上,源源不断"
                  : `已备好 ${cachedCount} 道题,即点即答,零等待`
                : "打开即后台批量出题并缓存,复习时即时呈现,不用等"}
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={aiMode}
            onClick={() => setAiMode((v) => !v)}
            className={cn(
              "relative h-6 w-11 shrink-0 rounded-full transition-colors",
              aiMode ? "bg-primary" : "bg-muted-foreground/30",
            )}
          >
            <span
              className={cn(
                "absolute left-0 top-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-transform",
                aiMode ? "translate-x-[22px]" : "translate-x-0.5",
              )}
            />
          </button>
        </div>

        {/* 综合复习:淡色主 CTA */}
        <button
          type="button"
          disabled={scopeCounts.all === 0}
          onClick={() => start("all")}
          className="group relative w-full overflow-hidden rounded-[22px] bg-gradient-to-br from-primary/[0.09] to-accent/[0.09] p-6 text-left ring-1 ring-primary/10 shadow-[0_10px_28px_rgba(32,57,58,0.05)] transition duration-200 hover:-translate-y-0.5 hover:shadow-[0_16px_40px_rgba(32,57,58,0.09)] disabled:cursor-default disabled:opacity-50 disabled:hover:translate-y-0 dark:shadow-none"
        >
          <span className="pointer-events-none absolute -right-5 -top-7 text-[104px] leading-none opacity-[0.08] transition-transform duration-300 group-hover:scale-110">
            ✨
          </span>
          <div className="relative">
            <div className="flex items-center gap-2 text-primary">
              <Sparkles className="h-4 w-4" />
              <span className="text-[11px] font-semibold uppercase tracking-[0.16em]">Daily review</span>
              {totalDue > 0 && (
                <span className="ml-auto rounded-full bg-primary/12 px-2.5 py-0.5 text-[11px] font-semibold text-primary">
                  {totalDue} 条到期
                </span>
              )}
            </div>
            <h3 className="mt-3 text-[22px] font-semibold leading-tight tracking-tight text-foreground">综合复习</h3>
            <p className="mt-1.5 text-[13px] leading-6 text-foreground/60">
              打乱全部主题,每组最多 {SESSION_MAX} 题。答错的更快再见,答对且有把握的间隔拉长。
            </p>
            <span className="mt-4 inline-flex items-center gap-1.5 rounded-full bg-primary px-4 py-2 text-[13px] font-medium text-primary-foreground transition group-hover:opacity-90">
              {scopeCounts.all > 0 ? `开始复习 · ${scopeCounts.all} 题就绪` : "暂无可复习内容"}
              {scopeCounts.all > 0 && <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />}
            </span>
          </div>
        </button>

        {/* 按主题复习:彩色卡片 */}
        <div>
          <p className="px-1 pb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            或按主题专项复习
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {TOPICS.map((t) => {
              const theme = TOPIC_THEME[t.id];
              const count = scopeCounts[t.id];
              const due = dueByTopic[t.id];
              const empty = count === 0;
              return (
                <button
                  key={t.id}
                  type="button"
                  disabled={empty}
                  onClick={() => start(t.id)}
                  className={cn(
                    "group relative flex min-h-[112px] flex-col overflow-hidden rounded-[20px] p-5 text-left shadow-[0_8px_24px_rgba(32,57,58,0.06)] transition duration-200 dark:shadow-none",
                    theme.card,
                    empty
                      ? "cursor-default opacity-55"
                      : "hover:-translate-y-0.5 hover:shadow-[0_16px_40px_rgba(32,57,58,0.12)]",
                  )}
                >
                  <div className="flex items-start justify-between">
                    <h4 className="text-[16px] font-semibold leading-tight tracking-tight text-foreground">{t.title}</h4>
                    <span className="text-xl leading-none transition-transform duration-200 group-hover:scale-110">
                      {theme.emoji}
                    </span>
                  </div>
                  <div className="mt-auto flex items-center gap-2 pt-4 text-[12px] font-medium text-foreground/65">
                    {empty ? (
                      <span>暂无待复习</span>
                    ) : (
                      <>
                        <span>{count} 题可复习</span>
                        {due > 0 && (
                          <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-[11px] font-semibold text-red-600 dark:text-red-400">
                            {due} 到期
                          </span>
                        )}
                        <ArrowRight className="ml-auto h-4 w-4 text-foreground/40 transition-transform group-hover:translate-x-0.5" />
                      </>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <p className="px-1 text-[11px] leading-5 text-muted-foreground">
          复习只考你学过的内容 · 采用间隔重复算法,越薄弱的知识出现得越勤
        </p>
      </div>
    );
  }

  // ── 复习结束:结算 ──
  if (index >= queue.length) {
    const correct = results.filter((r) => r.correct).length;
    const acc = results.length ? Math.round((correct / results.length) * 100) : 0;
    return (
      <div className="space-y-4">
        <div className="soft-card rounded-2xl p-8 text-center">
          <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-primary/10 text-primary">
            <Sparkles className="h-6 w-6" />
          </div>
          <h3 className="mt-4 text-lg font-semibold">本组复习完成 🎉</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            答对 <span className="font-semibold text-foreground">{correct}</span>/{results.length} 题 · 正确率{" "}
            <span className={cn("font-semibold", acc >= 80 ? "text-success" : acc >= 60 ? "text-warning" : "text-red-600 dark:text-red-400")}>
              {acc}%
            </span>
          </p>
          <p className="mt-3 text-xs leading-5 text-muted-foreground">
            答对且标记「有把握」的题已升入更长的复习间隔;答错的题会尽快再次出现。
          </p>
          <div className="mt-5 flex gap-2">
            <button
              type="button"
              onClick={() => start(scope)}
              className="flex-1 rounded-xl bg-primary py-2.5 text-sm font-medium text-primary-foreground transition hover:opacity-90"
            >
              再来一组
            </button>
            <button
              type="button"
              onClick={() => { setQueue(null); onDone(); }}
              className="flex-1 rounded-xl border bg-card py-2.5 text-sm text-muted-foreground transition hover:text-foreground"
            >
              返回
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── 答题中 ──
  const item = queue[index];
  const card = item.card;
  // 缓存里已有预生成的 AI 题 → 立即使用;否则若正在批量生成则显示等待;都没有则回退题库
  const cachedQuiz = aiMode ? cache[card.id] : undefined;
  const usingAi = !!cachedQuiz;
  const aiLoading = aiMode && !cachedQuiz && busy; // 后台批量还在生成本题
  const aiError = aiMode && !cachedQuiz && !busy && batchError;
  const staticShuffled = shuffledOptions(card);
  const current = cachedQuiz
    ? {
        type: cachedQuiz.type as string,
        question: cachedQuiz.question,
        options: cachedQuiz.options,
        answer: cachedQuiz.answer,
        explanation: cachedQuiz.explanation,
      }
    : {
        type: card.quiz.type as string,
        question: card.quiz.question,
        options: staticShuffled.options,
        answer: staticShuffled.answer,
        explanation: card.quiz.explanation,
      };
  const answered = picked !== null;
  const isCorrect = picked === current.answer;
  const sourceCard = getCard(card.id);

  const submit = (choice: number) => {
    if (answered || aiLoading) return;
    setPicked(choice);
    const correct = choice === current.answer;
    update((p) => recordQuizResult(p, card.id, correct, confident));
    setResults((r) => [...r, { correct }]);
  };

  const next = () => {
    setIndex((i) => i + 1);
    setPicked(null);
    setConfident(true);
  };

  return (
    <div className="space-y-4">
      {/* 顶部进度 */}
      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={() => { setQueue(null); }}
          className="inline-flex items-center gap-1.5 rounded-xl border bg-card/75 px-3 py-2 text-xs font-medium text-muted-foreground transition hover:border-primary/25 hover:text-primary"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
          退出
        </button>
        <span className="text-xs text-muted-foreground">
          第 <span className="font-semibold text-foreground">{index + 1}</span>/{queue.length} 题
        </span>
      </div>
      <div className="h-1 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${(index / queue.length) * 100}%` }} />
      </div>

      <div className="soft-card rounded-2xl p-6">
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-muted px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
            {QUIZ_TYPE_LABEL[current.type] ?? "选择题"}
          </span>
          {usingAi && (
            <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2.5 py-1 text-[11px] font-medium text-primary">
              <Wand2 className="h-3 w-3" />
              AI 出题
            </span>
          )}
          {!item.due && !usingAi && (
            <span className="rounded-full bg-info/10 px-2.5 py-1 text-[11px] font-medium text-info">首次测验</span>
          )}
          {/* 信心标记(答题前可切换) */}
          {!answered && !aiLoading && (
            <div className="ml-auto inline-flex rounded-lg border bg-muted/30 p-0.5 text-[11px]">
              <button
                type="button"
                onClick={() => setConfident(true)}
                className={cn("rounded-md px-2 py-1 transition", confident ? "bg-background font-medium text-foreground shadow-sm" : "text-muted-foreground")}
              >
                有把握
              </button>
              <button
                type="button"
                onClick={() => setConfident(false)}
                className={cn("inline-flex items-center gap-1 rounded-md px-2 py-1 transition", !confident ? "bg-background font-medium text-foreground shadow-sm" : "text-muted-foreground")}
              >
                <HelpCircle className="h-3 w-3" />
                拿不准
              </button>
            </div>
          )}
        </div>

        {aiLoading ? (
          <div className="mt-5 flex flex-col items-center gap-2.5 py-10 text-center">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
            <p className="text-sm font-medium">DeepSeek 正在批量准备题目…</p>
            <p className="text-[11px] text-muted-foreground">正在后台一次生成整组题,稍等片刻,之后即时出题</p>
          </div>
        ) : (
          <>
            {aiError && (
              <p className="mt-3 rounded-lg bg-warning/10 px-3 py-2 text-[11px] text-warning">
                AI 出题失败,已切换到题库题目
              </p>
            )}
            <h3 className="mt-4 text-base font-medium leading-relaxed">{current.question}</h3>

            <div className="mt-4 space-y-2">
              {current.options.map((opt, i) => {
                const isAnswer = i === current.answer;
                const isPicked = i === picked;
            return (
              <button
                key={i}
                type="button"
                disabled={answered}
                onClick={() => submit(i)}
                className={cn(
                  "flex w-full items-start gap-2.5 rounded-xl border px-4 py-3 text-left text-sm transition",
                  !answered && "hover:border-primary/40 hover:bg-primary/5",
                  answered && isAnswer && "border-success/50 bg-success/10",
                  answered && isPicked && !isCorrect && "border-red-500/50 bg-red-500/10",
                  answered && !isAnswer && !isPicked && "opacity-60",
                )}
              >
                <span
                  className={cn(
                    "mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border text-[11px] font-medium",
                    answered && isAnswer && "border-success bg-success text-white",
                    answered && isPicked && !isCorrect && "border-red-500 bg-red-500 text-white",
                    !(answered && (isAnswer || isPicked)) && "text-muted-foreground",
                  )}
                >
                  {answered && isAnswer ? <Check className="h-3 w-3" /> : answered && isPicked && !isCorrect ? <X className="h-3 w-3" /> : String.fromCharCode(65 + i)}
                </span>
                <span className="leading-6">{opt}</span>
              </button>
            );
          })}
        </div>

        {answered && (
          <div className="mt-4 space-y-3">
            <div
              className={cn(
                "rounded-xl border p-4",
                isCorrect ? "border-success/25 bg-success/5" : "border-red-500/25 bg-red-500/5",
              )}
            >
              <p className={cn("text-[11px] font-semibold uppercase tracking-[0.12em]", isCorrect ? "text-success" : "text-red-600 dark:text-red-400")}>
                {isCorrect ? (confident ? "答对了 ✓" : "答对了(但你标了拿不准,会再复习)") : "答错了"}
              </p>
              <p className="mt-1.5 text-sm leading-6 text-foreground/85">{current.explanation}</p>
            </div>
            {sourceCard && (
              <p className="text-[11px] text-muted-foreground">
                出自:{sourceCard.title}
              </p>
            )}
            <button
              type="button"
              onClick={next}
              className="w-full rounded-xl bg-primary py-2.5 text-sm font-medium text-primary-foreground transition hover:opacity-90"
            >
              {index < queue.length - 1 ? "下一题" : "完成本组"}
            </button>
          </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
