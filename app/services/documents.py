from __future__ import annotations

from datetime import datetime, timezone
from typing import List
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import ValidationError

from app.schemas import (
    Document,
    DocumentTranscript,
    DocumentSummary,
    DocumentVersion,
    DocumentView,
    Segment,
    SegmentExport,
)

DOCUMENT_VIEW_JSON_SQL = """
SELECT api.document_view_json(%(document_id)s) AS payload;
"""

DOCUMENT_LIST_SQL = """
SELECT
    d.id,
    d.title,
    d.source_system,
    d.created_at,
    d.updated_at,
    COUNT(ds.id) AS segment_count,
    COALESCE(SUM(char_length(COALESCE(ds.content_markdown, ''))), 0) AS char_count
FROM documents d
JOIN LATERAL (
    SELECT dv.id
    FROM document_versions dv
    WHERE dv.document_id = d.id
    ORDER BY dv.ingested_at DESC
    LIMIT 1
) latest_version ON TRUE
LEFT JOIN document_segments ds ON ds.document_version_id = latest_version.id
GROUP BY d.id, d.title, d.source_system, d.created_at, d.updated_at
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
    row = conn.execute(DOCUMENT_VIEW_JSON_SQL, {"document_id": document_id}).fetchone()
    payload = row["payload"] if row else None
    if not payload:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    try:
        return DocumentView.model_validate(payload)
    except ValidationError as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Invalid document payload") from exc


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
            char_count=row["char_count"],
        )
        for row in rows
    ]


def _render_transcript_markdown(document_view: DocumentView) -> str:
    document = document_view.document
    version = document_view.version
    segments = document_view.segments

    def _format_ts(value):
        return value.isoformat() if value else "—"

    lines: List[str] = [
        f"# {document.title}",
        "",
        f"- Source system: {document.source_system}",
        f"- External ID: {document.external_id}",
        f"- Segment count: {len(segments)}",
        f"- Created at: {document.created_at.isoformat()}",
        f"- Updated at: {document.updated_at.isoformat()}",
        f"- Last ingested at: {version.ingested_at.isoformat()}",
        "",
        "---",
        "",
    ]

    for index, segment in enumerate(segments, start=1):
        role = segment.source_role.capitalize()
        header = f"## Segment {index} · {role} ({segment.segment_type})"
        lines.append(header)
        lines.append("")
        lines.append(f"- Started: {_format_ts(segment.started_at)}")
        lines.append(f"- Ended: {_format_ts(segment.ended_at)}")
        if segment.raw_reference:
            lines.append(f"- Raw reference: {segment.raw_reference}")
        lines.append("")
        body = segment.content_markdown or ""
        if body:
            lines.append(body)
            lines.append("")
        if segment.blocks and len(segment.blocks) > 1:
            for block in segment.blocks:
                block_header = f"### Block {block.sequence} · {block.block_type}"
                lines.append(block_header)
                if block.language:
                    lines.append(f"_Language: {block.language}_")
                if block.body:
                    lines.append("")
                    lines.append(block.body)
                    lines.append("")
        if segment.assets:
            lines.append("### Attachments")
            for asset in segment.assets:
                parts = [asset.file_name or "Unnamed asset"]
                if asset.mime_type:
                    parts.append(asset.mime_type)
                if asset.size_bytes:
                    parts.append(f"{asset.size_bytes} bytes")
                lines.append(f"- {' · '.join(parts)}")
            lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def get_document_transcript(conn, document_id: UUID) -> DocumentTranscript:
    document_view = get_document_view(conn, document_id)
    markdown = _render_transcript_markdown(document_view)
    return DocumentTranscript(
        document=document_view.document,
        version=document_view.version,
        segment_count=len(document_view.segments),
        generated_at=datetime.now(timezone.utc),
        markdown=markdown,
    )


SEGMENT_EXPORT_SQL = """
SELECT
    d.id AS document_id,
    d.source_system,
    d.external_id,
    d.title,
    d.summary,
    d.created_at,
    d.updated_at,
    d.raw_metadata,
    dv.id AS version_id,
    dv.ingested_at,
    dv.source_path,
    dv.checksum,
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
JOIN document_versions dv ON dv.id = ds.document_version_id
JOIN documents d ON d.id = dv.document_id
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
            'attachment_id', att.id,
            'file_name', att.file_name,
            'mime_type', att.mime_type,
            'size_bytes', att.size_bytes,
            'created_at', sa.created_at,
            'has_content', att.content IS NOT NULL
        ) ORDER BY sa.created_at, sa.id
    ) AS assets
    FROM segment_assets sa
    JOIN attachments att ON att.id = sa.attachment_id
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
WHERE ds.id = %(segment_id)s;
"""


def _render_segment_markdown(document: Document, segment: Segment) -> str:
    def _format_ts(value):
        return value.isoformat() if value else "—"

    lines: List[str] = [
        f"# {document.title} — Segment {segment.sequence}",
        "",
        f"- Document source: {document.source_system}",
        f"- Segment role: {segment.source_role}",
        f"- Segment type: {segment.segment_type}",
        f"- Started: {_format_ts(segment.started_at)}",
        f"- Ended: {_format_ts(segment.ended_at)}",
    ]
    if segment.raw_reference:
        lines.append(f"- Raw reference: {segment.raw_reference}")
    lines.append("")
    body = segment.content_markdown or ""
    if body:
        lines.append(body)
        lines.append("")
    if segment.blocks and len(segment.blocks) > 1:
        for block in segment.blocks:
            block_header = f"## Block {block.sequence} · {block.block_type}"
            lines.append(block_header)
            if block.language:
                lines.append(f"_Language: {block.language}_")
            if block.body:
                lines.append("")
                lines.append(block.body)
                lines.append("")
    if segment.assets:
        lines.append("## Attachments")
        for asset in segment.assets:
            parts = [asset.file_name or "Unnamed asset"]
            if asset.mime_type:
                parts.append(asset.mime_type)
            if asset.size_bytes:
                parts.append(f"{asset.size_bytes} bytes")
            lines.append(f"- {' · '.join(parts)}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def get_segment_export(conn, segment_id: UUID) -> SegmentExport:
    row = conn.execute(SEGMENT_EXPORT_SQL, {"segment_id": segment_id}).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")

    document = Document(
        id=row["document_id"],
        source_system=row["source_system"],
        external_id=row["external_id"],
        title=row["title"],
        summary=row["summary"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        raw_metadata=row["raw_metadata"] or {},
    )
    version = DocumentVersion(
        id=row["version_id"],
        document_id=row["document_id"],
        ingested_at=row["ingested_at"],
        source_path=row["source_path"],
        checksum=_checksum_hex(row["checksum"]),
    )
    segment = Segment(
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
    markdown = _render_segment_markdown(document, segment)
    return SegmentExport(
        document=document,
        version=version,
        segment=segment,
        generated_at=datetime.now(timezone.utc),
        markdown=markdown,
    )
