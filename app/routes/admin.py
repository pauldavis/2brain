from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_user
from app.db import get_connection
from app.services.vectorizer import backfill_loop

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/refresh-indices")
def refresh_indices(user=Depends(get_current_user)):
    """
    Trigger database maintenance tasks:
    1. Backfill missing embeddings (Python Vectorizer).
    2. VACUUM ANALYZE to optimize query planning and index usage.
    """
    logger.info(f"Starting database maintenance (triggered by {user.email})...")

    try:
        # 1. Backfill vectors
        logger.info("Running vector backfill...")
        processed = backfill_loop()
        logger.info(f"Vector backfill complete: {processed} segments processed.")

        # 2. Database Maintenance
        # We need a connection that can run VACUUM (cannot run inside a transaction block)
        # get_connection yields a connection that we can configure.
        with get_connection() as conn:
            old_autocommit = conn.autocommit
            conn.autocommit = True
            try:
                with conn.cursor() as cur:
                    logger.info("Running VACUUM ANALYZE...")
                    cur.execute("VACUUM ANALYZE")
            finally:
                conn.autocommit = old_autocommit

        logger.info("Database maintenance complete.")
        return {
            "status": "ok",
            "message": f"Indices refreshed, database vacuumed, {processed} embeddings generated.",
        }

    except Exception as e:
        logger.error(f"Maintenance failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
