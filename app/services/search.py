from __future__ import annotations

from typing import List, Optional
import os
from uuid import UUID

from app.schemas import (
    DocumentSearchResult,
    SearchResult,
    SearchSegmentMatch,
)

SEARCH_SQL = """
WITH params AS (
    SELECT
        %(query)s::text AS query_text,
        NULLIF(TRIM(%(query)s::text), '') AS normalized_query,
        %(source_system)s::text AS source_system_filter,
        %(source_role)s::text AS source_role_filter,
        %(document_id)s::uuid AS document_filter
),
query_cte AS (
    SELECT
        query_text,
        normalized_query,
        CASE
            WHEN normalized_query IS NULL THEN NULL
            ELSE plainto_tsquery('english', normalized_query)
        END AS ts_query
    FROM params
)
SELECT
    d.id AS document_id,
    d.title AS document_title,
    d.source_system,
    d.updated_at AS document_updated_at,
    stats.segment_count,
    stats.char_count,
    ds.id AS segment_id,
    ds.sequence,
    ds.source_role,
    CASE
        WHEN query_cte.ts_query IS NULL THEN LEFT(ds.content_markdown, 280)
        ELSE ts_headline('english', ds.content_markdown, query_cte.ts_query)
    END AS snippet,
    ds.started_at
FROM documents d
CROSS JOIN query_cte
JOIN LATERAL (
    SELECT dv.id
    FROM document_versions dv
    WHERE dv.document_id = d.id
    ORDER BY dv.ingested_at DESC
    LIMIT 1
) latest_version ON TRUE
JOIN document_segments ds ON ds.document_version_id = latest_version.id
JOIN LATERAL (
    SELECT
        COUNT(*) AS segment_count,
        COALESCE(SUM(NULLIF(length(ds_all.content_markdown), 0)), 0) AS char_count
    FROM document_segments ds_all
    WHERE ds_all.document_version_id = latest_version.id
) stats ON TRUE
WHERE (query_cte.ts_query IS NULL OR ds.content_plaintext @@ query_cte.ts_query)
  AND (query_cte.source_system_filter IS NULL OR d.source_system = query_cte.source_system_filter)
  AND (query_cte.source_role_filter IS NULL OR ds.source_role = query_cte.source_role_filter)
  AND (query_cte.document_filter IS NULL OR d.id = query_cte.document_filter)
  AND ds.is_noise = FALSE
  AND ds.embedding_status = 'ready'
ORDER BY ds.started_at NULLS LAST, ds.sequence
LIMIT %(limit)s OFFSET %(offset)s;
"""

BM25_SQL = """
WITH ranked AS (
    SELECT
        ds.id AS segment_id,
        dv.document_id AS document_id,
        d.title AS document_title,
        d.source_system AS source_system,
        d.updated_at AS document_updated_at,
        ds.sequence,
        ds.source_role,
        LEFT(ds.content_markdown, 280) AS snippet,
        ds.content_markdown <@> to_bm25query(%(q)s::text, 'document_segments_bm25_idx') AS score,
        stats.segment_count,
        stats.char_count
    FROM documents d
    JOIN LATERAL (
        SELECT dv.id, dv.document_id
        FROM document_versions dv
        WHERE dv.document_id = d.id
        ORDER BY dv.ingested_at DESC
        LIMIT 1
    ) dv ON TRUE
    JOIN document_segments ds ON ds.document_version_id = dv.id
    JOIN LATERAL (
        SELECT
            COUNT(*) AS segment_count,
            COALESCE(SUM(NULLIF(length(ds_all.content_markdown), 0)), 0) AS char_count
        FROM document_segments ds_all
        WHERE ds_all.document_version_id = dv.id
    ) stats ON TRUE
)
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
    score
FROM ranked
WHERE score < COALESCE(%(threshold)s::float8, 1e9)
ORDER BY score
LIMIT %(limit)s OFFSET %(offset)s;
"""

RRF_SQL = """
WITH bm AS (
  SELECT segment_id,
         ROW_NUMBER() OVER (ORDER BY score) AS r
  FROM (
    SELECT ds.id AS segment_id,
           ds.content_markdown <@> to_bm25query(%(q)s::text, 'document_segments_bm25_idx') AS score
    FROM public.document_segments ds
    WHERE ds.embedding_status = 'ready'
      AND ds.is_noise = FALSE
    ORDER BY score
    LIMIT %(k)s
  ) ranked
),
vec AS (
  SELECT segment_id,
         ROW_NUMBER() OVER (ORDER BY dist) AS r
  FROM (
    SELECT ds.id AS segment_id,
           ds.embedding <=> %(qvec)s::vector AS dist
    FROM public.document_segments ds
    WHERE ds.embedding IS NOT NULL
      AND ds.embedding_status = 'ready'
      AND ds.is_noise = FALSE
    ORDER BY dist
    LIMIT %(k)s
  ) ranked
),
scores AS (
  SELECT segment_id,
         SUM(rrf) AS score
  FROM (
    SELECT b.segment_id, %(w_bm25)s * (1.0 / (%(k)s + b.r)) AS rrf FROM bm b
    UNION ALL
    SELECT v.segment_id, %(w_vec)s  * (1.0 / (%(k)s + v.r)) AS rrf FROM vec v
  ) s
  GROUP BY segment_id
)
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
  stats.char_count
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
ORDER BY sc.score DESC
LIMIT %(limit)s OFFSET %(offset)s;
"""

RRF_DOCUMENT_SQL = """
WITH bm AS (
  SELECT segment_id,
         ROW_NUMBER() OVER (ORDER BY score) AS r
  FROM (
    SELECT ds.id AS segment_id,
           ds.content_markdown <@> to_bm25query(%(q)s::text, 'document_segments_bm25_idx') AS score
    FROM public.document_segments ds
    WHERE ds.embedding_status = 'ready'
      AND ds.is_noise = FALSE
    ORDER BY score
    LIMIT %(k)s
  ) ranked
),
vec AS (
  SELECT segment_id,
         ROW_NUMBER() OVER (ORDER BY dist) AS r
  FROM (
    SELECT ds.id AS segment_id,
           ds.embedding <=> %(qvec)s::vector AS dist
    FROM public.document_segments ds
    WHERE ds.embedding IS NOT NULL
      AND ds.embedding_status = 'ready'
      AND ds.is_noise = FALSE
    ORDER BY dist
    LIMIT %(k)s
  ) ranked
),
scores AS (
  SELECT segment_id,
         SUM(rrf) AS score
  FROM (
    SELECT b.segment_id, %(w_bm25)s * (1.0 / (%(k)s + b.r)) AS rrf FROM bm b
    UNION ALL
    SELECT v.segment_id, %(w_vec)s  * (1.0 / (%(k)s + v.r)) AS rrf FROM vec v
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
  FROM segments
  WHERE global_rank <= %(segment_limit)s
),
ranked AS (
  SELECT
    *,
    ROW_NUMBER() OVER (PARTITION BY document_id ORDER BY score DESC) AS doc_rank
  FROM limited_segments
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
    SUM(score) FILTER (WHERE doc_rank <= %(doc_topk)s) AS topk_score,
    JSONB_AGG(
        JSONB_BUILD_OBJECT(
            'segment_id', segment_id,
            'sequence', sequence,
            'source_role', source_role,
            'score', score,
            'snippet', snippet
        ) ORDER BY doc_rank
    ) FILTER (WHERE doc_rank <= %(doc_top_segments)s) AS top_segments
  FROM ranked
  GROUP BY document_id
)
SELECT
  document_id,
  document_title,
  source_system,
  document_updated_at,
  segment_count,
  char_count,
  match_count,
  COALESCE(topk_score, 0.0) AS topk_score,
  best_segment_score,
  COALESCE(match_count::float / NULLIF(segment_count, 0), 0.0) AS match_density,
  (
    %(w_best)s * best_segment_score
    + %(w_topk)s * COALESCE(topk_score, 0.0)
    + %(w_density)s * COALESCE(match_count::float / NULLIF(segment_count, 0), 0.0)
  ) AS document_score,
  COALESCE(top_segments, '[]'::jsonb) AS top_segments
FROM doc_agg
ORDER BY document_score DESC
LIMIT %(limit)s OFFSET %(offset)s;
"""


def search_segments(
    conn,
    *,
    query: Optional[str] = None,
    source_system: Optional[str] = None,
    source_role: Optional[str] = None,
    document_id: Optional[UUID] = None,
    limit: int = 20,
    offset: int = 0,
) -> List[SearchResult]:
    rows = conn.execute(
        SEARCH_SQL,
        {
            "query": query,
            "source_system": source_system,
            "source_role": source_role,
            "document_id": document_id,
            "limit": limit,
            "offset": offset,
        },
    ).fetchall()
    return [
        SearchResult(
            document_id=row["document_id"],
            document_title=row["document_title"],
            source_system=row["source_system"],
            document_updated_at=row["document_updated_at"],
            document_segment_count=row["segment_count"],
            document_char_count=row["char_count"],
            segment_id=row["segment_id"],
            sequence=row["sequence"],
            source_role=row["source_role"],
            snippet=row["snippet"] or "",
            started_at=row["started_at"],
        )
        for row in rows
    ]


def search_segments_bm25(
    conn,
    *,
    q: str,
    limit: int = 20,
    offset: int = 0,
    threshold: float | None = None,
) -> tuple[list[SearchResult], dict]:
    rows = conn.execute(
        BM25_SQL,
        {
            "q": q,
            "threshold": threshold,
            "limit": limit,
            "offset": offset,
        },
    ).fetchall()
    best_score = rows[0]["score"] if rows and "score" in rows[0] else None
    results = [
        SearchResult(
            document_id=row["document_id"],
            document_title=row["document_title"],
            source_system=row["source_system"],
            document_updated_at=row["document_updated_at"],
            document_segment_count=row["segment_count"],
            document_char_count=row["char_count"],
            segment_id=row["segment_id"],
            sequence=row["sequence"],
            source_role=row["source_role"],
            snippet=row["snippet"] or "",
            started_at=None,
        )
        for row in rows
    ]
    return results, {"count": len(results), "best_score": best_score}


def _format_vector_literal(vec: List[float]) -> str:
    return "[" + ", ".join(f"{x:.8f}" for x in vec) + "]"


def search_segments_hybrid_rrf(
    conn,
    *,
    q: str,
    q_embedding: List[float],
    limit: int = 20,
    offset: int = 0,
    w_bm25: float = 0.5,
    w_vec: float = 0.5,
    k: int = 60,
) -> tuple[List[SearchResult], dict]:
    rows = conn.execute(
        RRF_SQL,
        {
            "q": q,
            "qvec": _format_vector_literal(q_embedding),
            "w_bm25": w_bm25,
            "w_vec": w_vec,
            "k": k,
            "limit": limit,
            "offset": offset,
        },
    ).fetchall()
    best_score = rows[0]["score"] if rows and "score" in rows[0] else None
    return_list = [
        SearchResult(
            document_id=row["document_id"],
            document_title=row["document_title"],
            source_system=row["source_system"],
            document_updated_at=row["document_updated_at"],
            document_segment_count=row["segment_count"],
            document_char_count=row["char_count"],
            segment_id=row["segment_id"],
            sequence=row["sequence"],
            source_role=row["source_role"],
            snippet=row["snippet"] or "",
            started_at=None,
        )
        for row in rows
    ]
    return return_list, {"count": len(return_list), "best_score": best_score}


def search_documents_hybrid_rrf(
    conn,
    *,
    q: str,
    q_embedding: List[float],
    limit: int = 20,
    offset: int = 0,
    w_bm25: float = 0.5,
    w_vec: float = 0.5,
    k: int = 60,
    doc_topk: int = 3,
    doc_top_segments: int = 3,
    segment_limit: Optional[int] = None,
    doc_score_w_best: float = 0.6,
    doc_score_w_topk: float = 0.3,
    doc_score_w_density: float = 0.1,
) -> tuple[List[DocumentSearchResult], dict]:
    segment_limit = segment_limit or max(limit * max(doc_topk, doc_top_segments), 50)
    rows = conn.execute(
        RRF_DOCUMENT_SQL,
        {
            "q": q,
            "qvec": _format_vector_literal(q_embedding),
            "w_bm25": w_bm25,
            "w_vec": w_vec,
            "k": k,
            "segment_limit": segment_limit,
            "doc_topk": doc_topk,
            "doc_top_segments": doc_top_segments,
            "w_best": doc_score_w_best,
            "w_topk": doc_score_w_topk,
            "w_density": doc_score_w_density,
            "limit": limit,
            "offset": offset,
        },
    ).fetchall()
    results: List[DocumentSearchResult] = []
    for row in rows:
        top_segments_raw = row["top_segments"] or []
        segment_matches = [
            SearchSegmentMatch(
                segment_id=segment["segment_id"],
                sequence=int(segment["sequence"]),
                source_role=segment["source_role"],
                score=float(segment["score"]),
                snippet=segment.get("snippet") or "",
            )
            for segment in top_segments_raw
        ]
        results.append(
            DocumentSearchResult(
                document_id=row["document_id"],
                document_title=row["document_title"],
                source_system=row["source_system"],
                document_updated_at=row["document_updated_at"],
                document_segment_count=row["segment_count"],
                document_char_count=row["char_count"],
                match_count=row["match_count"],
                match_density=float(row["match_density"] or 0.0),
                document_score=float(row["document_score"] or 0.0),
                best_segment_score=float(row["best_segment_score"] or 0.0),
                topk_score=float(row["topk_score"] or 0.0),
                top_segments=segment_matches,
            )
        )
    best_score = rows[0]["best_segment_score"] if rows else None
    return results, {"count": len(results), "best_score": best_score}


def embed_query_openai(text: str, *, model: str = "text-embedding-3-small") -> List[float]:
    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "openai package not available. Install `openai>=1.0` to embed queries."
        ) from e

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set in environment")

    client = OpenAI(api_key=api_key)
    resp = client.embeddings.create(model=model, input=text)
    emb = resp.data[0].embedding
    return [float(x) for x in emb]
