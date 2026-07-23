/** 量化学习:内容与进度的类型定义。
 *
 * 卡片 id 必须是稳定的字符串 slug(如 "market-slippage"),进度以 id 为键
 * 持久化在 localStorage —— 增删改卡片时绝不能复用或改变已有 id。
 */

export type TopicId = "market" | "technical" | "quant" | "risk" | "psychology";

export type CardType = "concept" | "story" | "pitfall";

export interface QuizQuestion {
  /** choice=选择题 judge=判断改错 scenario=情景题 */
  type: "choice" | "judge" | "scenario";
  question: string;
  options: string[];
  /** 正确选项下标 */
  answer: number;
  explanation: string;
}

export interface PracticeLink {
  label: string;
  to: string;
}

export interface KnowledgeCard {
  id: string;
  topicId: TopicId;
  type: CardType;
  /** 1=入门 2=进阶 3=高阶 */
  difficulty: 1 | 2 | 3;
  title: string;
  /** 核心讲解:把"为什么"讲透,2-4 句 */
  core: string;
  /** 例子或真实市场故事 */
  example?: string;
  /** 常见误区:"很多人以为…其实…" */
  pitfall?: string;
  /** 跳转到 app 内页面,用自己的数据验证 */
  practiceLink?: PracticeLink;
  relatedIds?: string[];
  quiz: QuizQuestion;
  /** 主题压轴卡 */
  capstone?: boolean;
  /** 由 AI 现场扩充生成(区别于内置题库) */
  aiGenerated?: boolean;
}

export interface Topic {
  id: TopicId;
  title: string;
  subtitle: string;
  /** 内容尚未制作完成的主题在 UI 中显示"制作中" */
  status: "available" | "coming";
}
