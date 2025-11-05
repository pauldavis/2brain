from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import HTTPException, status

from app.schemas import (
    Document,
    DocumentSummary,
    DocumentVersion,
    DocumentView,
    Keyword,
    Segment,
)

DOCUMENT_SQL = """
WITH latest_version AS (
    SELECT dv.*
    FROM document_versions dv
    WHERE dv.document_id = %(document_id)s
    ORDER BY dv.ingested_at DESC
    LIMIT 1
)
SELECT
    d.id AS document_id,
    d.source_system,
    d.external_id,
    d.title,
    d.summary,
    d.created_at,
    d.updated_at,
    d.raw_metadata,
    lv.id AS version_id,
    lv.document_id,
    lv.ingested_at,
    lv.source_path,
    lv.checksum
FROM documents d
JOIN latest_version lv ON lv.document_id = d.id
WHERE d.id = %(document_id)s;
"""

SEGMENTS_SQL = """
SELECT
    ds.id,
    ds.parent_segment_id,
    ds.sequence,
    ds.source_role,
    ds.segment_type,
    ds.content_markdown,
    ds.content_json,
    ds.started_at,
    ds.ended_at,
    ds.raw_reference,
    COALESCE(blocks.blocks, '[]'::jsonb) AS blocks,
    COALESCE(assets.assets, '[]'::jsonb) AS assets,
    COALESCE(annotations.annotations, '[]'::jsonb) AS annotations
FROM document_segments ds
LEFT JOIN LATERAL (
    SELECT jsonb_agg(
        jsonb_build_object(
            'id', sb.id,
            'sequence', sb.sequence,
            'block_type', sb.block_type,
            'language', sb.language,
            'body', sb.body,
            'raw_data', sb.raw_data
        ) ORDER BY sb.sequence
    ) AS blocks
    FROM segment_blocks sb
    WHERE sb.segment_id = ds.id
) AS blocks ON TRUE
LEFT JOIN LATERAL (
    SELECT jsonb_agg(
        jsonb_build_object(
            'id', sa.id,
            'asset_type', sa.asset_type,
            'file_name', sa.file_name,
            'mime_type', sa.mime_type,
            'size_bytes', sa.size_bytes,
            'local_path', sa.local_path,
            'source_reference', sa.source_reference,
            'created_at', sa.created_at
        ) ORDER BY sa.created_at, sa.id
    ) AS assets
    FROM segment_assets sa
    WHERE sa.segment_id = ds.id
) AS assets ON TRUE
LEFT JOIN LATERAL (
    SELECT jsonb_agg(
        jsonb_build_object(
            'id', an.id,
            'annotation_type', an.annotation_type,
            'payload', an.payload,
            'created_at', an.created_at
        ) ORDER BY an.created_at, an.id
    ) AS annotations
    FROM segment_annotations an
    WHERE an.segment_id = ds.id
) AS annotations ON TRUE
WHERE ds.document_version_id = %(version_id)s
ORDER BY ds.parent_segment_id NULLS FIRST, ds.sequence;
"""

KEYWORDS_SQL = """
SELECT jsonb_agg(
    jsonb_build_object(
        'id', k.id,
        'term', k.term,
        'description', k.description,
        'document_keyword_id', dk.id
    ) ORDER BY k.term
) AS keywords
FROM document_keywords dk
JOIN keywords k ON k.id = dk.keyword_id
WHERE dk.document_id = %(document_id)s;
"""

DOCUMENT_LIST_SQL = """
SELECT
    d.id,
    d.title,
    d.source_system,
    d.created_at,
    d.updated_at,
    COUNT(ds.id) AS segment_count
FROM documents d
JOIN document_versions dv ON dv.document_id = d.id
LEFT JOIN document_segments ds ON ds.document_version_id = dv.id
GROUP BY d.id
ORDER BY d.updated_at DESC
LIMIT %(limit)s OFFSET %(offset)s;
"""


def _checksum_hex(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    # psycopg returns memoryview for bytea
    if hasattr(value, "tobytes"):
        return value.tobytes().hex()
    return str(value)


def get_document_view(conn, document_id: UUID) -> DocumentView:
    doc_row = conn.execute(DOCUMENT_SQL, {"document_id": document_id}).fetchone()
    if not doc_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    version_id = doc_row["version_id"]
    segment_rows = conn.execute(SEGMENTS_SQL, {"version_id": version_id}).fetchall()
    keyword_row = conn.execute(KEYWORDS_SQL, {"document_id": document_id}).fetchone()

    document = Document(
        id=doc_row["document_id"],
        source_system=doc_row["source_system"],
        external_id=doc_row["external_id"],
        title=doc_row["title"],
        summary=doc_row["summary"],
        created_at=doc_row["created_at"],
        updated_at=doc_row["updated_at"],
        raw_metadata=doc_row["raw_metadata"] or {},
    )

    version = DocumentVersion(
        id=doc_row["version_id"],
        document_id=doc_row["document_id"],
        ingested_at=doc_row["ingested_at"],
        source_path=doc_row["source_path"],
        checksum=_checksum_hex(doc_row["checksum"]),
    )

    segments: List[Segment] = []
    for row in segment_rows:
        segments.append(
            Segment(
                id=row["id"],
                parent_segment_id=row["parent_segment_id"],
                sequence=row["sequence"],
                source_role=row["source_role"],
                segment_type=row["segment_type"],
                content_markdown=row["content_markdown"],
                content_json=row["content_json"],
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                raw_reference=row["raw_reference"],
                blocks=row["blocks"] or [],
                assets=row["assets"] or [],
                annotations=row["annotations"] or [],
            )
        )

    keywords_payload = keyword_row["keywords"] if keyword_row else None
    keywords = [Keyword(**item) for item in keywords_payload or []]

    return DocumentView(
        document=document,
        version=version,
        segments=segments,
        keywords=keywords,
    )


def list_documents(conn, limit: int = 20, offset: int = 0) -> List[DocumentSummary]:
    rows = conn.execute(DOCUMENT_LIST_SQL, {"limit": limit, "offset": offset}).fetchall()
    return [
        DocumentSummary(
            id=row["id"],
            title=row["title"],
            source_system=row["source_system"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            segment_count=row["segment_count"],
        )
        for row in rows
    ]
