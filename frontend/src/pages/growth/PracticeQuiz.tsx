/** 英语句型 · 测试页:两选一,随机抽。
 *
 *  和学习页的分工:那边只过内容、不下判断;真正决定"记住没记住"的是这里的
 *  客观作答。自评会骗人——刚看完答案的人总会高估自己——所以盒子只由这里推进。
 *
 *  两个让它不只是"答对"的细节:
 *
 *  * **计时**。答对还要够快才算自动化。慢慢推出来的正确答案,在真实对话里
 *    仍然是卡壳,所以超时的正确答案不升盒(阈值由后端给)。
 *  * **干扰项来自同一个功能分组**。不同组的两张卡一眼就能排除,考不出分辨力。
 *
 *  问句以中文释义为主、情境为辅。同组的句型常是近义的,只给情境会出歧义题;
 *  释义在整份清单里唯一,所以每题恰好一个正确答案。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Loader2, RotateCcw, Timer, X, Zap } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import {
  api, type PracticeAnswerResult, type PracticeQuestion, type PracticeStats,
  type DailyProgress,
} from "@/lib/api";
import { SpeakButton } from "@/components/SpeakButton";
import { cancelSpeech } from "@/lib/speech";

const BATCH = 20;

interface Verdict extends PracticeAnswerResult {
  chosen_id: string;
}

function Stat({ label, value, suffix }: { label: string; value: string | number; suffix?: string }) {
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

export function PracticeQuiz({ lang, track }: { lang: string; track: string }) {
  const [questions, setQuestions] = useState<PracticeQuestion[] | null>(null);
  const [stats, setStats] = useState<PracticeStats | null>(null);
  const [today, setToday] = useState<DailyProgress | null>(null);
  const [cursor, setCursor] = useState(0);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const advanceTimer = useRef<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  //  本轮战绩,只活在这一轮里。
  const [round, setRound] = useState({ right: 0, wrong: 0, streak: 0, best: 0 });
  const askedAt = useRef<number>(Date.now());

  const load = useCallback(async () => {
    try {
      const data = await api.getPracticeQuiz(lang, track, BATCH);
      setQuestions(data.questions);
      setStats(data.stats);
      setToday(data.today_progress);
      setCursor(0);
      setVerdict(null);
      setRound({ right: 0, wrong: 0, streak: 0, best: 0 });
      askedAt.current = Date.now();
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    }
  }, [lang, track]);

  useEffect(() => {
    void load();
  }, [load]);

  // 每换一题都重新计时,否则停留在结果页的时间会算进下一题。
  useEffect(() => {
    askedAt.current = Date.now();
  }, [cursor]);

  useEffect(() => () => {
    if (advanceTimer.current) window.clearTimeout(advanceTimer.current);
  }, []);

  if (error) {
    return <p className="rounded-2xl border border-dashed p-6 text-center text-sm text-muted-foreground">{error}</p>;
  }
  if (!questions || !stats || !today) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />载入中…
      </div>
    );
  }

  const question = questions[cursor];

  const choose = async (chosenId: string) => {
    if (verdict) return;
    const elapsed = Date.now() - askedAt.current;
    try {
      const result = await api.answerPracticeQuiz(question.answer_id, chosenId, elapsed);
      setVerdict({ ...result, chosen_id: chosenId });
      setStats(result.stats);
      setToday(result.today_progress);
      // 答对就自动翻页,节奏才连得起来;答错停下来——两张卡的释义就摆在那里,
      // 那一眼才是真正学到区别的地方。
      if (result.correct) {
        advanceTimer.current = window.setTimeout(next, 1100);
      }
      setRound((r) => {
        const streak = result.correct ? r.streak + 1 : 0;
        return {
          right: r.right + (result.correct ? 1 : 0),
          wrong: r.wrong + (result.correct ? 0 : 1),
          streak,
          best: Math.max(r.best, streak),
        };
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "记录失败");
    }
  };

  /** 取消待执行的自动翻页。想听发音的时候页面不该从脚底下溜走。 */
  const holdPage = () => {
    if (advanceTimer.current) {
      window.clearTimeout(advanceTimer.current);
      advanceTimer.current = null;
    }
  };

  const next = () => {
    cancelSpeech();  // 翻页时掐掉上一题的朗读,别压在下一题上
    holdPage();
    setVerdict(null);
    setCursor((c) => c + 1);
  };

  const done = cursor >= questions.length;
  const answered = round.right + round.wrong;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-3 gap-3">
        <Stat
          label="今天目标"
          value={`${today.correct} / ${today.goal}`}
          suffix={today.done ? "已完成" : undefined}
        />
        <Stat label="总正确率" value={stats.accuracy === null ? "—" : `${stats.accuracy}%`} />
        <Stat label="本轮连对" value={round.streak} suffix={round.best ? `最高 ${round.best}` : undefined} />
      </div>

      {done ? (
        <div className="space-y-3 rounded-2xl border bg-card p-6 text-center">
          <p className="text-[15px] font-medium">这一轮答完了</p>
          <p className="text-sm text-muted-foreground">
            {answered > 0
              ? `${answered} 题答对 ${round.right} 题,最长连对 ${round.best}。`
              : "这一轮没有题目。"}
          </p>
          <button
            type="button"
            onClick={() => void load()}
            className="rounded-xl border border-primary/40 bg-primary/10 px-4 py-2 text-sm font-medium text-primary transition hover:bg-primary/15"
          >
            再来一轮
          </button>
        </div>
      ) : (
        <div className="space-y-5 rounded-2xl border bg-card p-5 sm:p-6">
          <div className="flex items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
                {question.group_label}
              </span>
              <span className="rounded-full border px-2.5 py-1 text-xs text-muted-foreground">
                {question.level_label}
              </span>
            </div>
            <span className="text-xs tabular-nums text-muted-foreground">
              {cursor + 1} / {questions.length}
            </span>
          </div>

          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">想表达这个意思,该说哪一句?</p>
            {/* 主问句用释义:同组的句型常是近义的,只给情境会出歧义题。 */}
            <p className="text-[17px] font-medium leading-relaxed">{question.meaning}</p>
            <p className="text-sm leading-relaxed text-muted-foreground">{question.cue}</p>
          </div>

          <div className="grid gap-3">
            {question.options.map((option) => {
              const isAnswer = option.id === question.answer_id;
              const isChosen = verdict?.chosen_id === option.id;
              return (
                <button
                  key={option.id}
                  type="button"
                  disabled={Boolean(verdict)}
                  onClick={() => void choose(option.id)}
                  className={cn(
                    "rounded-xl border px-4 py-3 text-left transition-colors",
                    !verdict && "hover:border-primary/50 hover:bg-primary/5",
                    // 答完同时标出"对的那张"和"你选的那张":只标对错学不到区别在哪。
                    verdict && isAnswer && "border-primary/60 bg-primary/10",
                    verdict && isChosen && !isAnswer && "border-destructive/50 bg-destructive/5",
                    verdict && !isAnswer && !isChosen && "opacity-50",
                  )}
                >
                  <span className="flex items-start justify-between gap-3">
                    <span className="min-w-0">
                      <span className="block text-[15px] font-medium">{option.frame}</span>
                      {verdict && (
                        <span className="mt-1 block text-sm text-muted-foreground">{option.meaning}</span>
                      )}
                    </span>
                    <span className="flex shrink-0 items-center gap-1">
                      {/* 答完才给朗读:答题当下出声会打乱节奏,也会把计时拖长。 */}
                      {verdict && (
                        <SpeakButton
                          lang={lang}
                          text={option.frame}
                          label={`朗读 ${option.frame}`}
                          onSpeak={holdPage}
                        />
                      )}
                      {verdict && isAnswer && <Check className="h-4 w-4 text-primary" />}
                      {verdict && isChosen && !isAnswer && <X className="h-4 w-4 text-destructive" />}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>

          {verdict && (
            <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 text-sm font-medium",
                  verdict.correct ? "text-primary" : "text-destructive",
                )}
              >
                {verdict.correct ? (
                  verdict.grade === "instant" ? (
                    <><Zap className="h-4 w-4" />够快,进下一盒</>
                  ) : (
                    <><Timer className="h-4 w-4" />答对了,但想得有点久</>
                  )
                ) : (
                  <><X className="h-4 w-4" />这条退回第一盒</>
                )}
              </span>
              <button
                type="button"
                onClick={next}
                className="rounded-xl border border-primary/40 bg-primary/10 px-4 py-2 text-sm font-medium text-primary transition hover:bg-primary/15"
              >
                下一题
              </button>
            </div>
          )}
        </div>
      )}

      <button
        type="button"
        onClick={() => void load()}
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition hover:text-foreground"
      >
        <RotateCcw className="h-3 w-3" />换一批题
      </button>
    </div>
  );
}
