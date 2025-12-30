from __future__ import annotations

import time
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.db import get_connection
from app.metrics import log_query_stat
from app.schemas import DocumentSearchResult, SearchResult
from app.services.search import (
    embed_query_openai,
    search_documents_hybrid_rrf,
    search_segments,
    search_segments_bm25,
    search_segments_hybrid_rrf,
)

router = APIRouter(tags=["search"])


@router.get("/search", response_model=List[SearchResult])
def search_endpoint(
    query: Optional[str] = Query(
        None, description="Full-text query applied to segment content."
    ),
    source_system: Optional[str] = Query(
        None, description="Filter by source system (chatgpt, claude, other)."
    ),
    source_role: Optional[str] = Query(
        None, description="Filter by segment role (user, assistant, etc.)."
    ),
    document_id: Optional[UUID] = Query(
        None, description="Restrict results to a single document id."
    ),
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


@router.get("/search/bm25", response_model=List[SearchResult])
def search_bm25_endpoint(
    q: str = Query(..., description="BM25 keyword query"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    threshold: float | None = Query(
        None, description="Optional score cutoff; lower (more negative) is better."
    ),
    conn=Depends(get_connection),
) -> List[SearchResult]:
    t0 = time.perf_counter()
    results, meta = search_segments_bm25(
        conn,
        q=q,
        limit=limit,
        offset=offset,
        threshold=threshold,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    log_query_stat(
        {
            "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "mode": "bm25",
            "q": q,
            "count": meta.get("count"),
            "best_score": meta.get("best_score"),
            "threshold": threshold,
            "elapsed_ms": round(elapsed_ms, 2),
        }
    )
    return results


@router.get("/search/hybrid", response_model=List[SearchResult])
def search_hybrid_endpoint(
    q: str = Query(..., description="Free-form query; embedded via OpenAI"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    w_bm25: float = Query(0.5, ge=0.0, le=1.0),
    w_vec: float = Query(0.5, ge=0.0, le=1.0),
    k: int = Query(60, ge=1),
    conn=Depends(get_connection),
) -> List[SearchResult]:
    qvec = embed_query_openai(q, conn=conn)
    t0 = time.perf_counter()
    results, meta = search_segments_hybrid_rrf(
        conn,
        q=q,
        q_embedding=qvec,
        limit=limit,
        offset=offset,
        w_bm25=w_bm25,
        w_vec=w_vec,
        k=k,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    log_query_stat(
        {
            "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "mode": "hybrid",
            "q": q,
            "count": meta.get("count"),
            "best_score": meta.get("best_score"),
            "w_bm25": w_bm25,
            "w_vec": w_vec,
            "k": k,
            "elapsed_ms": round(elapsed_ms, 2),
        }
    )
    return results


@router.get("/search/hybrid_documents", response_model=List[DocumentSearchResult])
def search_hybrid_documents_endpoint(
    q: str = Query(..., description="Free-form query aggregated to documents."),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    w_bm25: float = Query(0.5, ge=0.0, le=1.0),
    w_vec: float = Query(0.5, ge=0.0, le=1.0),
    k: int = Query(60, ge=1),
    doc_topk: int = Query(
        3, ge=1, le=10, description="How many top segments contribute to doc score."
    ),
    doc_top_segments: int = Query(
        3, ge=1, le=10, description="How many segment previews to return."
    ),
    segment_limit: Optional[int] = Query(
        None,
        ge=10,
        description="Optional override for number of ranked segments considered before aggregation.",
    ),
    conn=Depends(get_connection),
) -> List[DocumentSearchResult]:
    qvec = embed_query_openai(q, conn=conn)
    t0 = time.perf_counter()
    results, meta = search_documents_hybrid_rrf(
        conn,
        q=q,
        q_embedding=qvec,
        limit=limit,
        offset=offset,
        w_bm25=w_bm25,
        w_vec=w_vec,
        k=k,
        doc_topk=doc_topk,
        doc_top_segments=doc_top_segments,
        segment_limit=segment_limit,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    log_query_stat(
        {
            "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "mode": "hybrid_documents",
            "q": q,
            "count": meta.get("count"),
            "best_score": meta.get("best_score"),
            "w_bm25": w_bm25,
            "w_vec": w_vec,
            "k": k,
            "doc_topk": doc_topk,
            "doc_top_segments": doc_top_segments,
            "segment_limit": segment_limit,
            "elapsed_ms": round(elapsed_ms, 2),
        }
    )
    return results


@router.get("/search/hybrid_documents_debug")
def search_hybrid_documents_debug_endpoint(
    q: str = Query(..., description="Free-form query aggregated to documents."),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    w_bm25: float = Query(0.5, ge=0.0, le=1.0),
    w_vec: float = Query(0.5, ge=0.0, le=1.0),
    k: int = Query(60, ge=1),
    doc_topk: int = Query(3, ge=1, le=10),
    doc_top_segments: int = Query(3, ge=1, le=10),
    segment_limit: Optional[int] = Query(None, ge=10),
    conn=Depends(get_connection),
):
    qvec = embed_query_openai(q, conn=conn)
    results, meta = search_documents_hybrid_rrf(
        conn,
        q=q,
        q_embedding=qvec,
        limit=limit,
        offset=offset,
        w_bm25=w_bm25,
        w_vec=w_vec,
        k=k,
        doc_topk=doc_topk,
        doc_top_segments=doc_top_segments,
        segment_limit=segment_limit,
    )
    return {"results": results, "meta": meta}
