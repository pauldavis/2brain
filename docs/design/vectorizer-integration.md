# PGAI Vectorizer + BM25 Runbook

- [x] Apply migration `0002_segment_embeddings.sql` to add quality + embedding columns and trigger logic.
- [x] Run `pgai install -d <db_url>` in each environment to provision the `ai.*` schema and helper functions.
- [x] Configure embedding provider credentials for pgai (Timescale Console API key store or environment variables such as `OPENAI_API_KEY` / `VOYAGE_API_KEY`).
- [x] Confirm ingestion pipeline populates `quality_score` / `is_noise`; override per segment if upstream signals exist (`ingest/db.py` auto-heuristic is the baseline).
- [x] Create the column-destination vectorizer targeting `document_segments.embedding`:
  ```sql
  SELECT ai.create_vectorizer(
      'public.document_segments'::regclass,
      name        => 'document_segments_embedding',
      loading     => ai.loading_column('content_markdown'),
      chunking    => ai.chunking_none(),  -- column destinations must be 1:1
      formatting  => ai.formatting_python_template(
          $$doc=$document_version_id seq=$sequence role=$source_role\n\n$chunk$$
      ),
      embedding   => ai.embedding_openai('text-embedding-3-small', 1536),
      destination => ai.destination_column('embedding'),
      processing  => ai.processing_default(batch_size => 25, concurrency => 4),
      enqueue_existing => true
  );
  ```
- [ ] Start vectorizer workers:
  - [ ] Timescale Cloud auto-scheduler enabled (default), or
  - [ ] Self-hosted worker running (`pgai vectorizer worker -d $DB_URL`) with provider keys loaded.
- [ ] Track rollout health:
  - [ ] `SELECT * FROM ai.vectorizer_status;` (queue depth / last runs).
  - [ ] `SELECT * FROM ai.vectorizer_errors WHERE vectorizer_id = <id>;` (API/parsing issues).
  - [ ] Tune `ai.processing_default` if rate limits or latency spikes appear.
- [x] Ensure downstream search paths filter `is_noise = FALSE` and `embedding_status = 'ready'` (`app/services/search.py`).
- [ ] Follow-up enhancements:
  - [x] Build partial BM25 index on `document_segments` (`WHERE is_noise = FALSE AND embedding_status = 'ready'`) for hybrid ranking (`db/bm25_document_segments.sql`).
  - [x] Add an IVFFlat vector index for `document_segments.embedding` to accelerate the semantic leg of hybrid search (`db/vector_index_document_segments.sql`).
  - [ ] Add a maintenance job that nulls embeddings + re-enqueues segments when `quality_score` changes materially.
  - [x] Expose `IVFFLAT_PROBES` application setting so hybrid search always sets an appropriate probe count on every connection.

## BM25 Index Creation (final form)

- We observed the planner avoiding a partial BM25 index and falling back to a full `Seq Scan` with multi‑second latency.
- Final approach: build an unrestricted BM25 index and let the query filter if needed.

SQL (use this in production):

```sql
-- Unrestricted BM25 index
CREATE INDEX CONCURRENTLY IF NOT EXISTS public.document_segments_bm25_idx
ON public.document_segments
USING bm25(content_markdown)
WITH (text_config = 'english');

VACUUM ANALYZE public.document_segments;  -- keep stats fresh
```

Canonical ranked search (fast):

```sql
SELECT
  ds.id AS segment_id,
  LEFT(ds.content_markdown, 280) AS snippet,
  ds.content_markdown <@> to_bm25query('vectorizer status', 'document_segments_bm25_idx') AS score
FROM public.document_segments ds
ORDER BY score
LIMIT 20;
```

Notes:
- `to_bm25query(<search text>, '<index_name>')` must reference the exact index name.
- Lower (more negative) score = better. Use a threshold to drop weak matches, e.g. `WHERE score < -0.8`.
- First query after restart will be slower (memtable warm‑up). Subsequent queries are sub‑100 ms.

## Troubleshooting we hit (and fixes)

1) Vectorizer didn’t drain after API key fix
- Cause: initial runs queued items with a bad key; remaining rows never re‑queued after fixing the key.
- Fix: manually re‑insert `id` into `ai._vectorizer_q_1` for rows with `embedding_status <> 'ready'`, then `SELECT ai.execute_vectorizer('<name>');`.

2) `ai.vectorizer_errors` query shape
- The view has `id` (vectorizer id), `message`, `details`, `recorded`. There is no `vectorizer_id` column.

3) “Pending forever” segments
- Cause: segments with empty/whitespace `content_markdown` are skipped by pgai (no chunks), so they never flip to ready.
- Fix: mark them `is_noise = TRUE`, optionally set `embedding_status = 'ready'` for dashboard parity.

4) Backfilling `quality_score` / `is_noise`
- Existing rows were ingested before the heuristic existed in `ingest/db.py`; we ran a one‑time SQL backfill so both fields reflect content.

5) `load_index` helper not found
- In `pg_textsearch 0.0.1` there is no exported `load_index()`; the memtable warms on first query.

6) `index_memory_limit` cannot be changed now
- It’s a GUC; changing it mid‑session often fails. Use the default (64MB) or apply `ALTER SYSTEM SET pg_textsearch.index_memory_limit = '…'; SELECT pg_reload_conf();` and reconnect.

7) Partial BM25 index caused `Seq Scan`
- The partial predicate prevented the optimizer from choosing the custom BM25 scan. Rebuilding the index without `WHERE` fixed it.

8) Schema qualification when dropping/creating indexes
- Use `public.document_segments_bm25_idx` (index) and `public.document_segments` (table). Do not use `schema.table.index` syntax.

9) DataGrip parameter binding
- Use `?::text` or `:q::text` with param type = String/Text. Double quotes on values turn them into identifiers and error with `column "…" does not exist`.

10) Tiger Console EXPLAIN output
- The web SQL tab shows “0 rows affected”. Use `EXPLAIN (… FORMAT JSON)` in a client (DataGrip/psql) to see the actual plan; look for `Custom Scan (PgTextSearchBMScan)`.

## Next steps (plan)

1) Wire BM25 into the service
- Add a BM25 code path in `app/services/search.py` beside the existing tsquery flow. Accept a `q` term and return top‑N ranked by BM25.

2) Hybrid ranking
- Implement a simple reciprocal‑rank fusion (RRF) between BM25 and vector search. Start with 50/50 weights and tune.

3) Maintenance tasks
- Nightly `VACUUM ANALYZE public.document_segments;` to keep the planner hot.
- Periodic audit for empty‑content segments; mark as noise.
- Re‑enqueue routine that nulls `embedding` and re‑queues when rescoring logic changes.

4) Observability
- Saved queries/dashboards for: `ai.vectorizer_status`, queue depths, BM25 latency (`EXPLAIN ANALYZE` samples), and `pg_stat_user_indexes.idx_scan` for `document_segments_bm25_idx`.

5) UI polish
- Add BM25 search input + threshold slider. Optional toggle to expand neighbors and to blend with semantic scores.

## Quick commands

Check vectorizer and queues:
```sql
SELECT * FROM ai.vectorizer_status;
SELECT ai.vectorizer_queue_pending('document_segments_embedding', true);
SELECT COUNT(*) FROM ai._vectorizer_q_1;
SELECT COUNT(*) FROM ai._vectorizer_q_failed_1;
```

Confirm BM25 index and usage:
```sql
SELECT to_regclass('public.document_segments_bm25_idx');
SELECT indexrelname, idx_scan
FROM pg_stat_user_indexes
WHERE indexrelname = 'document_segments_bm25_idx';
```

Run BM25 search:
```sql
SELECT
  ds.id,
  LEFT(ds.content_markdown, 280) AS snippet,
  ds.content_markdown <@> to_bm25query('nokia', 'document_segments_bm25_idx') AS score
FROM public.document_segments ds
ORDER BY score
LIMIT 20;
```

> **Timescale Cloud note:** If `ai.*` objects are missing, install pgai once from the Console or CLI, then rerun the vectorizer SQL.

## Vector Index Creation

- Use the helper in `db/vector_index_document_segments.sql` to build `document_segments_embedding_ivf_idx` once the `vector` extension is available.
- After the index is built, run `ANALYZE public.document_segments;` so the planner is aware of the new access path.
- Set `SET ivfflat.probes = 10;` (or tune higher) in hybrid-search sessions to trade recall for latency.

### Application configuration

- The API automatically issues `SET ivfflat.probes = <value>` for every connection when `IVFFLAT_PROBES` is present in the environment (defaults to 10 when unset).
- Raise `IVFFLAT_PROBES` if you notice recall dropping after adding more data or if you increase `k` in the hybrid query.
