/** 朗读按钮。浏览器不支持语音合成时整个不渲染,而不是留一个按了没反应的按钮。 */
import { Volume2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { isSpeechSupported, speak } from "@/lib/speech";

export function SpeakButton({
  text,
  lang,
  label,
  className,
  onSpeak,
}: {
  text: string;
  /** 要用哪门语言的语音念。用英语语音念荷兰语,发音会错得离谱。 */
  lang: string;
  /** 无障碍名字,说清楚要读的是什么 */
  label: string;
  className?: string;
  /** 朗读时附带通知调用方——测验页用它来取消自动翻页 */
  onSpeak?: () => void;
}) {
  if (!isSpeechSupported()) return null;

  return (
    <button
      type="button"
      aria-label={label}
      onClick={(event) => {
        // 例句本身常常嵌在可点击的卡片里,别让朗读顺带触发了翻页或选答案。
        event.stopPropagation();
        onSpeak?.();
        speak(text, lang);
      }}
      className={cn(
        "inline-grid h-7 w-7 shrink-0 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary",
        className,
      )}
    >
      <Volume2 className="h-4 w-4" strokeWidth={1.8} />
    </button>
  );
}
