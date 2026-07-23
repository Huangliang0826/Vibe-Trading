import type { TopicId } from "./types";

/**
 * 每个主题一枚马卡龙色 + emoji。
 * - `card`:实心卡片底色(浅色马卡龙 / 深色低明度同色系)
 * - `soft`:淡色块(用于小徽标、复习选项等,浅淡背景 + 主题色文字)
 * 前景文字统一走 foreground(浅卡=深字、深卡=浅字),两种主题下都清晰。
 */
export const TOPIC_THEME: Record<TopicId, { emoji: string; card: string; soft: string; dot: string }> = {
  market: {
    emoji: "🏛️",
    card: "bg-[#f4dccf] dark:bg-[#38291f]",
    soft: "bg-[#f4dccf]/60 dark:bg-[#38291f]/60",
    dot: "bg-[#d98a63]",
  },
  technical: {
    emoji: "📈",
    card: "bg-[#e2d7f1] dark:bg-[#2b2540]",
    soft: "bg-[#e2d7f1]/60 dark:bg-[#2b2540]/60",
    dot: "bg-[#9b7fd0]",
  },
  quant: {
    emoji: "🧪",
    card: "bg-[#cfe7d8] dark:bg-[#1f3529]",
    soft: "bg-[#cfe7d8]/60 dark:bg-[#1f3529]/60",
    dot: "bg-[#5faa7a]",
  },
  risk: {
    emoji: "🛡️",
    card: "bg-[#f4dfa0] dark:bg-[#39301a]",
    soft: "bg-[#f4dfa0]/60 dark:bg-[#39301a]/60",
    dot: "bg-[#d6ab4a]",
  },
  psychology: {
    emoji: "🧠",
    card: "bg-[#d4e3ef] dark:bg-[#212f3b]",
    soft: "bg-[#d4e3ef]/60 dark:bg-[#212f3b]/60",
    dot: "bg-[#6f9dc0]",
  },
};
