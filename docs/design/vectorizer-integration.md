# PGAI Vectorizer integration checklist

- [ ] Apply migration `0002_segment_embeddings.sql` to add quality + embedding columns and trigger logic.
- [ ] Run `pgai install -d <db_url>` in each environment to provision the `ai.*` schema and helper functions.
- [ ] Configure embedding provider credentials for pgai (Timescale Console API key store or environment variables such as `OPENAI_API_KEY` / `VOYAGE_API_KEY`).
- [ ] Confirm ingestion pipeline populates `quality_score` / `is_noise`; override per segment if upstream signals exist (`ingest/db.py` auto-heuristic is the baseline).
- [ ] Create the column-destination vectorizer targeting `document_segments.embedding`:
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
- [ ] Ensure downstream search paths filter `is_noise = FALSE` and `embedding_status = 'ready'`.
- [ ] Follow-up enhancements:
  - [ ] Build partial BM25 index on `document_segments` (`WHERE is_noise = FALSE`) for hybrid ranking.
  - [ ] Add a maintenance job that nulls embeddings + re-enqueues segments when `quality_score` changes materially.
