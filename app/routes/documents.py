from __future__ import annotations

import re
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from app.db import get_connection
from app.schemas import DocumentSummary, DocumentTranscript, DocumentView, SegmentExport
from app.services.documents import (
    get_segment_export,
    get_document_transcript,
    get_document_view,
    list_documents,
)


router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=List[DocumentSummary])
def list_documents_endpoint(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    conn=Depends(get_connection),
) -> List[DocumentSummary]:
    """Return paginated document summaries ordered by updated_at descending."""
    return list_documents(conn, limit=limit, offset=offset)


@router.get("/{document_id}", response_model=DocumentView)
def get_document_endpoint(
    document_id: UUID,
    conn=Depends(get_connection),
) -> DocumentView:
    """Return the unified view for a single document."""
    return get_document_view(conn, document_id)


def _default_filename(title: str, suffix: str | None = None) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-") or "conversation"
    if suffix:
        return f"{slug}-{suffix}.md"
    return f"{slug}.md"


@router.get("/{document_id}/transcript", response_model=DocumentTranscript)
def get_document_transcript_endpoint(
    document_id: UUID,
    format: str = Query("json", pattern="^(json|markdown)$"),
    download: bool = Query(False),
    conn=Depends(get_connection),
):
    """Return the entire conversation as a markdown transcript or JSON payload."""
    transcript = get_document_transcript(conn, document_id)
    if format == "markdown":
        headers = {}
        if download:
            headers["Content-Disposition"] = f'attachment; filename="{_default_filename(transcript.document.title)}"'
        return PlainTextResponse(transcript.markdown, media_type="text/markdown", headers=headers)
    return transcript


@router.get("/segments/{segment_id}/export", response_model=SegmentExport)
def export_segment_endpoint(
    segment_id: UUID,
    format: str = Query("json", pattern="^(json|markdown)$"),
    download: bool = Query(False),
    conn=Depends(get_connection),
):
    """Return a single segment export."""
    payload = get_segment_export(conn, segment_id)
    if format == "markdown":
        headers = {}
        if download:
            suffix = f"segment-{payload.segment.sequence}"
            headers["Content-Disposition"] = f'attachment; filename="{_default_filename(payload.document.title, suffix)}"'
        return PlainTextResponse(payload.markdown, media_type="text/markdown", headers=headers)
    return payload
