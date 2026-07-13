# Analytics Development and Release Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add canonical application versioning, recent feature/commit trends, code-change summaries, and release-window metric comparisons.

**Architecture:** A read-only Git adapter executes fixed local commands with timeouts and parses machine-delimited output into development events. Deterministic rules group adjacent commits into user-readable features; release tags become timeline markers, and the service joins those markers to existing daily aggregates without claiming causality.

**Tech Stack:** Python stdlib `subprocess`/`pathlib`, Git CLI, existing analytics store/service, Vite, React, TypeScript, ECharts, pytest, Vitest.

## Global Constraints

- Complete the foundation plan before this plan; research-quality metrics may be absent and must remain optional.
- `frontend/package.json` is the sole application-version source.
- Only Git tags matching `v[0-9]+.[0-9]+.[0-9]+` define releases; ordinary commits remain development events.
- Git access is local and read-only, with fixed arguments, a 3-second timeout, and no shell execution.
- Commit grouping is deterministic: consecutive commits within 24 hours, shared module, and shared normalized title keyword.
- Code lines represent change size only and never affect health scoring.
- Release comparisons show equal windows, sample counts, and a correlation disclaimer.
- Follow TDD and make frequent commits.

---

## File Structure

- `frontend/src/lib/version.ts`: build-injected canonical version.
- `frontend/src/vite-env.d.ts`: `__APP_VERSION__` declaration.
- `agent/src/analytics/version.py`: backend package-version reader.
- `agent/src/analytics/git_activity.py`: safe Git command adapter and parser.
- `agent/src/analytics/development.py`: feature grouping, churn ranking, release comparison.
- `frontend/src/components/analytics/DevelopmentView.tsx`: commit/features/release UI.

### Task 1: Canonical Application Version

**Files:**
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/src/vite-env.d.ts`
- Create: `frontend/src/lib/version.ts`
- Create: `frontend/src/lib/__tests__/version.test.ts`
- Modify: `frontend/src/components/layout/Layout.tsx`
- Modify: `frontend/src/lib/analytics.ts`
- Create: `agent/src/analytics/version.py`
- Modify: `agent/src/analytics/runtime.py`
- Create: `agent/tests/analytics/test_version.py`

**Interfaces:**
- Produces: frontend `APP_VERSION`, backend `read_app_version(repo_root) -> str`.
- Consumes: Layout's current visible `v0.1.9`; moves that value into `frontend/package.json` and removes the independent literal.

- [ ] **Step 1: Write failing frontend and backend version tests**

```typescript
import { expect, it } from "vitest";
import { APP_VERSION } from "../version";

it("prefixes the build version exactly once", () => {
  expect(APP_VERSION).toMatch(/^v\d+\.\d+\.\d+$/);
  expect(APP_VERSION).not.toContain("vv");
});
```

```python
import json

from src.analytics.version import read_app_version


def test_backend_reads_frontend_package_version(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
    assert read_app_version(tmp_path) == "1.2.3"
```

- [ ] **Step 2: Run tests and verify missing version modules**

Run: `cd frontend && npm run test:run -- src/lib/__tests__/version.test.ts`

Expected: FAIL because `version.ts` is missing.

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_version.py -v`

Expected: FAIL because `src.analytics.version` is missing.

- [ ] **Step 3: Inject and consume one version value**

First update `frontend/package.json` and both root-package version fields in `frontend/package-lock.json` from `0.1.7` to `0.1.9`, preserving the currently displayed application version. In `vite.config.ts`, read and parse `frontend/package.json` with `readFileSync(new URL("./package.json", import.meta.url), "utf-8")`, then add:

```typescript
define: {
  __APP_VERSION__: JSON.stringify(packageJson.version),
},
```

Declare `const __APP_VERSION__: string;` in `vite-env.d.ts`; export `APP_VERSION = `v${__APP_VERSION__.replace(/^v/, "")}``. Import it in Layout and the browser analytics transport, delete the hard-coded constant, and send the unprefixed value as each product event's `app_version`. Backend validates the version against `^\d+\.\d+\.\d+$`, returns `"unknown"` for missing, invalid, or unreadable JSON, and sets the same value on system/development events created by the analytics runtime.

- [ ] **Step 4: Run tests/build and commit**

Run: `cd frontend && npm run test:run -- src/lib/__tests__/version.test.ts src/components/layout/__tests__/Layout.test.tsx && npm run build`

Expected: tests and build PASS; footer continues to display `v0.1.9` from the canonical package version.

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_version.py -v`

Expected: PASS.

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/src/vite-env.d.ts frontend/src/lib/version.ts frontend/src/lib/__tests__/version.test.ts frontend/src/components/layout/Layout.tsx frontend/src/lib/analytics.ts agent/src/analytics/version.py agent/src/analytics/runtime.py agent/tests/analytics/test_version.py
git commit -m "fix: use one application version source"
```

### Task 2: Safe Git Activity Reader

**Files:**
- Create: `agent/src/analytics/git_activity.py`
- Create: `agent/tests/analytics/test_git_activity.py`

**Interfaces:**
- Produces: `GitCommit`, `GitRelease`, `GitActivityReader.read_commits(since, limit=200)`, `read_releases()`.
- Consumes: local repository path only.

- [ ] **Step 1: Write tests against a temporary Git repository**

```python
import subprocess

from src.analytics.git_activity import GitActivityReader


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def test_reader_parses_commits_modules_and_release(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    path = tmp_path / "frontend/src/pages/Scanner.tsx"
    path.parent.mkdir(parents=True)
    path.write_text("export const scanner = 1;\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "feat: add scanner trend")
    second = tmp_path / "agent/src/scanner/core.py"
    second.parent.mkdir(parents=True)
    second.write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "fix: scanner metrics")
    _git(tmp_path, "tag", "v1.2.3")
    result = GitActivityReader(tmp_path).read()
    assert [commit.subject for commit in result.commits][:2] == ["fix: scanner metrics", "feat: add scanner trend"]
    assert {module for commit in result.commits for module in commit.modules} >= {"frontend/scanner", "backend/scanner"}
    assert result.releases[0].tag == "v1.2.3"


def test_non_repo_is_an_explicit_empty_result(tmp_path):
    result = GitActivityReader(tmp_path).read()
    assert result.commits == []
    assert result.warnings == ["git_unavailable"]
```

- [ ] **Step 2: Run and verify failure**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_git_activity.py -v`

Expected: FAIL because `git_activity.py` does not exist.

- [ ] **Step 3: Implement fixed Git commands and parsers**

Use `subprocess.run(command, cwd=repo_root, capture_output=True, text=True, timeout=3, check=True)` with no `shell=True`. Commands are fixed to:

```python
["git", "log", f"--since={since.isoformat()}", f"--max-count={limit}", "--date=iso-strict", "--pretty=format:%x1e%H%x1f%aI%x1f%an%x1f%s", "--numstat"]
["git", "for-each-ref", "--sort=-creatordate", "--format=%(refname:short)%00%(objectname)%00%(creatordate:iso-strict)", "refs/tags"]
```

Accept releases only when `re.fullmatch(r"v\d+\.\d+\.\d+", tag)` succeeds. Map file paths through a centralized prefix table; unknown paths map to their first directory. Count files under `tests/`, `agent/tests/`, or containing `__tests__` as test files. Binary numstat `-` values count as zero lines but still count as a changed file.

- [ ] **Step 4: Run tests and commit**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_git_activity.py -v`

Expected: all tests PASS.

```bash
git add agent/src/analytics/git_activity.py agent/tests/analytics/test_git_activity.py
git commit -m "feat: read local git development activity"
```

### Task 3: Feature Grouping, Churn, and Release Comparison

**Files:**
- Create: `agent/src/analytics/development.py`
- Create: `agent/tests/analytics/test_development.py`
- Modify: `agent/src/analytics/runtime.py`
- Modify: `agent/src/analytics/service.py`
- Modify: `agent/src/api/analytics_routes.py`
- Modify: `agent/tests/analytics/test_routes.py`

**Interfaces:**
- Produces: `group_commits(commits)`, `rank_module_churn(commits, days=30)`, `compare_release(tag, window_days)`, `GET /api/analytics/development`.
- Consumes: Phase 1 daily metric points and Git reader output.

- [ ] **Step 1: Write deterministic grouping tests**

```python
def test_grouping_requires_time_module_and_keyword_overlap():
    commits = [
        commit("a", "2026-07-13T10:00:00Z", "feat: add paper experiment API", ["paper-trading"]),
        commit("b", "2026-07-13T16:00:00Z", "feat: improve paper experiment UI", ["paper-trading"]),
        commit("c", "2026-07-14T17:00:00Z", "fix: paper experiment labels", ["paper-trading"]),
        commit("d", "2026-07-13T18:00:00Z", "feat: scanner trend", ["scanner"]),
    ]
    groups = group_commits(commits)
    assert groups[0].commit_shas == ["b", "a"]
    assert {tuple(group.commit_shas) for group in groups[1:]} == {("c",), ("d",)}
```

Normalize titles by lowercasing, removing conventional prefixes (`feat:`, `fix:`, `docs:`), and removing stop words `{add, update, improve, fix, the, a, an, to, and}`.

- [ ] **Step 2: Write release comparison tests**

```python
def test_release_comparison_uses_ratio_inputs_and_denies_causality(tmp_path):
    store = AnalyticsStore(tmp_path / "a.db")
    seed_ratio_points(store, "request_success_rate", before=(690, 700), after=(675, 700))
    comparison = DevelopmentService(store, fake_git_release("v1.2.3", "2026-07-13T00:00:00Z")).compare_release("v1.2.3", 7)
    metric = comparison.metrics[0]
    assert metric.before_value == 690 / 700
    assert metric.after_value == 675 / 700
    assert metric.before_sample_count == 700
    assert metric.after_sample_count == 700
    assert comparison.causal is False


def test_release_comparison_requires_three_days_each_side(tmp_path):
    store = AnalyticsStore(tmp_path / "a.db")
    seed_daily_points(store, before_days=2, after_days=7)
    result = DevelopmentService(store, fake_git_release("v1.2.3", "2026-07-13T00:00:00Z")).compare_release("v1.2.3", 7)
    assert result.status == "insufficient_sample"
```

- [ ] **Step 3: Run and verify failure**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_development.py -v`

Expected: FAIL because the development service is missing.

- [ ] **Step 4: Implement ingestion and comparisons**

At startup and each hourly cycle, scan only commits newer than the newest stored commit timestamp and submit deterministic development events keyed by SHA. Store module list, file/line/test counts, version, and summary in allowlisted metadata. Group commits at query time so corrected mapping rules do not require raw-event migration. A feature group's label is the newest commit subject with its conventional prefix removed; the response always includes every original subject and SHA.

Release comparison accepts `window_days` only in `{7, 30}`. Aggregate ratios from summed numerators/denominators, not averages of daily percentages. For scalar metrics use sample-count-weighted means. Return the exact disclaimer `时间相关性，不代表该版本造成了指标变化。`.

- [ ] **Step 5: Add and test the endpoint**

`GET /api/analytics/development?days=30&release=v1.2.3&window_days=7` returns commits, feature groups, module churn, releases, release comparison, `data_through`, and warnings. Protect it with the same local/auth dependency and `Cache-Control: no-store`.

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_development.py tests/analytics/test_routes.py -v`

Expected: all tests PASS.

- [ ] **Step 6: Commit development intelligence**

```bash
git add agent/src/analytics agent/src/api/analytics_routes.py agent/tests/analytics
git commit -m "feat: correlate development and release trends"
```

### Task 4: Development and Release Frontend

**Files:**
- Create: `frontend/src/components/analytics/DevelopmentView.tsx`
- Create: `frontend/src/components/analytics/__tests__/DevelopmentView.test.tsx`
- Modify: `frontend/src/pages/Analytics.tsx`
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Consumes: development endpoint.
- Produces: “研发与版本” view and timeline markers for the final dashboard plan.

- [ ] **Step 1: Write failing UI tests**

```typescript
it("shows feature provenance and honest release comparison", async () => {
  apiMock.getAnalyticsDevelopment.mockResolvedValue(developmentFixture);
  render(<DevelopmentView days={30} />);
  expect(await screen.findByText("模拟盘实验对比")).toBeInTheDocument();
  expect(screen.getByText(/466146f/)).toBeInTheDocument();
  expect(screen.getByText(/ea104ad/)).toBeInTheDocument();
  expect(screen.getByText("17 files")).toBeInTheDocument();
  expect(screen.getByText("+620")).toBeInTheDocument();
  expect(screen.getByText("−48")).toBeInTheDocument();
  expect(screen.getByText("时间相关性，不代表该版本造成了指标变化。")).toBeInTheDocument();
  expect(screen.getByText("样本不足")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run and verify failure**

Run: `cd frontend && npm run test:run -- src/components/analytics/__tests__/DevelopmentView.test.tsx`

Expected: FAIL because component and API types are absent.

- [ ] **Step 3: Implement typed development UI**

Add `AnalyticsCommit`, `AnalyticsFeatureGroup`, `AnalyticsRelease`, `ReleaseMetricComparison`, and `AnalyticsDevelopmentResponse`. Render summary cards for commits/files/insertions/deletions, a feature timeline with expandable raw commits, module-churn bars, release selector, 7/30-day window selector, and before/after metric cards. Label insertions/deletions “变更规模”.

- [ ] **Step 4: Run tests and build**

Run: `cd frontend && npm run test:run -- src/components/analytics/__tests__/DevelopmentView.test.tsx src/pages/__tests__/Analytics.test.tsx && npm run build`

Expected: all tests PASS and build succeeds.

- [ ] **Step 5: Commit and verify Phase 3**

```bash
git add frontend/src/components/analytics/DevelopmentView.tsx frontend/src/components/analytics/__tests__/DevelopmentView.test.tsx frontend/src/pages/Analytics.tsx frontend/src/lib/api.ts
git commit -m "feat: add development and release analytics"
```

Run: `cd agent && ../.venv/bin/pytest tests/analytics -v`

Expected: all analytics backend tests PASS.
