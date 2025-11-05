from __future__ import annotations

from typing import List, Optional
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
