/** 成就墙。每一条都对应一件确实做到的事,所以未解锁的也把进度显示出来——
 *  "还差 3 条"比一个灰色的锁更能让人去做下一题。 */
import {
  Bookmark, Brain, BookOpen, Flag, Flame, Languages, Lock, Sparkles, Target, Undo2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { GrowthAchievement } from "@/lib/api";

const ICONS: Record<string, typeof Flame> = {
  sparkles: Sparkles, flame: Flame, book: BookOpen, brain: Brain,
  target: Target, undo: Undo2, languages: Languages, bookmark: Bookmark, flag: Flag,
};

export function Achievements({
  items,
  unlocked,
  total,
}: {
  items: GrowthAchievement[];
  unlocked: number;
  total: number;
}) {
  return (
    <div className="space-y-4 rounded-2xl border bg-card p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-[15px] font-medium">成就</h2>
        <span className="text-xs tabular-nums text-muted-foreground">
          {unlocked} / {total}
        </span>
      </div>

      <ul className="grid gap-2 sm:grid-cols-2">
        {items.map((item) => {
          const Icon = ICONS[item.icon] ?? Sparkles;
          return (
            <li
              key={item.key}
              className={cn(
                "flex items-start gap-3 rounded-xl border p-3 transition-colors",
                item.unlocked ? "border-primary/40 bg-primary/[0.06]" : "opacity-80",
              )}
            >
              <span
                className={cn(
                  "mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg",
                  item.unlocked ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground",
                )}
              >
                {item.unlocked ? <Icon className="h-4 w-4" /> : <Lock className="h-3.5 w-3.5" />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium">{item.label}</span>
                <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">
                  {item.detail}
                </span>
                {!item.unlocked && (
                  <span className="mt-1.5 block">
                    <span className="block h-1 overflow-hidden rounded-full bg-muted">
                      <span
                        className="block h-full rounded-full bg-primary/50 transition-all"
                        style={{ width: `${item.percent}%` }}
                      />
                    </span>
                    <span className="mt-1 block text-[11px] tabular-nums text-muted-foreground">
                      {item.value} / {item.target}
                    </span>
                  </span>
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
