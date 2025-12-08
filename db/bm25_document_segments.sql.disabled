-- BM25 index for high-quality segments.
-- Run from psql or the Timescale SQL editor.
-- Adjust index_memory_limit to suit your service size before creating large indexes.

SET pg_textsearch.index_memory_limit = '512MB';

CREATE INDEX CONCURRENTLY IF NOT EXISTS document_segments_bm25_idx
ON document_segments
USING bm25(content_markdown)
WITH (text_config = 'english')
WHERE embedding_status = 'ready'
  AND is_noise = FALSE;

-- Example search:
-- SELECT
--   document_id,
--   segment_id,
--   content_markdown,
--   content_markdown <@> to_bm25query('vectorizer status', 'document_segments_bm25_idx') AS score
-- FROM document_segments
-- WHERE embedding_status = 'ready'
--   AND is_noise = FALSE
-- ORDER BY score
-- LIMIT 20;
