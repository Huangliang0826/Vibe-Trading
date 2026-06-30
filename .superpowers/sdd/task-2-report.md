# Task 2 Report: SQLite Persistence and Idempotency

## Implementation

- Created `agent/src/opportunity_center/storage.py` with `OpportunityStore(db_path: Path | None = None)`.
- Defaulted the store path to `get_runtime_root() / "opportunity_center.db"` and created the parent directory on initialization.
- Initialized the exact Task 2 SQLite tables for:
  - `news_sources`
  - `news_articles`
  - `news_matches`
  - `stock_profiles`
  - `news_analyses`
  - `opportunity_snapshots`
  - `refresh_jobs`
- Applied SQLite WAL mode and `synchronous=NORMAL` on every connection.
- Implemented atomic, parameterized persistence methods for:
  - `upsert_articles()`
  - `find_recent_articles()`
  - `save_matches()`
  - `get_news_analysis()`
  - `save_news_analysis()`
  - `create_job()`
  - `update_job()`
  - `get_active_job()`
  - `upsert_snapshot()`
  - `list_latest()`
  - `get_detail()`
  - `get_history()`
  - `has_market_refresh()`
- Persisted snapshot rows as a permanent JSON envelope containing the validated `OpportunityItem` plus stored detail metadata.
- Computed `score_change` from the previous distinct `(market, code)` snapshot before writing each snapshot row.
- Stored news-analysis payloads with `model_dump_json()` and keyed them by `(article_id, market, code, analysis_date, prompt_version)`.
- Added local URL canonicalization for article storage so idempotency is based on stable URLs rather than tracking-parameter variants.
- Ensured `list_latest()` chooses the newest snapshot per `(market, code)` first, then applies filters after Pydantic validation, and only then applies `limit`.

## Tests / Results

- Focused storage + contract regression:
  - `uv run pytest agent/tests/opportunity_center/test_storage.py agent/tests/opportunity_center/test_models.py -v`
  - Result: `13 passed in 0.47s`
- Focused storage suite during the first GREEN pass:
  - `uv run pytest agent/tests/opportunity_center/test_storage.py -v`
  - Result: `7 passed in 0.49s`
- Diff hygiene:
  - `git diff --check`
  - Result: no whitespace or patch-format issues

## RED / GREEN Evidence

### RED

1. Added `agent/tests/opportunity_center/test_storage.py` first.
2. Ran:
   - `uv run pytest agent/tests/opportunity_center/test_storage.py -v`
3. Observed the expected missing-implementation failure:
   - `ModuleNotFoundError: No module named 'src.opportunity_center.storage'`

### GREEN

1. Implemented `agent/src/opportunity_center/storage.py`.
2. Re-ran:
   - `uv run pytest agent/tests/opportunity_center/test_storage.py -v`
3. Result:
   - all 7 storage tests passed
4. Added a follow-up regression test covering the filter-after-validation requirement in `list_latest()`.
5. Re-ran the focused verification suite:
   - `uv run pytest agent/tests/opportunity_center/test_storage.py agent/tests/opportunity_center/test_models.py -v`
6. Result:
   - all 13 focused tests passed

## Files Changed

- `agent/src/opportunity_center/storage.py`
- `agent/tests/opportunity_center/test_storage.py`

## Self-Review

- The store surface stays inside the ownership boundary from the brief: one production module and one focused test module.
- Snapshot history is preserved permanently: upserts only replace the same `(market, code, snapshot_date, score_version, strategy_version)` row and do not collapse earlier dates.
- `score_change` intentionally ignores the current row on same-key rewrites, so same-day reruns still compare against the previous distinct snapshot rather than the snapshot being overwritten.
- `get_detail()` reconstructs `OpportunityDetail` from validated stored snapshot data plus same-day persisted news analyses, which keeps the storage layer aligned with the Task 1 contracts without inventing a second schema.
- I caught and fixed a subtle self-review issue where `list_latest()` originally limited rows before applying post-validation filters; the final version filters first and only then slices to `limit`.
- I did not touch the unrelated forecast DCA baseline failure.

## Concerns

- `refresh_jobs` does not have dedicated `started_at` / `finished_at` columns in the Task 2 schema, so `RefreshJob.started_at` and `finished_at` are derived from `created_at` / `updated_at` based on status. This is consistent within the current task surface, but later tasks may want to persist those timestamps explicitly if the schema is extended.

## Task 2 Review Fixes

### Fixes

- Canonical URL conflicts now retain and return the already-persisted `article_id`. A feed item whose incoming ID changes therefore continues to address the same news-analysis cache entries.
- Added nullable `started_at` and `finished_at` columns to new `refresh_jobs` tables and additive `ALTER TABLE` migration logic for existing Task 2 databases.
- `update_job()` now records `started_at` only on `queued -> running` and `finished_at` only on `running -> completed/failed`, preserving the first transition timestamps on later updates.
- `create_job()` now uses `BEGIN IMMEDIATE` to serialize active-job detection and insertion, returning an existing queued or running job instead of creating a competitor.
- Active-job reads now deterministically prefer running jobs over queued jobs, then use stable creation-time and job-ID ordering.

### RED / GREEN Evidence

RED after adding the review regression tests:

- Command: `uv run pytest agent/tests/opportunity_center/test_storage.py -v`
- Result: `5 failed, 7 passed in 0.60s`
- Expected failures covered canonical article identity, both terminal timestamp transitions, active-job deduplication, and running-over-newer-queued precedence.

GREEN after implementing the fixes:

- Command: `uv run pytest agent/tests/opportunity_center/test_storage.py -v`
- Result: `12 passed in 0.52s`

Final focused regression:

- Command: `uv run pytest agent/tests/opportunity_center/test_storage.py agent/tests/opportunity_center/test_models.py -v`
- Result: `17 passed in 0.50s`

### Files Changed

- `agent/src/opportunity_center/storage.py`
- `agent/tests/opportunity_center/test_storage.py`
- `.superpowers/sdd/task-2-report.md`

### Self-Review

- Canonical URL lookup is deliberately evaluated before incoming-ID lookup, making the persisted canonical identity authoritative when the two identifiers disagree.
- Existing databases migrate without rebuilding or deleting `refresh_jobs`; historical rows keep null lifecycle timestamps rather than receiving fabricated values.
- The active-job select and insert occur under one SQLite write reservation, preventing concurrent creators from both observing an empty active set.
- A direct legacy-state regression confirms a newer queued row cannot hide an older running row even if such competing rows already exist.
- No model changes were needed, and the unrelated forecast DCA baseline was not touched.

### Concerns

- Pre-migration jobs retain null `started_at` and `finished_at` because their true transition times cannot be reconstructed accurately. New transitions are persisted exactly.

## Direct Terminal Transition Fix

- Updated `update_job()` so the first transition from any non-terminal status to `completed` or `failed` records `finished_at`.
- Direct `queued -> completed` and `queued -> failed` transitions leave `started_at` null because those jobs never ran.

RED regression command:

- Command: `uv run pytest agent/tests/opportunity_center/test_storage.py -v -k queued_job_terminal_transition`
- Result: `2 failed, 12 deselected in 0.51s`
- Both failures showed `finished_at=None` while `updated_at` contained the controlled terminal-transition time.

GREEN regression command:

- Command: `uv run pytest agent/tests/opportunity_center/test_storage.py -v -k queued_job_terminal_transition`
- Result: `2 passed, 12 deselected in 0.40s`

Final focused regression:

- Command: `uv run pytest agent/tests/opportunity_center/test_storage.py agent/tests/opportunity_center/test_models.py -v`
- Result: `19 passed in 0.43s`

## Atomic Job Updates And Backfill Score Changes

### Fixes

- Replaced `update_job()`'s unlocked read-then-write sequence with one conditional `UPDATE`. SQLite now evaluates lifecycle timestamp transitions against the current persisted row while status, progress, totals, market dates, errors, and `updated_at` update atomically.
- `started_at` and `finished_at` remain write-once under concurrent writers; later updates can still change status and progress without replacing either lifecycle timestamp.
- Changed snapshot predecessor selection to the newest row for the same market/code whose `snapshot_date` is strictly earlier than the incoming snapshot date.
- Same-day snapshot rewrites and historical backfills therefore compare against the same chronological predecessor and never against a future snapshot.

### RED / GREEN Evidence

RED after adding the concurrency and backfill regressions:

- Command: `uv run pytest agent/tests/opportunity_center/test_storage.py -v -k 'concurrent_job_updates or backfilled_snapshot'`
- Result: `2 failed, 14 deselected in 0.49s`
- The concurrent writers returned two distinct `started_at` values, and the D2 backfill calculated `-10` from D3 instead of `10` from D1.

GREEN after implementing the fixes:

- Command: `uv run pytest agent/tests/opportunity_center/test_storage.py -v -k 'concurrent_job_updates or backfilled_snapshot'`
- Result: `2 passed, 14 deselected in 0.45s`

Final focused regression:

- Command: `uv run pytest agent/tests/opportunity_center/test_storage.py agent/tests/opportunity_center/test_models.py -v`
- Result: `21 passed in 0.43s`

### Self-Review And Concerns

- The concurrency regression uses separate SQLite connections in two threads and coordinates the old pre-update reads, so it deterministically reproduces stale lifecycle writes rather than relying on scheduler timing.
- The conditional update still preserves omitted `completed`, `total`, and `market_dates` values and retains the existing behavior of clearing `error` when omitted.
- Snapshot chronology relies on the existing ISO `YYYY-MM-DD` date representation, whose lexical order matches chronological order.

## Terminal Immutability And Successor Rebasing

### Fixes

- Added an allowed-transition predicate to the atomic job update: queued jobs may remain queued or move to running/completed/failed; running jobs may remain running or move to completed/failed.
- Completed and failed jobs now ignore all later status, progress, total, market-date, and error updates and return their persisted terminal state unchanged.
- Concurrent terminal writers now converge on the first committed terminal outcome, preserving `get_active_job()` and `has_market_refresh()` semantics.
- Snapshot upserts now find the immediate next chronological date and rebase every versioned row at that date inside the same SQLite transaction.
- Inserting D2 between D1 and D3 recalculates D3 from D2, and rewriting D2 recalculates D3 again without changing snapshot uniqueness keys or stored detail data.

### RED / GREEN Evidence

RED after extending the terminal and chronology regressions:

- Command: `uv run pytest agent/tests/opportunity_center/test_storage.py -v -k 'terminal_job_is_immutable or concurrent_job_updates or backfilled_snapshot'`
- Result: `4 failed, 14 deselected in 0.53s`
- Completed and failed jobs reopened, concurrent terminal writers returned different outcomes, and D3 retained its stale `20` score change after D2 was inserted.

GREEN after implementing the invariants:

- Command: `uv run pytest agent/tests/opportunity_center/test_storage.py -v -k 'terminal_job_is_immutable or concurrent_job_updates or backfilled_snapshot'`
- Result: `4 passed, 14 deselected in 0.47s`

Final focused regression:

- Command: `uv run pytest agent/tests/opportunity_center/test_storage.py agent/tests/opportunity_center/test_models.py -v`
- Result: `23 passed in 0.44s`

### Self-Review And Concerns

- Invalid nonterminal transitions such as `running -> queued` are also no-ops, matching the explicit allowed-transition list.
- Successor rebasing updates only `payload_json` and `updated_at`; primary-key version dimensions, trigger, creation time, and detail payloads remain intact.
- Chronological comparison continues to rely on the existing ISO `YYYY-MM-DD` snapshot-date contract.

## Deterministic Latest-Version Selection

### Fix

- Replaced `list_latest()`'s timestamp-only anti-join with `ROW_NUMBER()` partitioned by `(market, code)`.
- Rows rank by `snapshot_date DESC`, `updated_at DESC`, and `rowid DESC`, so same-day versions with identical second-precision timestamps deterministically select the later persisted row.
- Pydantic reconstruction, market/signal/level filters, and the final limit remain after SQL ranking.

### RED / GREEN Evidence

RED after adding the tied-version regression:

- Command: `uv run pytest agent/tests/opportunity_center/test_storage.py -v -k list_latest_deterministically`
- Result: `1 failed, 18 deselected in 0.49s`
- The unfiltered listing returned both same-day versions instead of one row.

GREEN after implementing deterministic ranking:

- Command: `uv run pytest agent/tests/opportunity_center/test_storage.py -v -k list_latest_deterministically`
- Result: `1 passed, 18 deselected in 0.39s`
- The later persisted version was selected; filters matching only the superseded version returned no rows, and `limit=1` remained correct.

Final focused regression:

- Command: `uv run pytest agent/tests/opportunity_center/test_storage.py agent/tests/opportunity_center/test_models.py -v`
- Result: `24 passed in 0.44s`

## Deterministic Snapshot Chronology

### Fix

- Added `rowid DESC` as the final tie-breaker for strictly earlier predecessor selection, immediate-successor version scans, `get_detail()`, and `get_history()`.
- Same-date versions sharing identical second-precision timestamps now consistently treat the later persisted row as newer.
- `get_history()` retains every permanent version row while returning a stable date/timestamp/insertion chronology.

### RED / GREEN Evidence

RED after adding tied predecessor/detail/history coverage:

- Command: `uv run pytest agent/tests/opportunity_center/test_storage.py -v -k snapshot_chronology_uses_later_rowid`
- Result: `1 failed, 19 deselected in 0.85s`
- Explicit D1 detail returned the earlier persisted version under the timestamp tie.

GREEN after adding insertion-order tie-breakers:

- Command: `uv run pytest agent/tests/opportunity_center/test_storage.py -v -k snapshot_chronology_uses_later_rowid`
- Result: `1 passed, 19 deselected in 0.40s`
- D2 score changes used the later D1 predecessor, detail selected the later same-day version, and history returned all versions in deterministic descending order.

Final focused regression:

- Command: `uv run pytest agent/tests/opportunity_center/test_storage.py agent/tests/opportunity_center/test_models.py -v`
- Result: `25 passed in 0.46s`
