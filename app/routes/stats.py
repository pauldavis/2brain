from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from app.db import get_connection
from app.metrics import get_query_stats


router = APIRouter(tags=["stats"])


@router.get("/stats/vectorizer")
def stats_vectorizer(conn=Depends(get_connection)) -> Dict[str, Any]:
    data: Dict[str, Any] = {"ok": True}
    try:
        vs = conn.execute("SELECT * FROM ai.vectorizer_status").fetchall()
        rows = [dict(r) for r in vs]
        data["vectorizers"] = rows
        if rows:
            name = rows[0]["name"]
            pending_exact = conn.execute(
                "SELECT ai.vectorizer_queue_pending(%s, true)", (name,)
            ).fetchone()[0]
            data["pending_exact"] = int(pending_exact)
            vid = rows[0]["id"]
            errs = conn.execute(
                """
                SELECT recorded, message, details
                FROM ai.vectorizer_errors
                WHERE id = %s
                ORDER BY recorded DESC
                LIMIT 20
                """,
                (vid,),
            ).fetchall()
            data["errors"] = [dict(r) for r in errs]
    except Exception as e:  # pragma: no cover
        data = {"ok": False, "error": str(e)}
    return data


@router.get("/stats/bm25")
def stats_bm25(conn=Depends(get_connection)) -> Dict[str, Any]:
    data: Dict[str, Any] = {"ok": True}
    try:
        idx = conn.execute(
            """
            SELECT indexrelname, idx_scan, last_analyze, last_vacuum
            FROM pg_stat_user_indexes
            WHERE indexrelname = 'document_segments_bm25_idx'
            """
        ).fetchone()
        data["usage"] = dict(idx) if idx else None
        size = conn.execute(
            "SELECT pg_size_pretty(pg_relation_size('public.document_segments_bm25_idx'))"
        ).fetchone()
        data["size"] = size[0] if size else None
    except Exception as e:  # pragma: no cover
        data = {"ok": False, "error": str(e)}
    return data


@router.get("/stats/queries")
def stats_queries() -> Dict[str, Any]:
    return {"ok": True, "items": get_query_stats()}


@router.get("/stats/coverage")
def stats_coverage(conn=Depends(get_connection)) -> Dict[str, Any]:
    data: Dict[str, Any] = {"ok": True}
    try:
        emb = conn.execute(
            "SELECT embedding_status, COUNT(*) AS c FROM document_segments GROUP BY 1"
        ).fetchall()
        noise = conn.execute(
            "SELECT is_noise, COUNT(*) AS c FROM document_segments GROUP BY 1"
        ).fetchall()
        data["embedding_status"] = [dict(r) for r in emb]
        data["noise"] = [dict(r) for r in noise]
    except Exception as e:  # pragma: no cover
        data = {"ok": False, "error": str(e)}
    return data


@router.get("/stats/table")
def stats_table(conn=Depends(get_connection)) -> Dict[str, Any]:
    data: Dict[str, Any] = {"ok": True}
    try:
        size = conn.execute(
            "SELECT pg_size_pretty(pg_total_relation_size('public.document_segments'))"
        ).fetchone()[0]
        count = conn.execute("SELECT COUNT(*) FROM public.document_segments").fetchone()[0]
        data.update({"table_size": size, "rows": int(count)})
    except Exception as e:  # pragma: no cover
        data = {"ok": False, "error": str(e)}
    return data
