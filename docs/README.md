# Search Page Guide

This page summarizes how to operate the `/search` view in the viewer UI, how results are retrieved, and how the instrumentation controls behave.

## Search workflow

1. **Enter a query** in the text box at the top of the card.
2. **Pick a mode**:
   - `BM25` returns individual segments ranked only by the BM25 index.
   - `Hybrid (BM25 + Vector)` returns whole documents scored by the reciprocal-rank fusion of BM25 and vector results.
3. **Tune parameters**:
   - **BM25**: optional score threshold (e.g., `-0.8`) to hide weak matches.
   - **Hybrid**: `BM25 weight`, `Vector weight`, and `k` (top-k depth per leg).
4. **Press `Search`**. The app calls either `/search/bm25` or `/search/hybrid_documents` on the API, passing the current parameters. Results appear below the instrumentation card in segment or document form depending on the mode.

Search requests are stateless. Editing the query or mode does nothing until you press `Search` again.

## Instrumentation controls

The “Instrumentation” card (below the search controls) drives the `/stats/search_plan` endpoint and works independently from the main search action:

- **Explain query**: submits the current query + parameters to `/stats/search_plan`. This does *not* update the result lists unless you also press `Search`.
- **Analyze toggle** (now located beside the Explain button inside the instrumentation card):
  - When off (default) the API runs `EXPLAIN (FORMAT JSON)` so you only see the compiled plan.
  - When on, `EXPLAIN ANALYZE` is executed, meaning the real query actually runs and the planner output contains execution timing and buffer stats. Use Analyze sparingly because it exerts real load on the database.
- **Mode + parameters**: the plan request uses whatever is currently selected in the controls, so you can inspect BM25 vs. Hybrid plans without having to rerun a search.
- **Plan output**: the top block summarizes timing and limits. The bottom block is the raw JSON plan so you can confirm that PostgreSQL is using `PgTextSearchBMScan` and `Bitmap Index Scan` (for BM25) or the proper IVFFlat path (for hybrid).

Instrumentation data persists until you click Explain again or change the page. Running a search does not refresh the plan automatically.

## Data freshness

- Search results show live data directly from the API. Any ingest, re-index, or vectorizer change becomes visible the next time you press `Search`.
- The instrumentation plan reflects the current database statistics. If you recently modified indexes or ran `VACUUM ANALYZE`, re-run Explain to capture the new plan.
- Export buttons fetch individual segment markdown exports through `/documents/segments/{id}/export` and do not depend on the instrumentation card.

## Tips

- Right-clicking on a BM25 segment card exports the snippet immediately.
- Use Explain without Analyze first to confirm the plan; only enable Analyze when you need execution timing.
- If Explain fails, the instrumentation card displays the API error so you can inspect `/stats/search_plan` directly.
