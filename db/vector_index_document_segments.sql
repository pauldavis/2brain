-- Vector index for hybrid BM25/semantic search.
-- Requires the `vector` extension (installed by migration 0002_segment_embeddings.sql).

-- Tune `lists` based on table size. More lists = better recall but slower builds.
CREATE INDEX CONCURRENTLY IF NOT EXISTS document_segments_embedding_ivf_idx
ON public.document_segments
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 200);

-- After creating the index, run ANALYZE so the planner picks it up quickly:
--   ANALYZE public.document_segments;
-- And set `SET ivfflat.probes = 10;` (or higher) in the session running hybrid search
-- queries to balance recall versus latency.
