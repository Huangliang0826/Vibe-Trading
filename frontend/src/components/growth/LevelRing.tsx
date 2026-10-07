/** 等级环。只数"走到最后一盒"的条数——那个数字涨得慢,但涨的时候是真记住了。 */
import { cn } from "@/lib/utils";
import type { GrowthLevel } from "@/lib/api";

export function LevelRing({ level, size = 96 }: { level: GrowthLevel; size?: number }) {
  const stroke = 8;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const filled = (level.percent / 100) * circumference;

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
        <circle
          cx={size / 2} cy={size / 2} r={radius} fill="none" strokeWidth={stroke}
          className="stroke-muted-foreground/15"
        />
        <circle
          cx={size / 2} cy={size / 2} r={radius} fill="none" strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circumference}`}
          className="stroke-primary transition-all duration-700"
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">
        <div>
          <p className="text-[11px] leading-none text-muted-foreground">Lv.{level.level}</p>
          <p className={cn("mt-0.5 font-semibold leading-none", size > 80 ? "text-lg" : "text-sm")}>
            {level.label}
          </p>
        </div>
      </div>
    </div>
  );
}
