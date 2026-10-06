"""英语口语的 100 个高频句型(chunks)。

目标不是"认识",而是**调用自动化**:交流时不经过翻译就能脱口而出。所以每条
都带一个中文情境提示(``cue``),练习时只给提示、不给英文,逼着自己先产出。

选型标准:

* 口语对话里真实高频,不是书面语或考试腔;
* 是**框架**而不是整句——填进自己的内容就能用;
* 承担具体的交际功能(缓和、让步、叙述、组织话语……),按功能分组,
  方便在真实对话里按"我现在想干什么"检索,而不是按字母表检索。

内容是人工挑选的固定清单,不走模型生成:间隔重复需要稳定的 ID,内容一旦
每次生成都不同,复习进度就无从谈起。
"""

from __future__ import annotations

from dataclasses import dataclass

#: 难度级别。新句型按这个顺序引入:先把基础的练顺,再往上加。
LEVELS = {"core": "基础", "mid": "中级", "high": "高级"}

#: 三条并列的训练线,失败方式各不相同,所以进度分开统计:
#:
#: * **句型**要接自己的内容,用错只是话接不顺;
#: * **整句**拿来即用,不会就是接不上话;
#: * **搭配**嵌在句子里,用错语法完全正确,但一听就不是母语者。
TRACKS = {"frame": "句型", "oneliner": "整句", "collocation": "搭配"}

#: 分组按交际功能,但**每条线的功能不一样**:句型/整句是按"我现在想干什么"
#: 分的,搭配是按"我在说哪件事"分的。共用一张表会让搭配顶着句型的标签。
_TALK_GROUPS = {
    "A": "缓和与委婉",
    "B": "观点与立场",
    "C": "解释与澄清",
    "D": "叙述与经历",
    "E": "转折与让步",
    "F": "条件与推测",
    "G": "互动与回应",
    "H": "话语组织",
}

_SCENE_GROUPS = {
    "A": "日常起居",
    "B": "时间与安排",
    "C": "工作与协作",
    "D": "沟通与社交",
    "E": "想法与决定",
    "F": "问题与麻烦",
    "G": "学习与进步",
    "H": "身体与状态",
    # 动作词是"不地道"最明显的地方:中文一个"拿"对应 take / grab / pick up /
    # carry,一个"撞"对应 bump into / knock over / crash into。
    "I": "手上的动作",
    "J": "碰撞与身体",
}

GROUPS = {
    "frame": _TALK_GROUPS,
    "oneliner": _TALK_GROUPS,
    "collocation": _SCENE_GROUPS,
}


@dataclass(frozen=True)
class Pattern:
    id: str
    frame: str
    group: str
    level: str
    meaning: str
    #: 中文情境提示。练习时只显示这个,英文要自己产出。
    cue: str
    examples: tuple[str, ...]
    track: str = "frame"
    #: 中式英语的直译版,用作测验干扰项。只有搭配才有。
    wrong: tuple[str, ...] = ()

    @property
    def group_label(self) -> str:
        return GROUPS[self.track][self.group]

    @property
    def level_label(self) -> str:
        return LEVELS[self.level]

    @property
    def track_label(self) -> str:
        return TRACKS[self.track]

    def to_dict(self) -> dict:
        return {
            "id": self.id, "frame": self.frame, "group": self.group,
            "group_label": self.group_label, "level": self.level,
            "level_label": self.level_label, "meaning": self.meaning,
            "cue": self.cue, "examples": list(self.examples),
            "track": self.track, "track_label": self.track_label,
        }


_RAW: tuple[tuple, ...] = (
    # ── A 缓和与委婉 ──────────────────────────────────────────────────────────
    ("wondering-if", "I was wondering if …", "A", "我在想能不能……(英语里最客气的提请求方式)",
     "想请同事抽空帮你看一眼方案,用最客气的说法开口。",
     ("I was wondering if you could take a look at this.",
      "I was wondering if we could push it to Friday.")),
    ("would-it-be-possible", "Would it be possible to …", "A", "有没有可能……(比直接问更软)",
     "想问能不能改个时间,但不想显得理所当然。",
     ("Would it be possible to reschedule?",
      "Would it be possible to get that by Monday?")),
    ("id-say", "I'd say …", "A", "我觉得……(弱化断言,留余地)",
     "别人问你这个要花多久,你不确定但要给个数。",
     ("I'd say it'll take about two weeks.",
      "I'd say that's the main reason.")),
    ("kind-of", "kind of / sort of …", "A", "有点……(把话说软)",
     "你觉得那家店一般般,但不想说得太重。",
     ("It was kind of disappointing.",
      "I'm sort of busy right now.")),
    ("not-sure-but", "I'm not sure, but …", "A", "我不太确定,不过……",
     "你记得个大概但没把握,先声明再说。",
     ("I'm not sure, but I think it starts at nine.",
      "I'm not sure, but it might be closed today.")),
    ("might-just-be-me", "It might just be me, but …", "A", "可能只有我这么觉得,不过……",
     "你要提一个可能别人不认同的感受。",
     ("It might just be me, but that feels too expensive.",
      "It might just be me, but the pacing felt off.")),
    ("mind-me-asking", "If you don't mind me asking, …", "A", "如果不介意我问一句……",
     "想问一个稍微私人的问题,先铺垫一下。",
     ("If you don't mind me asking, how long have you been here?",
      "If you don't mind me asking, what made you switch?")),
    ("dont-mean-to", "I don't mean to …, but …", "A", "我不是想……,只是……",
     "你要打断别人,但不想显得没礼貌。",
     ("I don't mean to interrupt, but we're running out of time.",
      "I don't mean to be difficult, but this doesn't add up.")),
    ("correct-me", "Correct me if I'm wrong, but …", "A", "我可能记错,但……",
     "你要指出对方可能有问题的地方,先给自己留台阶。",
     ("Correct me if I'm wrong, but didn't we agree on Thursday?",
      "Correct me if I'm wrong, but that's not what the data shows.")),
    ("to-be-honest", "To be honest, …", "A", "老实说……(引出实话,略带保留)",
     "对方问你觉得怎么样,你要说实话但不想太冲。",
     ("To be honest, I didn't really enjoy it.",
      "To be honest, I'd rather stay in tonight.")),
    ("i-guess", "I guess …", "A", "我猜/应该吧(不太确定,也不想争)",
     "你半信半疑地接受了对方的说法。",
     ("I guess that makes sense.",
      "I guess we'll find out tomorrow.")),
    ("more-or-less", "more or less", "A", "差不多;大体上",
     "事情基本搞定了,但还有点尾巴。",
     ("It's more or less done.",
      "That's more or less what I had in mind.")),
    ("wouldnt-say", "I wouldn't say …", "A", "我不会说……(委婉否定对方的措辞)",
     "对方用了一个过重的词形容某件事,你要纠正语气。",
     ("I wouldn't say it was a failure — it just needs more work.",
      "I wouldn't say I'm an expert, but I've done a few.")),

    # ── B 观点与立场 ──────────────────────────────────────────────────────────
    ("the-way-i-see-it", "The way I see it, …", "B", "在我看来……(引出自己的判断)",
     "讨论到一半,你要给出自己的整体看法。",
     ("The way I see it, we only have two options.",
      "The way I see it, it's not worth the risk.")),
    ("personally", "Personally, I …", "B", "就我个人而言……",
     "大家意见不一,你要把自己的偏好单独标出来。",
     ("Personally, I'd go with the second one.",
      "Personally, I don't mind either way.")),
    ("not-really-into", "I'm not really into …", "B", "我对……不太感冒",
     "朋友约你去看某类电影,你没什么兴趣但不想扫兴。",
     ("I'm not really into horror movies.",
      "I'm not really into crowds.")),
    ("big-fan-of", "I'm a big fan of …", "B", "我很喜欢……",
     "聊到一个你很喜欢的东西,要表达得地道一点。",
     ("I'm a big fan of their earlier work.",
      "I'm not a big fan of meetings.")),
    ("what-i-like-about", "What I like about X is …", "B", "我喜欢某样东西的地方在于……",
     "你要具体说出喜欢某样东西的原因,而不是只说一句「很好」。",
     ("What I like about this place is how quiet it is.",
      "What I like about him is that he's straightforward.")),
    ("id-rather", "I'd rather …", "B", "我宁愿……",
     "两个选项里你明显偏向一个。",
     ("I'd rather not talk about it.",
      "I'd rather walk than wait for the bus.")),
    ("fine-either-way", "I'm fine either way.", "B", "我都行(真的没偏好)",
     "对方让你选,你确实无所谓。",
     ("I'm fine either way — you pick.",
      "Either way works for me.")),
    ("not-my-thing", "It's not really my thing.", "B", "不太是我的菜",
     "你想礼貌地表示没兴趣,不带评判。",
     ("Golf's not really my thing.",
      "Clubbing was never my thing.")),
    ("can-see-why", "I can see why …", "B", "我能理解为什么……(先共情再表态)",
     "你不同意对方,但要先承认他的角度说得通。",
     ("I can see why you'd think that.",
      "I can see why they're upset.")),
    ("torn-between", "I'm torn between …", "B", "我在……之间很纠结",
     "两个都想要,一时决定不下来。",
     ("I'm torn between the two.",
      "I'm torn between staying and going home.")),
    ("if-anything", "If anything, …", "B", "要说有什么的话,反而……",
     "对方说某事太多了,你觉得恰恰相反。",
     ("If anything, it's too quiet.",
      "If anything, that made it better.")),
    ("all-for", "I'm all for …", "B", "我完全支持……",
     "有人提了个你很赞成的主意。",
     ("I'm all for trying something new.",
      "I'm all for it, as long as it's quick.")),
    ("mixed-feelings", "I have mixed feelings about …", "B", "我对……感觉挺复杂",
     "某件事有好有坏,你一句话说不清。",
     ("I have mixed feelings about moving.",
      "I have mixed feelings about the ending.")),

    # ── C 解释与澄清 ──────────────────────────────────────────────────────────
    ("the-thing-is", "The thing is, …", "C", "问题在于……(引出关键的那个障碍)",
     "你想答应对方,但有个绕不开的问题要先说。",
     ("The thing is, I already promised someone else.",
      "The thing is, we don't have the budget for it.")),
    ("what-i-mean-is", "What I mean is …", "C", "我的意思是……(重说一遍)",
     "对方听岔了,你要换个说法解释。",
     ("What I mean is, it's not urgent — just important.",
      "What I mean is, we should wait a bit.")),
    ("put-it-this-way", "Let me put it this way: …", "C", "我这么说吧……",
     "直说会太难听,你要换个角度把意思传到。",
     ("Let me put it this way: I wouldn't do it again.",
      "Let me put it this way: it could have gone better.")),
    ("in-other-words", "In other words, …", "C", "换句话说……",
     "你要把刚说的一长串总结成一句。",
     ("In other words, we're back where we started.",
      "In other words, it's a no.")),
    ("the-point-is", "The point is, …", "C", "重点是……(把话题拉回来)",
     "讨论跑偏了,你要把关键拎出来。",
     ("The point is, we need to decide today.",
      "The point is, nobody told us.")),
    ("not-what-i-meant", "That's not what I meant.", "C", "我不是那个意思",
     "对方误解了你的话,你要立刻澄清。",
     ("That's not what I meant at all.",
      "That's not quite what I meant.")),
    ("basically", "Basically, …", "C", "基本上就是……(简化一个复杂的事)",
     "你要用一句话概括一件挺复杂的事。",
     ("Basically, it does the same thing but faster.",
      "Basically, we ran out of time.")),
    ("its-just-that", "It's just that …", "C", "只是说……(解释顾虑)",
     "你要拒绝但得说明原因,语气放软。",
     ("It's just that I've got a lot on right now.",
      "It's just that I'm not sure it's the right time.")),
    ("give-you-an-example", "To give you an example, …", "C", "举个例子……",
     "你刚讲完一个抽象的点,要落地。",
     ("To give you an example, last week took three days.",
      "To give you an example, my sister did exactly that.")),
    ("trying-to-say", "What I'm trying to say is …", "C", "我想说的是……",
     "你说了一堆没说到点上,要收回来。",
     ("What I'm trying to say is, it's not about the money.",
      "What I'm trying to say is, we should slow down.")),
    ("make-sense", "Does that make sense?", "C", "这样说清楚了吗?(把球递回去)",
     "你解释完一件复杂的事,想确认对方跟上了。",
     ("Does that make sense, or should I go over it again?",
      "Let me know if that doesn't make sense.")),
    ("long-story-short", "Long story short, …", "C", "长话短说……",
     "事情经过很长,你要跳到结果。",
     ("Long story short, we missed the flight.",
      "Long story short, it worked out.")),
    ("comes-down-to", "It comes down to …", "C", "归根结底是……",
     "绕了半天,你要指出真正的决定因素。",
     ("It all comes down to timing.",
      "It comes down to how much you're willing to spend.")),

    # ── D 叙述与经历 ──────────────────────────────────────────────────────────
    ("ended-up", "I ended up …", "D", "结果我就……(事情和原计划不一样)",
     "本来打算早点走,结果没走成。",
     ("I ended up staying until midnight.",
      "We ended up taking a taxi.")),
    ("it-turns-out", "It turns out …", "D", "结果发现……(和原先以为的不一样)",
     "你本来以为是一回事,后来发现不是。",
     ("It turns out he was right all along.",
      "It turns out the shop was closed.")),
    ("about-to-when", "I was about to … when …", "D", "我正要……结果……",
     "你刚准备做某事就被打断了。",
     ("I was about to leave when she called.",
      "I was about to say the same thing.")),
    ("used-to", "I used to …", "D", "我以前常常……(现在不了)",
     "讲一个已经改变的旧习惯。",
     ("I used to play a lot when I was younger.",
      "I used to live right around the corner.")),
    ("been-meaning-to", "I've been meaning to …", "D", "我一直想着要……(但一直没做)",
     "有件事你惦记很久了,始终没动手。",
     ("I've been meaning to call you.",
      "I've been meaning to get that fixed.")),
    ("took-me-a-while", "It took me a while to …", "D", "我花了好一阵才……",
     "某件事你不是一下子就上手的。",
     ("It took me a while to get used to it.",
      "It took me a while to figure out what he meant.")),
    ("happened-to", "I happened to …", "D", "我碰巧……",
     "一件纯属巧合的事。",
     ("I happened to be in the area.",
      "I happened to run into her yesterday.")),
    ("next-thing-i-knew", "Next thing I knew, …", "D", "我还没反应过来就……",
     "事情发展得太快,你来不及反应。",
     ("Next thing I knew, everyone had left.",
      "Next thing I knew, it was three in the morning.")),
    ("one-thing-led", "One thing led to another, and …", "D", "一来二去,就……",
     "小事一件接一件,最后变成大事。",
     ("One thing led to another, and we ended up starting a company.",
      "One thing led to another, and I missed the last train.")),
    ("id-just-when", "I'd just … when …", "D", "我刚……就……",
     "你刚做完一件事,另一件事就发生了。",
     ("I'd just sat down when the phone rang.",
      "I'd just got home when it started raining.")),
    ("thats-when", "That's when I realized …", "D", "就是那时候我才意识到……",
     "讲到故事的转折点。",
     ("That's when I realized I'd left my keys inside.",
      "That's when it hit me.")),
    ("ran-into", "I ran into …", "D", "我偶然碰到……",
     "路上撞见一个熟人。",
     ("I ran into an old classmate at the station.",
      "We ran into some trouble with the setup.")),
    ("getting-used-to", "I'm still getting used to …", "D", "我还在适应……",
     "新环境、新工作,你还没完全习惯。",
     ("I'm still getting used to the weather here.",
      "I'm still getting used to the new system.")),
    # ── E 转折与让步 ──────────────────────────────────────────────────────────
    ("that-said", "That said, …", "E", "话虽如此……(前面认同,后面转折)",
     "你刚承认了对方有道理,现在要提出保留意见。",
     ("That said, I still think it's too risky.",
      "That said, it's not the end of the world.")),
    ("then-again", "Then again, …", "E", "不过话说回来……(自己推翻自己)",
     "你刚说完一个判断,又想到了反面。",
     ("Then again, maybe I'm overthinking it.",
      "Then again, nobody's complained so far.")),
    ("having-said-that", "Having said that, …", "E", "虽然这么说……",
     "你要在肯定之后加一个转折,语气比最普通的那个连词正式一点。",
     ("Having said that, I'd still double-check.",
      "Having said that, it's not a deal-breaker.")),
    ("to-be-fair", "To be fair, …", "E", "平心而论……(替对方说句公道话)",
     "大家在抱怨某人,你要指出他也有难处。",
     ("To be fair, he wasn't told either.",
      "To be fair, it was a tough call.")),
    ("still", "Still, …", "E", "不过还是……",
     "理由都成立,但你心里那关还是过不去。",
     ("Still, I'd feel better if we asked first.",
      "Still, it's worth a try.")),
    ("even-so", "Even so, …", "E", "即便如此……",
     "对方的解释你接受了,但结论不变。",
     ("Even so, we can't afford to wait.",
      "Even so, I wouldn't count on it.")),
    ("not-that-its-just", "It's not that …, it's just …", "E", "不是说……,只是……",
     "你要澄清一个被误会的态度。",
     ("It's not that I don't want to, it's just bad timing.",
      "It's not that it's hard, it's just tedious.")),
    ("on-the-one-hand", "On the one hand … on the other hand …", "E", "一方面……另一方面……",
     "一件事有明显的利弊两面。",
     ("On the one hand it's cheaper, on the other hand it takes longer.",
      "On the one hand I'm relieved, on the other I'm a bit sad.")),
    ("see-your-point", "I see your point, but …", "E", "我明白你的意思,但……",
     "不同意对方,但要先给足面子。",
     ("I see your point, but the timing doesn't work.",
      "I see your point, but that's not what we agreed.")),
    ("fair-enough-but", "Fair enough, but …", "E", "有道理,不过……",
     "对方说得通,你还有个条件。",
     ("Fair enough, but let's set a deadline.",
      "Fair enough, but someone has to tell them.")),
    ("not-that-it-matters", "Not that it matters, but …", "E", "虽然无所谓,不过……",
     "你要补一句不影响大局的小信息。",
     ("Not that it matters, but I was there too.",
      "Not that it matters now, but I did warn them.")),
    ("whether-or-not", "Whether or not …", "E", "不管是不是……",
     "无论某个条件成不成立,结果都一样。",
     ("Whether or not he agrees, we're doing it.",
      "Whether or not it rains, the event is on.")),

    # ── F 条件与推测 ──────────────────────────────────────────────────────────
    ("it-depends-on", "It depends on …", "F", "取决于……(拒绝给出绝对答案)",
     "对方问你行不行,而答案要看情况。",
     ("It depends on how much time we have.",
      "It depends — are we driving or flying?")),
    ("as-far-as-i-know", "As far as I know, …", "F", "据我所知……(给信息但不打包票)",
     "你知道个大概,但不想为准确性负全责。",
     ("As far as I know, nothing's changed.",
      "As far as I know, she's still on holiday.")),
    ("chances-are", "Chances are …", "F", "很可能……",
     "你要给一个大概率的推测。",
     ("Chances are they've already left.",
      "Chances are it'll sell out.")),
    ("in-case", "(just) in case …", "F", "以防……",
     "做一件预防性的准备。",
     ("Bring an umbrella, just in case.",
      "I'll write it down in case I forget.")),
    ("as-long-as", "As long as …", "F", "只要……就……",
     "你同意,但附带一个条件。",
     ("As long as we're back by six, it's fine.",
      "As long as you tell me in advance.")),
    ("unless", "Unless …", "F", "除非……",
     "除了一个例外情况,其余都成立。",
     ("I'll be there, unless something comes up.",
      "Unless you'd rather not.")),
    ("if-i-were-you", "If I were you, I'd …", "F", "如果我是你,我会……",
     "朋友问你建议,你要给但不想太强势。",
     ("If I were you, I'd sleep on it.",
      "If I were you, I'd ask first.")),
    ("supposing", "Supposing …", "F", "假设……(提一个假想情况)",
     "你要拉对方一起推演一个假设场景。",
     ("Supposing it doesn't work, what then?",
      "Supposing we start now — how long would it take?")),
    ("theres-a-chance", "There's a chance (that) …", "F", "有可能……",
     "一件事还没定,但有希望。",
     ("There's a chance I'll be late.",
      "There's a good chance it'll be fine.")),
    ("bound-to", "It's bound to …", "F", "一定会……(几乎必然)",
     "你要说某件事迟早会发生。",
     ("It's bound to happen sooner or later.",
      "They're bound to notice.")),
    ("knowing-x", "Knowing X, …", "F", "以某人的性格,肯定……",
     "根据对某人的了解做预测。",
     ("Knowing him, he'll be twenty minutes late.",
      "Knowing my luck, it'll rain.")),
    ("either-way", "Either way, …", "F", "不管怎样……",
     "两种情况下结论都一样。",
     ("Either way, we need to let them know.",
      "Either way, I'm fine with it.")),

    # ── G 互动与回应 ──────────────────────────────────────────────────────────
    ("makes-sense", "That makes sense.", "G", "有道理(表示听懂并认同)",
     "对方解释完,你要给一个自然的回应。",
     ("That makes sense, thanks.",
      "Ah, that makes sense now.")),
    ("know-what-you-mean", "I know what you mean.", "G", "我懂你的意思(共情)",
     "对方讲了一个处境,你有同感。",
     ("I know what you mean — same here.",
      "I know exactly what you mean.")),
    ("same-here", "Same here.", "G", "我也是",
     "对方说的正好也是你的情况。",
     ("Same here, I barely slept.",
      "Same here — let's skip it.")),
    ("good-point", "Good point.", "G", "说得好(认可一个你没想到的点)",
     "对方提了个你没考虑到的角度。",
     ("Good point, I hadn't thought of that.",
      "That's a good point.")),
    ("fair-point", "Fair point.", "G", "有道理(勉强认同)",
     "你本来不同意,但对方这句说服了你。",
     ("Fair point, let's do it your way.",
      "Fair point — I'll look into it.")),
    ("not-following", "I'm not following.", "G", "我没跟上(请对方再说一遍)",
     "对方讲得太快或太绕,你没懂。",
     ("Sorry, I'm not following — can you back up?",
      "I'm not quite following you.")),
    ("you-were-saying", "Sorry, you were saying?", "G", "抱歉,你刚才说?",
     "你走神了或被打断,要请对方继续。",
     ("Sorry, you were saying? I got distracted.",
      "Go on, you were saying.")),
    ("hang-on", "Hang on a second.", "G", "等一下(争取几秒钟)",
     "你需要短暂打断,去确认一件事。",
     ("Hang on a second, let me check.",
      "Hang on — say that again?")),
    ("get-back-to-you", "Let me get back to you on that.", "G", "这个我回头答复你",
     "你现在答不上来,但不想说不知道。",
     ("Let me get back to you on that tomorrow.",
      "I'll get back to you once I know more.")),
    ("good-question", "That's a good question.", "G", "这问题问得好(顺便给自己争取时间)",
     "被问到一个需要想一下的问题。",
     ("That's a good question — I'm not sure, actually.",
      "That's a really good question.")),
    ("no-worries", "No worries.", "G", "没事(轻松化解对方的歉意)",
     "对方为一件小事道歉。",
     ("No worries, it happens.",
      "No worries at all.")),
    ("up-to-you", "It's up to you.", "G", "你决定",
     "你把选择权交给对方。",
     ("It's totally up to you.",
      "Up to you — I don't mind.")),

    # ── H 话语组织 ────────────────────────────────────────────────────────────
    ("speaking-of-which", "Speaking of which, …", "H", "说到这个……(顺势换话题)",
     "对方提到的东西刚好让你想起一件事。",
     ("Speaking of which, did you ever hear back?",
      "Speaking of which, I need to book mine.")),
    ("by-the-way", "By the way, …", "H", "顺便说一下……",
     "想插入一件不相干但该说的事。",
     ("By the way, I'll be out on Friday.",
      "By the way, thanks for sending that.")),
    ("anyway", "Anyway, …", "H", "总之……(把跑偏的话题收回来)",
     "聊远了,你要拉回正题。",
     ("Anyway, where were we?",
      "Anyway, that's the plan.")),
    ("first-of-all", "First of all, …", "H", "首先……(明确开始列点)",
     "你要分条讲几件事。",
     ("First of all, thanks for coming.",
      "First of all, that's not what happened.")),
    ("the-other-thing", "The other thing is …", "H", "还有一件事……",
     "你刚说完一点,还有第二点要补。",
     ("The other thing is, we're short on time.",
      "The other thing is the cost.")),
    ("which-reminds-me", "Which reminds me, …", "H", "这倒提醒我了……",
     "说着说着忽然想起一件要紧事。",
     ("Which reminds me, I owe you money.",
      "Which reminds me — did you call them?")),
    ("going-back-to", "Going back to what you said, …", "H", "回到你刚才说的……",
     "你想重新接上前面的话头。",
     ("Going back to what you said earlier, I think you're right.",
      "Going back to the budget for a second…")),
    ("to-wrap-up", "To wrap up, …", "H", "最后总结一下……",
     "讨论要结束了,你来收口。",
     ("To wrap up, we'll go with option B.",
      "Just to wrap up — everyone clear on next steps?")),
    ("where-was-i", "Where was I?", "H", "我说到哪了?",
     "你被打断之后要找回自己的话头。",
     ("Sorry, where was I?",
      "Now, where was I…")),
    ("just-so-you-know", "Just so you know, …", "H", "跟你说一声……(预先告知)",
     "有件事对方应该知道,虽然不用他做什么。",
     ("Just so you know, the deadline moved.",
      "Just so you know, I won't be around next week.")),
    ("for-what-its-worth", "For what it's worth, …", "H", "不管有没有用,我想说……",
     "你要给一个不一定被采纳的意见。",
     ("For what it's worth, I thought you handled it well.",
      "For what it's worth, I'd go for the first one.")),
    ("lets-just-say", "Let's just say …", "H", "这么说吧……(点到为止)",
     "细节不方便讲,你要含糊但传神地带过。",
     ("Let's just say it didn't go well.",
      "Let's just say I won't be going back.")),
)


from src.growth.english_collocations import _RAW_ACTIONS, _RAW_COLLOCATIONS  # noqa: E402
from src.growth.english_oneliners import _RAW_ONELINERS  # noqa: E402
from src.growth.english_patterns_more import _RAW_HIGH, _RAW_MID  # noqa: E402


def _track_of(frame: str) -> str:
    """省略号就是分界:有空位要填的是句型,没有的本身就是一句完整的话。

    原来那 200 条里有 48 条属于后者(``That makes sense.``、``No worries.``),
    一直混在句型里。按这条规则自动归位,id 不变,练习进度照旧。
    """
    return "frame" if "…" in frame else "oneliner"


def _build(raw: tuple[tuple, ...], level: str) -> list[Pattern]:
    return [
        Pattern(id=i, frame=f, group=g, level=level, meaning=m, cue=c,
                examples=tuple(e), track=_track_of(f))
        for i, f, g, m, c, e in raw
    ]


def _build_oneliners(raw: tuple[tuple, ...]) -> list[Pattern]:
    return [
        Pattern(id=i, frame=f, group=g, level=lv, meaning=m, cue=c,
                examples=tuple(e), track="oneliner")
        for i, f, g, lv, m, c, e in raw
    ]


def _build_collocations(raw: tuple[tuple, ...]) -> list[Pattern]:
    """搭配自带难度,也自带中式英语的错误版。

    """
    return [
        Pattern(id=i, frame=f, group=g, level=lv, meaning=m, cue=c,
                examples=tuple(e), track="collocation", wrong=tuple(w))
        for i, f, g, lv, m, c, e, w in raw
    ]


_ALL = (
    _build(_RAW, "core") + _build(_RAW_MID, "mid") + _build(_RAW_HIGH, "high")
    + _build_oneliners(_RAW_ONELINERS)
    + _build_collocations(_RAW_COLLOCATIONS + _RAW_ACTIONS)
)

#: 每条线内部按难度排序。清单顺序就是引入顺序,不排的话第一天就会撞上高级内容;
#: 整句那条线尤其需要——它由两批来源拼成(迁移过来的 + 新写的),天然是乱的。
_LEVEL_ORDER = list(LEVELS)
PATTERNS_BY_TRACK: dict[str, tuple[Pattern, ...]] = {
    track: tuple(sorted((p for p in _ALL if p.track == track),
                        key=lambda p: _LEVEL_ORDER.index(p.level)))
    for track in TRACKS
}

PATTERNS: tuple[Pattern, ...] = tuple(
    p for track in TRACKS for p in PATTERNS_BY_TRACK[track]
)
PATTERN_BY_ID = {p.id: p for p in PATTERNS}
TOTAL = len(PATTERNS)
TRACK_TOTALS = {track: len(items) for track, items in PATTERNS_BY_TRACK.items()}
LEVEL_TOTALS = {
    track: {key: sum(1 for p in items if p.level == key) for key in LEVELS}
    for track, items in PATTERNS_BY_TRACK.items()
}
