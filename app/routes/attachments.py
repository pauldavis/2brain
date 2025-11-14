from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.db import get_connection
from app.services.attachments import get_attachment


router = APIRouter(prefix="/attachments", tags=["attachments"])


@router.get("/{attachment_id}")
def get_attachment_content(
    attachment_id: UUID,
    download: bool = Query(False),
    conn=Depends(get_connection),
):
    """Return the raw bytes for an attachment."""
    record = get_attachment(conn, attachment_id)
    content = record["content"]
    media_type = record["mime_type"] or "application/octet-stream"
    headers = {}
    if download and record["file_name"]:
        headers["Content-Disposition"] = f'attachment; filename="{record["file_name"]}"'
    return Response(content=content, media_type=media_type, headers=headers)
