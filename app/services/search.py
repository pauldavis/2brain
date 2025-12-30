from __future__ import annotations

import logging
import os
import time
import traceback
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from app.config import get_settings
from app.schemas import (
    DocumentSearchResult,
    SearchResult,
)

logger = logging.getLogger(__name__)


def _parse_pgvector_text(value: object) -> List[float]:
    """
    Parse pgvector values that may come back as:
      - a Python sequence of numbers (ideal)
      - a string like "[1,2,3]" (common without pgvector psycopg adapters)
    """
    if value is None:
        raise ValueError("embedding value is None")

    # If it's already a sequence of numeric types, coerce to floats.
    if isinstance(value, (list, tuple)):
        return [float(x) for x in value]

    if isinstance(value, str):
        s = value.strip()
        # pgvector text format is typically: [0.1,0.2,...]
        if s.startswith("[") and s.endswith("]"):
            s = s[1:-1].strip()
        if not s:
            return []
        return [float(x.strip()) for x in s.split(",") if x.strip()]

    # Some drivers may return other sequence-like types; try iterating.
    try:
        return [float(x) for x in value]  # type: ignore[arg-type]
    except Exception as e:
        raise ValueError(
            f"Unsupported embedding value type: {type(value).__name__}"
        ) from e


# -----------------------------------------------------------------------------
# In-memory embedding cache (TTL)
# -----------------------------------------------------------------------------
# This avoids repeated OpenAI embedding calls for the same query within a single
# server process (perfect for interactive search refinement).
#
# Controls:
# - EMBED_CACHE_MAX: maximum entries (default 1024)
# - EMBED_CACHE_TTL_SECONDS: TTL per entry (default 3600 seconds)
#
# Notes:
# - Process-local only; clears on restart.
# - Simple eviction: if full, drop the oldest entry by insertion time.
# -----------------------------------------------------------------------------
_EMBED_CACHE: Dict[Tuple[str, str], Tuple[float, List[float]]] = {}
_EMBED_CACHE_ORDER: List[Tuple[str, str]] = []

# -----------------------------------------------------------------------------
# Persistent embedding cache (Postgres)
# -----------------------------------------------------------------------------
# If QUERY_EMBED_CACHE_DB=1, the service will:
# 1) look up (model, normalized_query) in public.query_embedding_cache
# 2) if present and not expired, return it (and update last_used_at/use_count)
# 3) otherwise call OpenAI, then upsert the embedding into the cache table
#
# Requires migration 0009_query_embedding_cache.sql to have been applied.
# Controls:
# - QUERY_EMBED_CACHE_DB: enable DB cache (default off)
# - QUERY_EMBED_CACHE_TTL_SECONDS: TTL for DB entries (default 7 days)
# -----------------------------------------------------------------------------

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
            ELSE websearch_to_tsquery('english', normalized_query)
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
WITH q AS (
    SELECT websearch_to_tsquery('english', %(q)s::text) AS tsq
),
ranked AS (
    SELECT
        ds.id AS segment_id,
        dv.document_id AS document_id,
        d.title AS document_title,
        d.source_system AS source_system,
        d.updated_at AS document_updated_at,
        ds.sequence,
        ds.source_role,
        LEFT(ds.content_markdown, 280) AS snippet,
        ts_rank(ds.content_plaintext, q.tsq) AS score,
        stats.segment_count,
        stats.char_count
    FROM q
    JOIN documents d ON TRUE
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
    WHERE ds.content_plaintext @@ q.tsq
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
WHERE score > COALESCE(%(threshold)s::float8, 0.0)
ORDER BY score DESC
LIMIT %(limit)s OFFSET %(offset)s;
"""

RRF_SQL = """
WITH q AS (
  SELECT websearch_to_tsquery('english', %(q)s::text) AS tsq
),
bm AS (
  SELECT segment_id,
         ROW_NUMBER() OVER (ORDER BY score DESC) AS r
  FROM (
    SELECT ds.id AS segment_id,
           ts_rank(ds.content_plaintext, q.tsq) AS score
    FROM q
    JOIN public.document_segments ds ON TRUE
    WHERE ds.embedding_status = 'ready'
      AND ds.is_noise = FALSE
      AND ds.content_plaintext @@ q.tsq
    ORDER BY score DESC
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

HYBRID_DOCS_JSON_SQL = """
SELECT api.search_hybrid_documents_json(
    %(q)s::text,
    %(qvec)s::vector,
    %(w_bm25)s::double precision,
    %(w_vec)s::double precision,
    %(k)s::integer,
    %(limit)s::integer,
    %(offset)s::integer,
    %(doc_topk)s::integer,
    %(doc_top_segments)s::integer,
    %(segment_limit)s::integer,
    %(w_best)s::double precision,
    %(w_topk)s::double precision,
    %(w_density)s::double precision
) AS payload;
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
    row = conn.execute(
        HYBRID_DOCS_JSON_SQL,
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
    ).fetchone()
    payload = row["payload"] if row else None
    results = payload.get("results", []) if isinstance(payload, dict) else []
    meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
    return results, {
        "count": meta.get("count", 0),
        "best_score": meta.get("best_score"),
        "duplicate_debug": meta.get("duplicate_debug", []),
        "segment_debug": meta.get("segment_debug", []),
    }


def embed_query_openai(
    text: str, *, model: str = "text-embedding-3-small", conn=None
) -> List[float]:
    """
    Embed the given query text using OpenAI.

    Caching layers:
    1) In-memory TTL cache (fast, per-process)
    2) Optional Postgres-backed cache (persistent across restarts) if:
       - QUERY_EMBED_CACHE_DB=1
       - a DB connection is provided via `conn`
       - and public.query_embedding_cache exists (migration 0009)

    Timing instrumentation:
    - If EMBED_TIMING_LOG=1, logs:
      - in-memory hit/miss
      - db hit/miss (when enabled)
      - input length
      - elapsed time for the OpenAI embeddings call
    """
    # Normalize query for caching (trim + collapse whitespace)
    normalized = " ".join((text or "").strip().split())
    cache_key = (model, normalized)

    log_timing = os.environ.get("EMBED_TIMING_LOG", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    # In-memory cache settings
    try:
        cache_max = int(os.environ.get("EMBED_CACHE_MAX", "1024").strip() or "1024")
    except ValueError:
        cache_max = 1024

    try:
        ttl_seconds = int(
            os.environ.get("EMBED_CACHE_TTL_SECONDS", "3600").strip() or "3600"
        )
    except ValueError:
        ttl_seconds = 3600

    now = time.time()

    # Fast path: in-memory cache hit (and not expired)
    cached = _EMBED_CACHE.get(cache_key)
    if cached is not None:
        expires_at, vec = cached
        if expires_at > now:
            if log_timing:
                logger.info(
                    "[embed_cache] hit layer=mem model=%s chars=%d",
                    model,
                    len(normalized),
                )
            return vec
        # expired
        _EMBED_CACHE.pop(cache_key, None)
        try:
            _EMBED_CACHE_ORDER.remove(cache_key)
        except ValueError:
            pass

    if log_timing:
        logger.info(
            "[embed_cache] miss layer=mem model=%s chars=%d", model, len(normalized)
        )

    # Optional: Postgres-backed cache
    use_db_cache = os.environ.get("QUERY_EMBED_CACHE_DB", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if use_db_cache and conn is not None and normalized:
        try:
            # NOTE: expires_at is timestamptz; compare against NOW() in SQL.
            row = conn.execute(
                """
                SELECT embedding, expires_at
                FROM public.query_embedding_cache
                WHERE model = %(model)s
                  AND query_sha256 = digest(%(q)s::text, 'sha256')
                  AND (expires_at IS NULL OR expires_at > now())
                """,
                {"model": model, "q": normalized},
            ).fetchone()

            if row is not None:
                # best-effort usage tracking
                conn.execute(
                    """
                    UPDATE public.query_embedding_cache
                    SET last_used_at = now(),
                        use_count = use_count + 1
                    WHERE model = %(model)s
                      AND query_sha256 = digest(%(q)s::text, 'sha256')
                    """,
                    {"model": model, "q": normalized},
                )
                # Persist usage counters in the cache table.
                conn.commit()

                # pgvector may come back as either a sequence of numbers or a text value like "[...]"
                emb = _parse_pgvector_text(row["embedding"])

                # also warm in-memory cache
                if ttl_seconds > 0 and cache_max > 0:
                    mem_expires_at = now + ttl_seconds
                    while len(_EMBED_CACHE_ORDER) >= cache_max and _EMBED_CACHE_ORDER:
                        oldest = _EMBED_CACHE_ORDER.pop(0)
                        _EMBED_CACHE.pop(oldest, None)
                    _EMBED_CACHE[cache_key] = (mem_expires_at, emb)
                    _EMBED_CACHE_ORDER.append(cache_key)

                if log_timing:
                    logger.info(
                        "[embed_cache] hit layer=db model=%s chars=%d",
                        model,
                        len(normalized),
                    )
                return emb

            if log_timing:
                logger.info(
                    "[embed_cache] miss layer=db model=%s chars=%d",
                    model,
                    len(normalized),
                )
        except Exception as e:
            if log_timing:
                logger.info(
                    "[embed_cache] db_error %s\n%s",
                    repr(e),
                    traceback.format_exc(),
                )

    # Fall back to OpenAI
    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "openai package not available. Install `openai>=1.0` to embed queries."
        ) from e

    api_key = get_settings().openai_api_key
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set in environment")

    client = OpenAI(api_key=api_key)
    t0 = time.perf_counter()
    resp = client.embeddings.create(model=model, input=normalized)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    emb = [float(x) for x in resp.data[0].embedding]

    # Store in Postgres cache (best effort)
    if use_db_cache and conn is not None and normalized:
        try:
            try:
                db_ttl_seconds = int(
                    os.environ.get("QUERY_EMBED_CACHE_TTL_SECONDS", "604800").strip()
                    or "604800"
                )
            except ValueError:
                db_ttl_seconds = 604800

            # Store as timestamptz in the DB directly.
            conn.execute(
                """
                INSERT INTO public.query_embedding_cache (
                    query_text,
                    query_sha256,
                    model,
                    embedding,
                    provider,
                    dims,
                    created_at,
                    last_used_at,
                    use_count,
                    expires_at
                )
                VALUES (
                    %(q)s::text,
                    digest(%(q)s::text, 'sha256'),
                    %(model)s::text,
                    %(embedding)s::vector,
                    'openai',
                    %(dims)s::integer,
                    now(),
                    now(),
                    1,
                    CASE
                        WHEN %(ttl_seconds)s::integer <= 0 THEN NULL
                        ELSE now() + make_interval(secs => %(ttl_seconds)s::integer)
                    END
                )
                ON CONFLICT (model, query_sha256) DO UPDATE
                SET embedding = EXCLUDED.embedding,
                    dims = EXCLUDED.dims,
                    last_used_at = now(),
                    use_count = public.query_embedding_cache.use_count + 1,
                    expires_at = EXCLUDED.expires_at
                """,
                {
                    "q": normalized,
                    "model": model,
                    "embedding": "[" + ",".join(str(x) for x in emb) + "]",
                    "dims": len(emb),
                    "ttl_seconds": db_ttl_seconds,
                },
            )
            # Persist the cache entry. psycopg defaults to autocommit=False, so without
            # an explicit commit the insert/update would be rolled back on connection close.
            conn.commit()

            if log_timing:
                logger.info(
                    "[embed_cache] stored layer=db model=%s chars=%d ttl_seconds=%d",
                    model,
                    len(normalized),
                    db_ttl_seconds,
                )
        except Exception as e:
            if log_timing:
                logger.info(
                    "[embed_cache] db_store_error %s\n%s",
                    repr(e),
                    traceback.format_exc(),
                )

    # Store in in-memory cache (TTL)
    if ttl_seconds > 0 and cache_max > 0 and normalized:
        expires_at = now + ttl_seconds
        while len(_EMBED_CACHE_ORDER) >= cache_max and _EMBED_CACHE_ORDER:
            oldest = _EMBED_CACHE_ORDER.pop(0)
            _EMBED_CACHE.pop(oldest, None)
        _EMBED_CACHE[cache_key] = (expires_at, emb)
        _EMBED_CACHE_ORDER.append(cache_key)

    if log_timing:
        logger.info(
            "[embed] model=%s chars=%d elapsed_ms=%.2f",
            model,
            len(normalized),
            elapsed_ms,
        )

    return emb
