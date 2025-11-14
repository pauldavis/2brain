from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status

ATTACHMENT_SQL = """
SELECT
    id,
    file_name,
    mime_type,
    size_bytes,
    content
FROM attachments
WHERE id = %(attachment_id)s
"""


def get_attachment(conn, attachment_id: UUID):
    row = conn.execute(ATTACHMENT_SQL, {"attachment_id": attachment_id}).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    if row["content"] is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment content unavailable")
    return row
