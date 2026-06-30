# 今日机会列表折叠 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 今日机会默认显示前三名，并允许用户展开全部或重新收起。

**Architecture:** 保留后端返回的完整排序结果，在 `TodayOpportunities` 内通过本地布尔状态切片显示。筛选发生变化时恢复收起状态，详情加载逻辑保持不变。

**Tech Stack:** React 19、TypeScript、Vitest、Testing Library、Lucide React。

## Global Constraints

- 不改变 API、后端排序或评分逻辑。
- 结果不超过三只时不显示展开控制。
- 不增加前端依赖。

---

### Task 1: 折叠今日机会列表

**Files:**
- Modify: `frontend/src/components/opportunities/TodayOpportunities.tsx`
- Test: `frontend/src/components/opportunities/__tests__/TodayOpportunities.test.tsx`

**Interfaces:**
- Consumes: `OpportunityList.items` 已排序数组。
- Produces: 本地 `showAll` 状态、前三名 `visibleItems` 和“查看其余 N 只/收起”按钮。

- [ ] **Step 1: 写失败测试**

构造四只股票，断言默认只能看到前三只；点击“查看其余 1 只”后第四只出现；点击“收起”后第四只消失。另用三只股票断言不出现展开按钮。

- [ ] **Step 2: 运行测试确认失败**

Run: `npm --prefix frontend run test:run -- src/components/opportunities/__tests__/TodayOpportunities.test.tsx`

Expected: 第四只默认仍可见，且找不到“查看其余 1 只”按钮。

- [ ] **Step 3: 最小实现**

在组件中增加 `showAll`，以 `items.slice(0, 3)` 生成默认列表；仅在 `items.length > 3` 时渲染带 Chevron 图标的切换按钮。筛选变化时调用 `setShowAll(false)`。

- [ ] **Step 4: 验证测试和构建**

Run: `npm --prefix frontend run test:run -- src/components/opportunities src/components/layout/__tests__/Layout.test.tsx src/lib/__tests__/apiAuth.test.ts`

Run: `npm --prefix frontend run build`

Expected: 所有测试和生产构建通过。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/opportunities/TodayOpportunities.tsx frontend/src/components/opportunities/__tests__/TodayOpportunities.test.tsx
git commit -m "feat: collapse opportunity list to top three"
```
