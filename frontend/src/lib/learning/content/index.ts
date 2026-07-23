import type { KnowledgeCard, TopicId } from "../types";
import type { GeneratedCard } from "@/lib/api";
import { MARKET_CARDS } from "./market-mechanics";
import { PSYCHOLOGY_CARDS } from "./psychology";
import { TECHNICAL_CARDS } from "./technical";
import { QUANT_CARDS } from "./quant";
import { RISK_CARDS } from "./risk";
import { loadExtra, appendGeneratedCards, saveExtra, type ExtraByTopic } from "../extra-store";

const STATIC_BY_TOPIC: Record<TopicId, KnowledgeCard[]> = {
  market: MARKET_CARDS,
  technical: TECHNICAL_CARDS,
  quant: QUANT_CARDS,
  risk: RISK_CARDS,
  psychology: PSYCHOLOGY_CARDS,
};

// AI 扩充的卡片从 localStorage 载入,运行时合并在静态题库之后。
let _extra: ExtraByTopic = loadExtra();

function build(): Record<TopicId, KnowledgeCard[]> {
  const out = {} as Record<TopicId, KnowledgeCard[]>;
  (Object.keys(STATIC_BY_TOPIC) as TopicId[]).forEach((t) => {
    out[t] = [...STATIC_BY_TOPIC[t], ...(_extra[t] ?? [])];
  });
  return out;
}

// 以 let 导出,便于扩充后重建;ES 模块的实时绑定让引用方读到最新值。
export let CARDS_BY_TOPIC: Record<TopicId, KnowledgeCard[]> = build();
export let ALL_CARDS: KnowledgeCard[] = Object.values(CARDS_BY_TOPIC).flat();

let CARD_MAP = new Map(ALL_CARDS.map((c) => [c.id, c]));

function rebuild(): void {
  CARDS_BY_TOPIC = build();
  ALL_CARDS = Object.values(CARDS_BY_TOPIC).flat();
  CARD_MAP = new Map(ALL_CARDS.map((c) => [c.id, c]));
}

export function getCard(id: string): KnowledgeCard | undefined {
  return CARD_MAP.get(id);
}

/** 追加一批 AI 生成的卡片到某主题(持久化 + 重建合并视图),返回新增卡片。 */
export function addGeneratedCards(topicId: TopicId, generated: GeneratedCard[]): KnowledgeCard[] {
  const { next, added } = appendGeneratedCards(_extra, topicId, generated);
  _extra = next;
  rebuild();
  return added;
}

/** 用一份(通常是跨设备合并后的)完整 extra 覆盖当前值并持久化、重建。 */
export function setExtraCards(extra: ExtraByTopic): void {
  _extra = extra;
  saveExtra(_extra);
  rebuild();
}

/** 某主题已 AI 扩充的卡片数量。 */
export function extraCountForTopic(topicId: TopicId): number {
  return _extra[topicId]?.length ?? 0;
}
