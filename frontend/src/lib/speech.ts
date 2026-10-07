/** 朗读:挑一个像样的英语语音,把句型和例句读出来。
 *
 *  用浏览器自带的 Web Speech API,不走后端——没有密钥、没有延迟、没有调用成本,
 *  而 macOS 与 iOS 自带的英语语音质量足够做跟读。
 *
 *  **选音不能随便取第一个。** 这台机器上 `getVoices()` 返回 41 个英语语音,排在
 *  最前面的几个是 Bad News、Bahh、Bells、Boing——macOS 自带的玩具语音,会唱歌或
 *  发怪声。所以这里用显式的优先级打分:好语音加分,玩具语音直接排除。
 */

/** 每门语言的首选语音名,按优先级。苹果系与 Chrome 各覆盖一部分。 */
const PREFERRED_BY_LANG: Record<string, string[]> = {
  en: [
  "samantha",
  "google us english",
  "google uk english female",
  "google uk english male",
  "daniel",
  "karen",
  "moira",
    "tessa",
  ],
  // 荷兰语:macOS 自带 Xander(荷兰)和 Ellen(比利时),Chrome 另有 Google 的。
  nl: ["xander", "google nederlands", "ellen"],
};

const LANG_PREFIXES: Record<string, string[]> = {
  en: ["en-us", "en-gb", "en"],
  nl: ["nl-nl", "nl-be", "nl"],
};

/** 名字里带这些词的通常是新一代高质量语音。 */
const QUALITY_HINTS = ["siri", "natural", "enhanced", "premium"];

/** 会唱歌、发怪声或机器音的玩具语音——读出来的东西不能用来跟读。 */
const NOVELTY = new Set([
  "albert", "bad news", "bahh", "bells", "boing", "bubbles", "cellos",
  "good news", "jester", "junior", "organ", "superstar", "trinoids",
  "whisper", "wobble", "zarvox", "fred", "kathy", "ralph", "deranged",
  "hysterical", "pipe organ", "princess", "bruce", "agnes",
]);

export interface VoiceLike {
  name: string;
  lang: string;
}

export function scoreVoice(voice: VoiceLike, target = "en"): number {
  const name = voice.name.toLowerCase();
  const lang = voice.lang.toLowerCase();
  // 语言不对直接出局。用英语语音念荷兰语,发音会错得离谱——对语言学习者来说
  // 这比不出声更糟。
  if (!lang.startsWith(target)) return -Infinity;
  // 玩具语音一律出局,不是"排在最后"。Whisper 是沙哑耳语、Zarvox 和 Bad News
  // 是机器阴森腔,拿它们念外语比没有声音更糟;而只要能被挑中,早晚会被挑中。
  if (NOVELTY.has(name.replace(/\s*\(.*\)\s*$/, "").trim())) return -Infinity;

  let score = 0;
  const preferred = (PREFERRED_BY_LANG[target] ?? []).findIndex((p) => name.startsWith(p));
  if (preferred >= 0) score += 100 - preferred;
  if (QUALITY_HINTS.some((hint) => name.includes(hint))) score += 20;
  const prefixes = LANG_PREFIXES[target] ?? [target];
  const rank = prefixes.findIndex((p) => lang.startsWith(p));
  score += rank >= 0 ? 10 - rank * 2 : 5;
  return score;
}

export function pickVoice(voices: VoiceLike[], target = "en"): VoiceLike | null {
  const usable = voices.filter((v) => scoreVoice(v, target) > -Infinity);
  if (!usable.length) return null;
  return usable.reduce((best, v) => (scoreVoice(v, target) > scoreVoice(best, target) ? v : best));
}

/** 把卡片上的书面写法改成能读出口的形式。
 *
 *  句型是**框架**,写出来带着给人看的记号:省略号表示"后面接你自己的内容"、
 *  斜杠表示"或者"、大写 X 是占位符。照着念会得到 "slash"、"ex" 和一串顿住的
 *  省略号,听起来就不是人话了。
 */
export function speechText(raw: string): string {
  return raw
    .replace(/\s*\/\s*/g, ", ")   // kind of / sort of → kind of, sort of
    .replace(/\bX\b/g, "someone")  // 占位符,否则读成字母 ex
    .replace(/[…]+/g, " ")          // 省略号只是"接着说"的记号,不发音
    .replace(/[()]/g, "")           // (just) in case → just in case
    .replace(/\s+/g, " ")
    .replace(/\s+([,.:;?!])/g, "$1")
    // 省略号开头的句型(…, to say the least.)清掉记号后会剩一个行首逗号。
    .replace(/^[\s,.:;]+/, "")
    .replace(/[\s,:;]+$/, "")
    .trim();
}

export function isSpeechSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

const cached: Record<string, SpeechSynthesisVoice | null> = {};

/** 预热。
 *
 *  ``getVoices()`` 在页面刚载入时返回**空数组**,语音表要等约 100 毫秒后由
 *  ``voiceschanged`` 送达。而人点得比这快:第一次点击时挑不到语音,
 *  ``utterance.voice`` 根本没被设置,浏览器只好拿一个兜底引擎去念——那就是
 *  "每天第一次朗读声音沙哑阴森"的来源。
 *
 *  所以在模块加载时就开始等,等人真正点下去时缓存早已就位。
 */
function warmUp(): void {
  if (!isSpeechSupported()) return;
  const fill = () => {
    const voices = window.speechSynthesis.getVoices();
    if (!voices.length) return;
    // 每次 voiceschanged 都重挑一遍,不是只补空缺:有的浏览器先给一份不完整的
    // 列表,照着它挑中的结果会被缓存一整个会话。
    for (const lang of Object.keys(FALLBACK_LANG)) {
      cached[lang] = (pickVoice(voices, lang) as SpeechSynthesisVoice | undefined) ?? null;
    }
  };
  fill();
  window.speechSynthesis.addEventListener("voiceschanged", fill);
}

function resolveVoice(lang: string): SpeechSynthesisVoice | null {
  if (lang in cached) return cached[lang];
  const voices = window.speechSynthesis.getVoices();
  // 还没就绪就不缓存,下次再试——缓存一个 null 会把这门语言永久钉死在兜底音上。
  if (!voices.length) return null;
  cached[lang] = (pickVoice(voices, lang) as SpeechSynthesisVoice | undefined) ?? null;
  return cached[lang];
}

const FALLBACK_LANG: Record<string, string> = { en: "en-US", nl: "nl-NL" };

/** 朗读一段外语。
 *
 *  **同步发起**:iOS Safari 只允许在用户手势内直接调用 ``speak``,放进 promise
 *  里会被拒。预热已经保证点击时语音表就位,所以这里不需要等。
 */
let primed = false;

/** 让系统语音引擎的冷启动发生在听不见的地方。
 *
 *  选好语音只解决了"挑错声音";引擎本身当天第一次被唤醒时,第一段话仍可能
 *  发闷或发抖。先推一段音量为零的占位,失真就落在这一段上。音量为零,所以
 *  没有任何可听见的代价。
 */
function prime(): void {
  if (primed) return;
  primed = true;
  const silent = new SpeechSynthesisUtterance(" ");
  silent.volume = 0;
  window.speechSynthesis.speak(silent);
}

export function speak(text: string, lang = "en", rate = 1): void {
  if (!isSpeechSupported()) return;
  const clean = speechText(text);
  if (!clean) return;

  // 只在确实有声音要打断时才 cancel。引擎还没热起来就调 cancel,是首次播放
  // 失真的另一个已知诱因。
  if (window.speechSynthesis.speaking || window.speechSynthesis.pending) {
    window.speechSynthesis.cancel();
  }
  prime();

  const utterance = new SpeechSynthesisUtterance(clean);
  const voice = resolveVoice(lang);
  if (voice) utterance.voice = voice;
  // 即使没挑到语音也要钉死语言,否则会用界面语言(中文)的语音去念外语。
  utterance.lang = voice?.lang || FALLBACK_LANG[lang] || lang;
  utterance.rate = rate;
  window.speechSynthesis.speak(utterance);
}

warmUp();

export function cancelSpeech(): void {
  if (isSpeechSupported()) window.speechSynthesis.cancel();
}
