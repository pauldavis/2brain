from __future__ import annotations

from typing import Any, Dict, Literal

from fastapi import APIRouter, Depends, Query

from app.db import get_connection
from app.metrics import get_query_stats
from app.services.search import (
    BM25_SQL,
    RRF_SQL,
    _format_vector_literal,
    embed_query_openai,
)

router = APIRouter(tags=["stats"])


@router.get("/stats/vectorizer")
def stats_vectorizer(conn=Depends(get_connection)) -> Dict[str, Any]:
    data: Dict[str, Any] = {"ok": True, "vectorizers": []}
    try:
        view_exists = conn.execute(
            "SELECT to_regclass('ai.vectorizer_status')"
        ).fetchone()[0]
        if view_exists is None:
            data["message"] = (
                "pgai vectorizer metadata is not installed (missing ai.vectorizer_status)."
            )
            return data

        vs = conn.execute("SELECT * FROM ai.vectorizer_status").fetchall()
        rows = [dict(r) for r in vs]
        data["vectorizers"] = rows
        if not rows:
            data["message"] = (
                "No vectorizers registered. Run ai.create_vectorizer first."
            )
            return data

        name = rows[0]["name"]
        try:
            pending_exact = conn.execute(
                "SELECT ai.vectorizer_queue_pending(%s, true)", (name,)
            ).fetchone()[0]
            data["pending_exact"] = int(pending_exact)
        except Exception as pending_err:  # pragma: no cover - helper may be absent
            data.setdefault("warnings", []).append(
                f"Could not query ai.vectorizer_queue_pending: {pending_err}"
            )

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
        data = {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
        }
    return data


@router.get("/stats/fts")
def stats_fts(conn=Depends(get_connection)) -> Dict[str, Any]:
    data: Dict[str, Any] = {"ok": True}
    try:
        idx_row = conn.execute(
            "SELECT to_regclass('public.document_segments_content_plaintext_idx') AS idx_oid"
        ).fetchone()
        idx_oid = idx_row["idx_oid"] if idx_row else None
        if idx_oid is None:
            data["message"] = (
                "GIN index document_segments_content_plaintext_idx is missing. Run migration 0001_initial_schema.sql."
            )
            data["usage"] = None
            data["size"] = None
            data["table_stats"] = None
            return data

        idx = conn.execute(
            """
            SELECT *
            FROM pg_stat_user_indexes
            WHERE indexrelname = 'document_segments_content_plaintext_idx'
            """
        ).fetchone()
        data["usage"] = dict(idx) if idx else None
        size_row = conn.execute(
            """
            SELECT pg_size_pretty(pg_relation_size('public.document_segments_content_plaintext_idx')) AS size
            """
        ).fetchone()
        data["size"] = size_row["size"] if size_row else None

        table_stats = conn.execute(
            """
            SELECT relname, last_vacuum, last_autovacuum, last_analyze, last_autoanalyze
            FROM pg_stat_user_tables
            WHERE relname = 'document_segments'
            """
        ).fetchone()
        data["table_stats"] = dict(table_stats) if table_stats else None
    except Exception as e:  # pragma: no cover
        data = {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
        }
    return data


def _explain_query(
    conn, sql: str, params: Dict[str, Any], *, analyze: bool = True
) -> Dict[str, Any]:
    """Run EXPLAIN (FORMAT JSON) against the provided SQL and return the parsed plan."""
    explain_opts = ["BUFFERS", "VERBOSE", "COSTS", "FORMAT JSON"]
    if analyze:
        explain_opts.insert(0, "ANALYZE")
    statement = f"EXPLAIN ({', '.join(explain_opts)})\n{sql}"
    row = conn.execute(statement, params).fetchone()
    plan_list = row.get("QUERY PLAN") if row else None
    if not plan_list:
        raise RuntimeError("EXPLAIN did not return a plan")
    plan = plan_list[0]
    return plan


@router.get("/stats/search_plan")
def stats_search_plan(
    mode: Literal["bm25", "hybrid"] = Query("bm25"),
    q: str = Query(..., description="Search text to analyze"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    threshold: float | None = Query(
        None, description="BM25 score cutoff when mode=bm25"
    ),
    w_bm25: float = Query(0.5, ge=0.0, le=1.0),
    w_vec: float = Query(0.5, ge=0.0, le=1.0),
    k: int = Query(60, ge=1, le=500),
    analyze: bool = Query(True, description="Run ANALYZE to capture execution stats"),
    conn=Depends(get_connection),
) -> Dict[str, Any]:
    try:
        if mode == "bm25":
            params = {"q": q, "threshold": threshold, "limit": limit, "offset": offset}
            plan = _explain_query(conn, BM25_SQL, params, analyze=analyze)
            metadata = {
                "mode": mode,
                "threshold": threshold,
                "limit": limit,
                "offset": offset,
            }
        else:
            q_embedding = embed_query_openai(q)
            params = {
                "q": q,
                "qvec": _format_vector_literal(q_embedding),
                "w_bm25": w_bm25,
                "w_vec": w_vec,
                "k": k,
                "limit": limit,
                "offset": offset,
            }
            plan = _explain_query(conn, RRF_SQL, params, analyze=analyze)
            metadata = {
                "mode": mode,
                "w_bm25": w_bm25,
                "w_vec": w_vec,
                "k": k,
                "limit": limit,
                "offset": offset,
            }
        return {
            "ok": True,
            "query": q,
            "metadata": metadata,
            "planning_time_ms": plan.get("Planning Time"),
            "execution_time_ms": plan.get("Execution Time"),
            "plan": plan,
        }
    except Exception as exc:  # pragma: no cover - diagnostic endpoint
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/stats/queries")
def stats_queries() -> Dict[str, Any]:
    return {"ok": True, "items": get_query_stats()}


@router.get("/stats/coverage")
def stats_coverage(conn=Depends(get_connection)) -> Dict[str, Any]:
    data: Dict[str, Any] = {"ok": True}
    try:
        emb = conn.execute(
            """
            SELECT embedding_status, COUNT(*) AS c
            FROM document_segments
            WHERE is_noise = FALSE OR embedding_status = 'skipped_noise'
            GROUP BY 1
            ORDER BY 1
            """
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
        size_row = conn.execute(
            "SELECT pg_size_pretty(pg_total_relation_size('public.document_segments')) AS size"
        ).fetchone()
        count_row = conn.execute(
            "SELECT COUNT(*) AS count FROM public.document_segments"
        ).fetchone()
        size = size_row["size"] if size_row else None
        count = count_row["count"] if count_row else None
        data.update(
            {"table_size": size, "rows": int(count) if count is not None else None}
        )
    except Exception as e:  # pragma: no cover
        data = {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
        }
    return data
