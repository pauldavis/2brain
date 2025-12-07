-- Hybrid search helper returning JSON payloads for the API.
-- Run this after applying migrations: psql -f db/api_search_hybrid_documents.sql

CREATE SCHEMA IF NOT EXISTS api;

CREATE OR REPLACE FUNCTION api.search_hybrid_documents_json(
    p_query text,
    p_query_embedding vector,
    p_w_bm25 double precision DEFAULT 0.5,
    p_w_vec double precision DEFAULT 0.5,
    p_k integer DEFAULT 60,
    p_limit integer DEFAULT 20,
    p_offset integer DEFAULT 0,
    p_doc_topk integer DEFAULT 3,
    p_doc_top_segments integer DEFAULT 3,
    p_segment_limit integer DEFAULT NULL,
    p_w_best double precision DEFAULT 0.6,
    p_w_topk double precision DEFAULT 0.3,
    p_w_density double precision DEFAULT 0.1
)
RETURNS jsonb
LANGUAGE sql
AS
$$
WITH settings AS (
    SELECT COALESCE(
        p_segment_limit,
        GREATEST(p_limit * GREATEST(p_doc_topk, p_doc_top_segments), 50)
    )::integer AS segment_limit
),
bm AS (
  SELECT segment_id,
         ROW_NUMBER() OVER (ORDER BY score) AS r
  FROM (
    SELECT ds.id AS segment_id,
           ds.content_markdown <@> to_bm25query(p_query, 'document_segments_bm25_idx') AS score
    FROM public.document_segments ds
    WHERE ds.embedding_status = 'ready'
      AND ds.is_noise = FALSE
    ORDER BY score
    LIMIT p_k
  ) ranked
),
vec AS (
  SELECT segment_id,
         ROW_NUMBER() OVER (ORDER BY dist) AS r
  FROM (
    SELECT ds.id AS segment_id,
           ds.embedding <=> p_query_embedding AS dist
    FROM public.document_segments ds
    WHERE ds.embedding IS NOT NULL
      AND ds.embedding_status = 'ready'
      AND ds.is_noise = FALSE
    ORDER BY dist
    LIMIT p_k
  ) ranked
),
scores AS (
  SELECT segment_id,
         SUM(rrf) AS score
  FROM (
    SELECT b.segment_id, p_w_bm25 * (1.0 / (p_k + b.r)) AS rrf FROM bm b
    UNION ALL
    SELECT v.segment_id, p_w_vec  * (1.0 / (p_k + v.r)) AS rrf FROM vec v
  ) s
  GROUP BY segment_id
),
segments AS (
  SELECT
    d.id AS document_id,
    d.title AS document_title,
    d.source_system,
    d.updated_at AS document_updated_at,
    ds.id AS segment_id,
    ds.sequence,
    ds.source_role,
    LEFT(ds.content_markdown, 280) AS snippet,
    sc.score,
    stats.segment_count,
    stats.char_count,
    ROW_NUMBER() OVER (ORDER BY sc.score DESC) AS global_rank
  FROM scores sc
  JOIN public.document_segments ds ON ds.id = sc.segment_id
  JOIN public.document_versions dv ON dv.id = ds.document_version_id
  JOIN public.documents d ON d.id = dv.document_id
  JOIN LATERAL (
      SELECT
          COUNT(*) AS segment_count,
          COALESCE(SUM(NULLIF(length(ds_all.content_markdown), 0)), 0) AS char_count
      FROM document_segments ds_all
      WHERE ds_all.document_version_id = dv.id
  ) stats ON TRUE
  WHERE ds.embedding_status = 'ready'
    AND ds.is_noise = FALSE
),
limited_segments AS (
  SELECT *
  FROM segments, settings
  WHERE global_rank <= settings.segment_limit
),
ranked AS (
  SELECT
    *,
    ROW_NUMBER() OVER (PARTITION BY document_id ORDER BY score DESC) AS doc_rank
  FROM limited_segments
),
ranked_unique AS (
  SELECT
    document_id,
    document_title,
    source_system,
    document_updated_at,
    segment_count,
    char_count,
    segment_id,
    sequence,
    source_role,
    snippet,
    score,
    doc_rank
  FROM (
    SELECT DISTINCT ON (document_id, segment_id)
      document_id,
      document_title,
      source_system,
      document_updated_at,
      segment_count,
      char_count,
      segment_id,
      sequence,
      source_role,
      snippet,
      score,
      doc_rank
    FROM ranked
    ORDER BY document_id, segment_id, doc_rank
  ) deduped
),
doc_agg AS (
  SELECT
    document_id,
    MAX(document_title) AS document_title,
    MAX(source_system) AS source_system,
    MAX(document_updated_at) AS document_updated_at,
    MAX(segment_count) AS segment_count,
    MAX(char_count) AS char_count,
    COUNT(*) AS match_count,
    MAX(score) AS best_segment_score,
    SUM(score) FILTER (WHERE doc_rank <= p_doc_topk) AS topk_score,
    jsonb_agg(
        jsonb_build_object(
            'segment_id', segment_id,
            'sequence', sequence,
            'source_role', source_role,
            'score', score,
            'snippet', snippet
        ) ORDER BY doc_rank
    ) FILTER (WHERE doc_rank <= p_doc_top_segments) AS top_segments
  FROM ranked_unique
  GROUP BY document_id
),
scored AS (
  SELECT
    document_id,
    document_title,
    source_system,
    document_updated_at,
    segment_count,
    char_count,
    match_count,
    COALESCE(match_count::float / NULLIF(segment_count, 0), 0.0) AS match_density,
    COALESCE(best_segment_score, 0.0) AS best_segment_score,
    COALESCE(topk_score, 0.0) AS topk_score,
    COALESCE(top_segments, '[]'::jsonb) AS top_segments,
    (p_w_best * COALESCE(best_segment_score, 0.0)
      + p_w_topk * COALESCE(topk_score, 0.0)
      + p_w_density * COALESCE(match_count::float / NULLIF(segment_count, 0), 0.0)
    ) AS document_score
  FROM doc_agg
),
final AS (
  SELECT *
  FROM scored
  ORDER BY document_score DESC
  LIMIT p_limit OFFSET p_offset
),
final_agg AS (
  SELECT
    jsonb_agg(
      jsonb_build_object(
        'document_id', document_id,
        'document_title', document_title,
        'source_system', source_system,
        'document_updated_at', document_updated_at,
        'document_segment_count', segment_count,
        'document_char_count', char_count,
        'match_count', match_count,
        'match_density', match_density,
        'document_score', document_score,
        'best_segment_score', best_segment_score,
        'topk_score', topk_score,
        'top_segments', top_segments
      ) ORDER BY document_score DESC
    ) AS results,
    COUNT(*) AS result_count,
    MAX(best_segment_score) AS best_score
  FROM final
)
SELECT jsonb_build_object(
  'results', COALESCE(final_agg.results, '[]'::jsonb),
  'meta', jsonb_build_object(
      'count', COALESCE(final_agg.result_count, 0),
      'best_score', final_agg.best_score,
      'duplicate_debug', '[]'::jsonb,
      'segment_debug', '[]'::jsonb
  )
)
FROM final_agg;
$$;
