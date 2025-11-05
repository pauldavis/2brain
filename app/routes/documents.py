from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.db import get_connection
from app.schemas import DocumentSummary, DocumentView
from app.services.documents import get_document_view, list_documents


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
