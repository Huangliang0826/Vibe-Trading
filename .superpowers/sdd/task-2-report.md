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
