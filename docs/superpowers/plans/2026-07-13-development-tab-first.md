# Development-First Analytics Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make “研发与版本” the first and default view of the Analytics page.

**Architecture:** Keep the existing `AnalyticsView` union and child views. Change only the initial React state and the four navigation buttons' render order, with a page-level regression test covering default content, order, and API behavior.

**Tech Stack:** React, TypeScript, Vitest, Testing Library

## Global Constraints

- Tab order is 研发与版本、功能使用、系统健康、研究质量.
- Default view is `development`; refresh does not persist the prior selection.
- The default period remains 30 days.
- Backend APIs and analytics calculations do not change.

---

### Task 1: Make development the primary Analytics view

**Files:**
- Modify: `frontend/src/pages/Analytics.tsx`
- Test: `frontend/src/pages/__tests__/Analytics.test.tsx`

**Interfaces:**
- Consumes: existing `AnalyticsView`, `DevelopmentView`, and analytics API methods.
- Produces: `Analytics` whose first/default view is `development`.

- [ ] **Step 1: Write the failing page test**

Mock `DevelopmentView` with a visible marker, then assert the initial view, Tab order, and absence of usage/system requests:

```tsx
vi.mock("@/components/analytics/DevelopmentView", () => ({
  DevelopmentView: () => <div>研发版本默认内容</div>,
}));

it("opens with development first and keeps analytics tabs in priority order", () => {
  render(<Analytics />);
  expect(screen.getByText("研发版本默认内容")).toBeInTheDocument();
  const tabNames = screen.getAllByRole("button")
    .map((button) => button.textContent)
    .filter((name) => ["研发与版本", "功能使用", "系统健康", "研究质量"].includes(name || ""));
  expect(tabNames).toEqual(["研发与版本", "功能使用", "系统健康", "研究质量"]);
  expect(apiMock.getAnalyticsUsage).not.toHaveBeenCalled();
  expect(apiMock.getAnalyticsSystemHealth).not.toHaveBeenCalled();
});
```

Update the existing switch test so it explicitly clicks `功能使用` before expecting usage metrics, then clicks `系统健康`.

- [ ] **Step 2: Run the test and verify the intended failure**

Run:

```bash
cd frontend && npm test -- --run src/pages/__tests__/Analytics.test.tsx
```

Expected: FAIL because the default content is not development and the Tab order still starts with 功能使用.

- [ ] **Step 3: Implement the minimal UI change**

In `Analytics.tsx`, set:

```tsx
const [view, setView] = useState<AnalyticsView>("development");
```

Render the existing development button before the usage, system, and research buttons; do not alter their handlers or styling.

- [ ] **Step 4: Verify page and full frontend tests**

Run:

```bash
cd frontend && npm test -- --run src/pages/__tests__/Analytics.test.tsx
npm test -- --run
npm run build
```

Expected: Analytics page tests pass, all frontend tests pass, and the production build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Analytics.tsx frontend/src/pages/__tests__/Analytics.test.tsx
git commit -m "feat: prioritize development analytics"
```
