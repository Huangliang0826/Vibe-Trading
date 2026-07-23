import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  BarChart3,
  BookOpen,
  ChevronLeft,
  CheckCircle2,
  GraduationCap,
  Lightbulb,
  Loader2,
  RefreshCw,
  ScrollText,
  Sparkles,
  Star,
  TrendingUp,
  TriangleAlert,
  Wand2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { TOPICS } from "@/lib/learning/topics";
import { CARDS_BY_TOPIC, ALL_CARDS, getCard, addGeneratedCards } from "@/lib/learning/content";
import type { KnowledgeCard, CardType, TopicId } from "@/lib/learning/types";
import {
  loadProgress,
  saveProgress,
  markRead,
  setLastVisited,
  toggleFavorite,
  type LearningProgress,
} from "@/lib/learning/progress";
import { countDueReviews } from "@/lib/learning/review";
import { TOPIC_THEME } from "@/lib/learning/theme";
import { setExtraCards } from "@/lib/learning/content";
import { loadExtra } from "@/lib/learning/extra-store";
import { pullAndMerge, schedulePush } from "@/lib/learning/sync";
import { ReviewSession } from "@/components/learning/ReviewSession";
import { StatsPanel } from "@/components/learning/StatsPanel";

const TYPE_META: Record<CardType, { label: string; className: string; icon: typeof Lightbulb }> = {
  concept: { label: "概念", className: "bg-primary/10 text-primary", icon: Lightbulb },
  story: { label: "故事", className: "bg-info/10 text-info", icon: ScrollText },
  pitfall: { label: "陷阱", className: "bg-red-500/10 text-red-600 dark:text-red-400", icon: TriangleAlert },
};

function useProgress() {
  const [progress, setProgress] = useState<LearningProgress>(() => loadProgress());
  const update = useCallback((fn: (p: LearningProgress) => LearningProgress) => {
    setProgress((prev) => {
      const next = fn(prev);
      if (next !== prev) {
        saveProgress(next);
        schedulePush(); // 镜像到后端,跨设备同步
      }
      return next;
    });
  }, []);
  // 用(通常是跨设备合并后的)进度整体替换本地状态
  const replaceProgress = useCallback((next: LearningProgress) => {
    saveProgress(next);
    setProgress(next);
  }, []);
  return { progress, update, replaceProgress };
}

function DifficultyDots({ level }: { level: 1 | 2 | 3 }) {
  return (
    <span className="inline-flex items-center gap-0.5" title={`难度 ${level}/3`}>
      {[1, 2, 3].map((i) => (
        <span
          key={i}
          className={cn("h-1.5 w-1.5 rounded-full", i <= level ? "bg-warning" : "bg-muted-foreground/20")}
        />
      ))}
    </span>
  );
}

const CARD_BASE =
  "group relative flex min-h-[168px] flex-col overflow-hidden rounded-[22px] p-6 text-left shadow-[0_10px_30px_rgba(32,57,58,0.06)] transition duration-200 hover:-translate-y-0.5 hover:shadow-[0_18px_44px_rgba(32,57,58,0.12)] dark:shadow-none";

function TopicGrid({
  progress,
  favoritesCount,
  onOpenTopic,
  onOpenFavorites,
}: {
  progress: LearningProgress;
  favoritesCount: number;
  onOpenTopic: (id: TopicId) => void;
  onOpenFavorites: () => void;
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {TOPICS.map((topic, i) => {
        const cards = CARDS_BY_TOPIC[topic.id];
        const total = cards.length;
        const readCount = cards.filter((c) => progress.read[c.id]).length;
        const pct = total > 0 ? Math.round((readCount / total) * 100) : 0;
        const done = total > 0 && readCount === total;
        const theme = TOPIC_THEME[topic.id];
        return (
          <button
            key={topic.id}
            type="button"
            onClick={() => onOpenTopic(topic.id)}
            className={cn(CARD_BASE, theme.card)}
          >
            <div className="flex items-start justify-between">
              <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/45">
                主题 {String(i + 1).padStart(2, "0")}
              </span>
              <span className="text-2xl leading-none transition-transform duration-200 group-hover:scale-110">
                {theme.emoji}
              </span>
            </div>

            <h3 className="mt-5 text-[22px] font-semibold leading-tight tracking-tight text-foreground">
              {topic.title}
            </h3>
            <p className="mt-2 text-[13px] leading-6 text-foreground/60">{topic.subtitle}</p>

            {/* 底部进度:标签 — 细线 — 状态 */}
            <div className="mt-auto flex items-center gap-3 pt-6 text-[11px] font-medium text-foreground/60">
              <span className="shrink-0">已学 {readCount}/{total}</span>
              <div className="relative h-[3px] flex-1 overflow-hidden rounded-full bg-foreground/15">
                <div className="absolute inset-y-0 left-0 rounded-full bg-foreground/45 transition-all" style={{ width: `${pct}%` }} />
              </div>
              <span className="inline-flex shrink-0 items-center gap-1">
                {done ? (
                  <>
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    已学完
                  </>
                ) : (
                  `${pct}%`
                )}
              </span>
            </div>
          </button>
        );
      })}

      {/* 收藏夹入口 —— 中性米色,与彩色主题卡区分 */}
      <button
        type="button"
        onClick={onOpenFavorites}
        disabled={favoritesCount === 0}
        className={cn(
          CARD_BASE,
          "bg-[#eee8dd] dark:bg-[#2a2622]",
          favoritesCount === 0 && "cursor-default opacity-55 hover:translate-y-0 hover:shadow-[0_10px_30px_rgba(32,57,58,0.06)]",
        )}
      >
        <div className="flex items-start justify-between">
          <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/45">收藏夹</span>
          <Star className={cn("h-6 w-6 transition-transform duration-200 group-hover:scale-110", favoritesCount > 0 ? "fill-warning text-warning" : "text-foreground/30")} />
        </div>
        <h3 className="mt-5 text-[22px] font-semibold leading-tight tracking-tight text-foreground">我的收藏</h3>
        <p className="mt-2 text-[13px] leading-6 text-foreground/60">
          {favoritesCount > 0 ? "点过星标的好知识,常看常新" : "学习时点亮星标,好知识值得反复品味"}
        </p>
        <div className="mt-auto pt-6 text-[11px] font-medium text-foreground/60">已收藏 {favoritesCount} 条</div>
      </button>
    </div>
  );
}

// ── 学习 tab:卡片阅读器 ────────────────────────────────────────────────────
function CardReader({
  cards,
  title,
  initialCardId,
  progress,
  onToggleFavorite,
  onRead,
  onVisit,
  onBack,
  onAddCards,
}: {
  cards: KnowledgeCard[];
  title: string;
  initialCardId?: string;
  progress: LearningProgress;
  onToggleFavorite: (id: string) => void;
  onRead: (id: string) => void;
  onVisit: (card: KnowledgeCard) => void;
  onBack: () => void;
  /** 提供时,主题学完后可让 AI 扩充 10 条;返回新增卡片 */
  onAddCards?: () => Promise<KnowledgeCard[]>;
}) {
  const initialIndex = Math.max(0, cards.findIndex((c) => c.id === initialCardId));
  const [index, setIndex] = useState(initialIndex);
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState(false);
  const card = cards[index];
  if (!card) return null;

  const isRead = Boolean(progress.read[card.id]);
  const isFav = progress.favorites.includes(card.id);
  const meta = TYPE_META[card.type];
  const TypeIcon = meta.icon;
  const readCount = cards.filter((c) => progress.read[c.id]).length;

  const go = (next: number) => {
    const target = cards[next];
    if (!target) return;
    setIndex(next);
    onVisit(target);
  };

  const topicDone = readCount === cards.length;
  const onLastCard = index === cards.length - 1;

  const handleAdd = async () => {
    if (!onAddCards || adding) return;
    setAdding(true);
    setAddError(false);
    const firstNewIndex = cards.length; // 新卡追加在末尾
    try {
      const added = await onAddCards();
      if (added.length > 0) setIndex(firstNewIndex);
    } catch {
      setAddError(true);
    } finally {
      setAdding(false);
    }
  };

  const related = (card.relatedIds ?? [])
    .map((id) => getCard(id))
    .filter((c): c is KnowledgeCard => Boolean(c));

  return (
    <div className="space-y-4">
      {/* 顶部:返回 + 进度 */}
      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1.5 rounded-xl border bg-card/75 px-3 py-2 text-xs font-medium text-muted-foreground transition hover:border-primary/25 hover:text-primary"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
          {title}
        </button>
        <span className="text-xs text-muted-foreground">
          第 <span className="font-semibold text-foreground">{index + 1}</span>/{cards.length} 条 · 已学{" "}
          <span className="font-semibold text-foreground">{readCount}</span> 条
        </span>
      </div>
      <div className="h-1 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary transition-all"
          style={{ width: `${((index + 1) / cards.length) * 100}%` }}
        />
      </div>

      {/* 卡片本体 */}
      <article className="soft-card rounded-2xl p-6 sm:p-8">
        <div className="flex flex-wrap items-center gap-2">
          <span className={cn("inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-medium", meta.className)}>
            <TypeIcon className="h-3 w-3" />
            {meta.label}
          </span>
          {card.capstone && (
            <span className="inline-flex items-center gap-1 rounded-full bg-accent/10 px-2.5 py-1 text-[11px] font-medium text-accent">
              <GraduationCap className="h-3 w-3" />
              压轴
            </span>
          )}
          <DifficultyDots level={card.difficulty} />
          {isRead && (
            <span className="ml-auto inline-flex items-center gap-1 text-[11px] text-success">
              <CheckCircle2 className="h-3.5 w-3.5" />
              已学
            </span>
          )}
        </div>

        <h2 className="mt-4 text-xl font-semibold leading-snug tracking-tight sm:text-2xl">{card.title}</h2>
        <p className="mt-4 text-[15px] leading-7 text-foreground/90">{card.core}</p>

        {card.example && (
          <div className="mt-5 rounded-xl border border-info/20 bg-info/5 p-4">
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-info">案例</p>
            <p className="mt-1.5 text-sm leading-6 text-foreground/85">{card.example}</p>
          </div>
        )}

        {card.pitfall && (
          <div className="mt-3 rounded-xl border border-warning/25 bg-warning/5 p-4">
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-warning">避坑</p>
            <p className="mt-1.5 text-sm leading-6 text-foreground/85">{card.pitfall}</p>
          </div>
        )}

        {card.practiceLink && (
          <Link
            to={card.practiceLink.to}
            className="mt-5 inline-flex items-center gap-2 rounded-xl bg-accent/10 px-4 py-2.5 text-sm font-medium text-accent transition hover:bg-accent/15"
          >
            <TrendingUp className="h-4 w-4" />
            {card.practiceLink.label}
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        )}

        {related.length > 0 && (
          <div className="mt-6 border-t border-border/70 pt-4">
            <p className="text-[11px] text-muted-foreground">相关知识</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {related.map((r) => {
                const targetIdx = cards.findIndex((c) => c.id === r.id);
                return (
                  <button
                    key={r.id}
                    type="button"
                    disabled={targetIdx < 0}
                    onClick={() => go(targetIdx)}
                    className="rounded-full border bg-card px-3 py-1 text-xs text-muted-foreground transition hover:border-primary/25 hover:text-primary disabled:cursor-default disabled:opacity-50"
                    title={targetIdx < 0 ? "在其他主题中" : undefined}
                  >
                    {r.title}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </article>

      {/* 操作区 */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => go(index - 1)}
          disabled={index === 0}
          className="inline-flex h-11 items-center gap-1.5 rounded-xl border bg-card px-4 text-sm text-muted-foreground transition hover:text-foreground disabled:opacity-40"
        >
          <ArrowLeft className="h-4 w-4" />
          上一条
        </button>
        <button
          type="button"
          onClick={() => onToggleFavorite(card.id)}
          className={cn(
            "inline-flex h-11 items-center gap-1.5 rounded-xl border px-4 text-sm transition",
            isFav ? "border-warning/40 bg-warning/10 text-warning" : "bg-card text-muted-foreground hover:text-foreground",
          )}
        >
          <Star className={cn("h-4 w-4", isFav && "fill-warning")} />
          {isFav ? "已收藏" : "收藏"}
        </button>
        <button
          type="button"
          onClick={() => {
            onRead(card.id);
            if (index < cards.length - 1) go(index + 1);
          }}
          className="ml-auto inline-flex h-11 flex-1 items-center justify-center gap-1.5 rounded-xl bg-primary px-5 text-sm font-medium text-primary-foreground transition hover:opacity-90 sm:flex-none"
        >
          {index < cards.length - 1 ? (
            <>
              学完,下一条
              <ArrowRight className="h-4 w-4" />
            </>
          ) : isRead ? (
            "已全部学完 🎉"
          ) : (
            "学完本主题 🎉"
          )}
        </button>
      </div>

      {/* 主题学完:让 AI 再出 10 条新知识 */}
      {onAddCards && topicDone && onLastCard && (
        <div className="rounded-2xl border border-primary/15 bg-gradient-to-br from-primary/[0.07] to-accent/[0.07] p-5 text-center">
          <div className="mx-auto grid h-11 w-11 place-items-center rounded-2xl bg-primary/10 text-primary">
            <Sparkles className="h-5 w-5" />
          </div>
          <p className="mt-3 text-sm font-medium">本主题已全部学完 🎉</p>
          <p className="mx-auto mt-1 max-w-sm text-xs leading-5 text-muted-foreground">
            意犹未尽?让 DeepSeek 再为你续写 10 条同样有深度、有趣味的新知识,继续精进。
          </p>
          <button
            type="button"
            onClick={handleAdd}
            disabled={adding}
            className="mt-4 inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:opacity-60"
          >
            {adding ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                AI 正在续写 10 条…
              </>
            ) : (
              <>
                <Wand2 className="h-4 w-4" />
                增加 10 个知识点
              </>
            )}
          </button>
          {adding && <p className="mt-2 text-[11px] text-muted-foreground">一次生成 10 条完整知识,约需一分钟,请耐心等待</p>}
          {addError && <p className="mt-2 text-[11px] text-red-600 dark:text-red-400">扩充失败,请稍后再试</p>}
        </div>
      )}
    </div>
  );
}

// ── 页面 ───────────────────────────────────────────────────────────────────
type Tab = "learn" | "review" | "stats";

export function Learning() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tab: Tab = searchParams.get("tab") === "review" ? "review" : searchParams.get("tab") === "stats" ? "stats" : "learn";
  const [view, setView] = useState<{ kind: "grid" } | { kind: "topic"; id: TopicId } | { kind: "favorites" }>({ kind: "grid" });
  const { progress, update, replaceProgress } = useProgress();
  // AI 扩充卡片后自增,触发重新读取合并后的 CARDS_BY_TOPIC
  const [contentVersion, setContentVersion] = useState(0);

  // 挂载时与后端同步一次(拉取 → 无损合并 → 应用 → 回推),实现手机/网页同步
  useEffect(() => {
    let cancelled = false;
    pullAndMerge(loadProgress(), loadExtra()).then((merged) => {
      if (cancelled || !merged) return;
      replaceProgress(merged.progress);
      setExtraCards(merged.extra);
      setContentVersion((v) => v + 1);
      schedulePush(200); // 把合并结果尽快回写后端
    });
    return () => { cancelled = true; };
  }, [replaceProgress]);

  const handleAddCards = useCallback(async (topicId: TopicId): Promise<KnowledgeCard[]> => {
    const topic = TOPICS.find((t) => t.id === topicId);
    const res = await api.generateCards({
      topic_id: topicId,
      topic_title: topic?.title ?? "",
      topic_subtitle: topic?.subtitle ?? "",
      existing_titles: CARDS_BY_TOPIC[topicId].map((c) => c.title),
      count: 10,
    });
    const added = addGeneratedCards(topicId, res.cards);
    setContentVersion((v) => v + 1);
    schedulePush(200); // 新卡片同步到后端
    return added;
  }, []);

  const selectTab = (t: Tab) => {
    const next = new URLSearchParams(searchParams);
    if (t === "learn") next.delete("tab");
    else next.set("tab", t);
    setSearchParams(next, { replace: true });
  };

  const favoriteCards = useMemo(
    () => progress.favorites.map((id) => getCard(id)).filter((c): c is KnowledgeCard => Boolean(c)),
    [progress.favorites],
  );

  const dueCount = useMemo(() => countDueReviews(progress, ALL_CARDS), [progress]);
  const totalRead = Object.keys(progress.read).length;

  return (
    <div className="mx-auto max-w-3xl space-y-8 px-4 py-7 sm:px-6 sm:py-9">
      {/* Header */}
      <div className="flex items-start gap-4">
        <div className="mt-1 grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-primary/10 text-primary ring-1 ring-primary/10">
          <GraduationCap className="h-5 w-5" strokeWidth={1.8} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="page-kicker">Quant academy</p>
          <h1 className="mt-1.5 text-[30px] font-semibold leading-tight tracking-[-0.035em] sm:text-[32px]">量化学习</h1>
          <p className="mt-2 text-sm text-muted-foreground">五个主题一百条知识,把交易的智慧一条条学扎实</p>
        </div>
        {totalRead > 0 && (
          <div className="hidden shrink-0 text-right sm:block">
            <p className="text-2xl font-semibold text-primary">{totalRead}</p>
            <p className="text-[11px] text-muted-foreground">累计已学</p>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div role="tablist" aria-label="学习栏目" className="inline-flex rounded-lg border bg-muted/30 p-1">
        {(
          [
            { key: "learn", label: "学习", icon: BookOpen },
            { key: "review", label: "复习", icon: RefreshCw },
            { key: "stats", label: "学习进度", icon: BarChart3 },
          ] as const
        ).map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => selectTab(key)}
            className={cn(
              "inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm transition-colors",
              tab === key ? "bg-background font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
            {key === "review" && dueCount > 0 && (
              <span className="grid h-4 min-w-4 place-items-center rounded-full bg-red-500 px-1 text-[10px] font-semibold leading-none text-white">
                {dueCount}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      {tab === "learn" &&
        (view.kind === "grid" ? (
          <TopicGrid
            progress={progress}
            favoritesCount={favoriteCards.length}
            onOpenTopic={(id) => setView({ kind: "topic", id })}
            onOpenFavorites={() => setView({ kind: "favorites" })}
          />
        ) : (
          (() => {
            void contentVersion; // 扩充后触发本 IIFE 重新读取合并卡片
            const topicId = view.kind === "topic" ? view.id : null;
            const cards = topicId ? CARDS_BY_TOPIC[topicId] : favoriteCards;
            const title = topicId ? TOPICS.find((t) => t.id === topicId)?.title ?? "" : "我的收藏";
            if (cards.length === 0) {
              setView({ kind: "grid" });
              return null;
            }
            return (
              <CardReader
                cards={cards}
                title={title}
                initialCardId={topicId ? progress.lastVisited[topicId] : undefined}
                progress={progress}
                onToggleFavorite={(id) => update((p) => toggleFavorite(p, id))}
                onRead={(id) => update((p) => markRead(p, id))}
                onVisit={(card) => {
                  if (topicId) update((p) => setLastVisited(p, card.topicId, card.id));
                }}
                onBack={() => setView({ kind: "grid" })}
                onAddCards={topicId ? () => handleAddCards(topicId) : undefined}
              />
            );
          })()
        ))}

      {tab === "review" && <ReviewSession progress={progress} update={update} onDone={() => {}} />}

      {tab === "stats" && <StatsPanel progress={progress} onReview={() => selectTab("review")} />}
    </div>
  );
}
