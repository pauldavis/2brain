from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.db import get_connection
from app.schemas import SearchResult
from app.services.search import search_segments


router = APIRouter(tags=["search"])


@router.get("/search", response_model=List[SearchResult])
def search_endpoint(
    query: Optional[str] = Query(None, description="Full-text query applied to segment content."),
    source_system: Optional[str] = Query(None, description="Filter by source system (chatgpt, claude, other)."),
    source_role: Optional[str] = Query(None, description="Filter by segment role (user, assistant, etc.)."),
    document_id: Optional[UUID] = Query(None, description="Restrict results to a single document id."),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    conn=Depends(get_connection),
) -> List[SearchResult]:
    """Search document segments using PostgreSQL full-text search."""
    return search_segments(
        conn,
        query=query,
        source_system=source_system,
        source_role=source_role,
        document_id=document_id,
        limit=limit,
        offset=offset,
    )
