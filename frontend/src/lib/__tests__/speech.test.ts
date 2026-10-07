import { describe, expect, it } from "vitest";
import { pickVoice, scoreVoice, speechText } from "@/lib/speech";

const v = (name: string, lang: string) => ({ name, lang });

// 这台开发机上 getVoices() 的真实返回顺序:前几个全是玩具语音。
const REAL_ORDER = [
  v("Daniel", "en-GB"), v("Albert", "en-US"), v("Bad News", "en-US"),
  v("Bahh", "en-US"), v("Bells", "en-US"), v("Boing", "en-US"),
  v("Bubbles", "en-US"), v("Cellos", "en-US"), v("Fred", "en-US"),
  v("Good News", "en-US"), v("Jester", "en-US"), v("Karen", "en-AU"),
  v("Moira", "en-IE"), v("Samantha", "en-US"), v("Trinoids", "en-US"),
  v("Zarvox", "en-US"), v("Ting-Ting", "zh-CN"),
];

describe("朗读选音", () => {
  it("不会挑中会发怪声的玩具语音", () => {
    // 直接取第一个 en-US 会得到 Albert,再往下是 Bad News、Boing——
    // 这些读出来没法用来跟读。
    const chosen = pickVoice(REAL_ORDER);

    expect(chosen?.name).toBe("Samantha");
  });

  it("每一个玩具语音的得分都低于任何正常语音", () => {
    const novelty = ["Bad News", "Bahh", "Boing", "Zarvox", "Trinoids", "Albert", "Fred"];
    const normal = scoreVoice(v("Moira", "en-IE"));

    for (const name of novelty) {
      expect(scoreVoice(v(name, "en-US"))).toBeLessThan(normal);
    }
  });

  it("绝不会挑中语言不对的语音", () => {
    expect(scoreVoice(v("Ting-Ting", "zh-CN"))).toBe(-Infinity);
    expect(pickVoice([v("Ting-Ting", "zh-CN"), v("Kyoko", "ja-JP")])).toBeNull();
  });

  it("荷兰语用荷兰语语音,不会退回英语", () => {
    // 用英语语音念荷兰语,发音会错得离谱——对语言学习者比不出声更糟。
    const voices = [v("Samantha", "en-US"), v("Xander", "nl-NL"), v("Ellen", "nl-BE")];

    expect(pickVoice(voices, "nl")?.name).toBe("Xander");
    expect(scoreVoice(v("Samantha", "en-US"), "nl")).toBe(-Infinity);
  });

  it("没有该语言的语音时返回空,而不是拿别的语言顶上", () => {
    expect(pickVoice([v("Samantha", "en-US")], "nl")).toBeNull();
  });

  it("同为荷兰语时偏好荷兰口音而不是比利时口音", () => {
    expect(scoreVoice(v("Xander", "nl-NL"), "nl")).toBeGreaterThan(
      scoreVoice(v("Xander", "nl-BE"), "nl"),
    );
  });

  it("在 Chrome 上挑 Google 的英语语音", () => {
    const chosen = pickVoice([
      v("Google Deutsch", "de-DE"),
      v("Google US English", "en-US"),
      v("Google UK English Female", "en-GB"),
    ]);

    expect(chosen?.name).toBe("Google US English");
  });

  it("名字里带 Siri 或 Enhanced 的新语音优先于普通语音", () => {
    expect(scoreVoice(v("Siri Voice 1", "en-US"))).toBeGreaterThan(
      scoreVoice(v("Shelley (English (United States))", "en-US")),
    );
  });

  it("没有首选名单里的语音时,仍然挑一个正常的英语语音", () => {
    const chosen = pickVoice([v("Zarvox", "en-US"), v("Shelley", "en-US")]);

    expect(chosen?.name).toBe("Shelley");
  });

  it("只剩玩具语音时宁可出声也不沉默", () => {
    expect(pickVoice([v("Zarvox", "en-US")])?.name).toBe("Zarvox");
  });

  it("同为首选时偏好美音", () => {
    expect(scoreVoice(v("Samantha", "en-US"))).toBeGreaterThan(scoreVoice(v("Samantha", "en-AU")));
  });
});

describe("朗读文本清洗", () => {
  it("省略号不发音", () => {
    // 省略号只是"后面接你自己的内容"的记号。
    expect(speechText("I was wondering if …")).toBe("I was wondering if");
    // 省略号在句首时,清掉记号别留下一个孤零零的逗号。
    expect(speechText("…, to say the least.")).toBe("to say the least.");
  });

  it("斜杠读成停顿而不是 slash", () => {
    expect(speechText("kind of / sort of …")).toBe("kind of, sort of");
  });

  it("占位符 X 不会被读成字母", () => {
    expect(speechText("What I like about X is …")).toBe("What I like about someone is");
    expect(speechText("Knowing X, …")).toBe("Knowing someone");
  });

  it("括号里的词照读,括号本身不读", () => {
    expect(speechText("(just) in case …")).toBe("just in case");
  });

  it("保留正常的句末标点", () => {
    expect(speechText("Does that make sense?")).toBe("Does that make sense?");
    expect(speechText("I'm fine either way.")).toBe("I'm fine either way.");
  });

  it("完整例句原样不动", () => {
    const example = "I was wondering if you could take a look at this.";
    expect(speechText(example)).toBe(example);
  });

  it("只剩记号的文本清洗后为空,不会去念", () => {
    expect(speechText("… / …")).toBe("");
  });
});
