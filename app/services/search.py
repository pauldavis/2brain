from __future__ import annotations

from typing import List, Optional
import os
from uuid import UUID

from app.schemas import SearchResult

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
        ds.sequence,
        ds.source_role,
        LEFT(ds.content_markdown, 280) AS snippet,
        ds.content_markdown <@> to_bm25query(%(q)s::text, 'document_segments_bm25_idx') AS score
    FROM documents d
    JOIN LATERAL (
        SELECT dv.id, dv.document_id
        FROM document_versions dv
        WHERE dv.document_id = d.id
        ORDER BY dv.ingested_at DESC
        LIMIT 1
    ) dv ON TRUE
    JOIN document_segments ds ON ds.document_version_id = dv.id
)
SELECT
    document_id,
    document_title,
    source_system,
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
  SELECT ds.id AS segment_id,
         ROW_NUMBER() OVER (
           ORDER BY ds.content_markdown <@> to_bm25query(%(q)s::text, 'document_segments_bm25_idx')
         ) AS r
  FROM public.document_segments ds
),
vec AS (
  SELECT ds.id AS segment_id,
         ROW_NUMBER() OVER (
           ORDER BY ds.embedding <=> %(qvec)s::vector
         ) AS r
  FROM public.document_segments ds
  WHERE ds.embedding IS NOT NULL
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
  ds.id AS segment_id,
  ds.sequence,
  ds.source_role,
  LEFT(ds.content_markdown, 280) AS snippet,
  sc.score
FROM scores sc
JOIN public.document_segments ds ON ds.id = sc.segment_id
JOIN public.document_versions dv ON dv.id = ds.document_version_id
JOIN public.documents d ON d.id = dv.document_id
ORDER BY sc.score DESC
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
            segment_id=row["segment_id"],
            sequence=row["sequence"],
            source_role=row["source_role"],
            snippet=row["snippet"] or "",
            started_at=None,
        )
        for row in rows
    ]
    return return_list, {"count": len(return_list), "best_score": best_score}


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
