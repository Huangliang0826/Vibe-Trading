# Task 3 Report: RSS Ingestion, Matching, and Cached AI Analysis

## Implementation

- Added [feeds.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/src/opportunity_center/feeds.py) with:
  - `NewsSource`
  - `canonicalize_url(url)`
  - `parse_feed(xml, source, now)`
  - `FeedIngestor(store, source_path, max_concurrency=12).refresh(now)`
- Implemented safe RSS 2.0 / Atom parsing with `xml.etree.ElementTree`.
- Canonicalized article URLs by removing `utm_*`, `ref`, `source`, and fragments.
- Enforced seven-day recency and six-item per-source limits during parsing.
- Added same-day dedupe for canonical URL collisions and near-title collisions using `SequenceMatcher >= 0.92` over normalized title fingerprints.
- Applied global ingest-time dedupe against recent persisted articles without changing the `OpportunityStore` contract.
- Added [matching.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/src/opportunity_center/matching.py) with:
  - `NewsMatch`
  - `build_stock_context(market, code, quote_name, profile)`
  - `match_articles(context, articles)`
- Implemented deterministic direct > industry > macro matching using stock code, quote/profile names, aliases, brands, products, sector/industry terms, and macro keywords.
- Added [news_analysis.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/src/opportunity_center/news_analysis.py) with:
  - `NEWS_PROMPT_VERSION = "news-impact-v1"`
  - `NewsAnalyzer(store, llm_factory=ChatLLM).analyze(context, matches, analysis_date)`
- Implemented per-stock/day/article/prompt cache reuse through `OpportunityStore.get_news_analysis()` and `save_news_analysis()`.
- Enforced analysis caps of 10 direct, 5 industry, and 3 macro matches per stock/day, newest first within each bucket.
- Batched uncached LLM work at 12 items max per call.
- Stripped optional markdown fences, parsed the whole JSON object, validated rows through `NewsImpact`, and dropped malformed output without manufacturing neutral impacts.

## Tests / Results

- RED:
  - `uv run pytest agent/tests/opportunity_center/test_feeds.py agent/tests/opportunity_center/test_matching_analysis.py -v`
  - Result: `9 failed` with `ModuleNotFoundError` for the new Task 3 modules.
- GREEN (Task 3 focused):
  - `uv run pytest agent/tests/opportunity_center/test_feeds.py agent/tests/opportunity_center/test_matching_analysis.py -v`
  - Result: `9 passed in 0.70s`
- Final focused regression:
  - `uv run pytest agent/tests/opportunity_center/test_models.py agent/tests/opportunity_center/test_storage.py agent/tests/opportunity_center/test_feeds.py agent/tests/opportunity_center/test_matching_analysis.py -v`
  - Result: `34 passed in 0.76s`
- Patch hygiene:
  - `git diff --check`
  - Result: clean

## RED / GREEN Evidence

### RED

1. Wrote the Task 3 tests first:
   - [test_feeds.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/tests/opportunity_center/test_feeds.py)
   - [test_matching_analysis.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/tests/opportunity_center/test_matching_analysis.py)
2. Ran:
   - `uv run pytest agent/tests/opportunity_center/test_feeds.py agent/tests/opportunity_center/test_matching_analysis.py -v`
3. Observed expected missing-implementation failures:
   - `ModuleNotFoundError: No module named 'src.opportunity_center.feeds'`
   - `ModuleNotFoundError: No module named 'src.opportunity_center.matching'`
   - `ModuleNotFoundError: No module named 'src.opportunity_center.news_analysis'`

### GREEN

1. Implemented the three Task 3 production modules.
2. Re-ran:
   - `uv run pytest agent/tests/opportunity_center/test_feeds.py agent/tests/opportunity_center/test_matching_analysis.py -v`
3. Result:
   - all 9 Task 3 tests passed
4. Ran the broader opportunity-center focused suite:
   - `uv run pytest agent/tests/opportunity_center/test_models.py agent/tests/opportunity_center/test_storage.py agent/tests/opportunity_center/test_feeds.py agent/tests/opportunity_center/test_matching_analysis.py -v`
5. Result:
   - all 34 focused tests passed

## Files Changed

- [feeds.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/src/opportunity_center/feeds.py)
- [matching.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/src/opportunity_center/matching.py)
- [news_analysis.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/src/opportunity_center/news_analysis.py)
- [test_feeds.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/tests/opportunity_center/test_feeds.py)
- [test_matching_analysis.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/tests/opportunity_center/test_matching_analysis.py)
- [task-3-report.md](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/.superpowers/sdd/task-3-report.md)

## Self-Review

- I kept the ownership boundary intact: the Task 3 work lives in the three requested production files plus Task 3 tests and this report.
- I did not redesign `NewsArticle`, `NewsImpact`, `StockContext`, or `OpportunityStore`; all new behavior is layered on top of the existing strict contracts.
- Because `NewsArticle` does not expose a `canonical_url` field, canonical URLs are represented by the normalized `url` value instead of inventing a new contract field.
- Because `OpportunityStore` currently exposes cache methods only for news-analysis rows, I kept `build_stock_context()` deterministic and local; the brief’s optional LLM enrichment path was not needed to satisfy Task 3 and would have required new storage API surface.
- The dedupe path intentionally happens before persistence so Task 3 gets real canonical and near-title suppression without modifying Task 2 storage semantics.
- Malformed LLM JSON now produces warnings and omission only; there is no fallback neutral `NewsImpact`.

## Concerns

- `FeedIngestor.refresh()` is synchronous by contract and uses `asyncio.run()` internally; if a later caller needs ingestion inside an already-running event loop, that caller will likely want an explicit async entry point.
- Matching currently relies on article title/summary text plus the existing `StockContext` fields. Since `NewsArticle` does not carry persisted source-sector metadata, source-hint-aware matching would need a future contract extension if later tasks require it.
