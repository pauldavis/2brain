from __future__ import annotations

import logging
from typing import List, Optional

import psycopg
from psycopg.rows import dict_row

from app.config import get_settings
from app.db import connection
from app.services.search import embed_query_openai

logger = logging.getLogger(__name__)


def process_pending_embeddings(batch_size: int = 50) -> int:
    """
    Finds segments with embedding_status='pending', generates embeddings via OpenAI,
    and updates the database.

    Returns the number of segments processed.
    """
    processed_count = 0

    try:
        # We use a separate connection context to ensure we can commit/rollback independently
        with connection() as conn:
            # 1. Fetch pending segments
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, content_markdown
                    FROM document_segments
                    WHERE embedding_status = 'pending'
                    AND content_markdown IS NOT NULL
                    AND trim(content_markdown) != ''
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                    """,
                    (batch_size,),
                )
                rows = cur.fetchall()

            if not rows:
                return 0

            logger.info(f"Vectorizer: Found {len(rows)} pending segments.")

            # 2. Generate embeddings
            updates = []
            for row in rows:
                seg_id = row["id"]
                text = row["content_markdown"]
                try:
                    # Use the shared OpenAI embedding function
                    vector = embed_query_openai(text)
                    updates.append((vector, seg_id))
                except Exception as e:
                    logger.error(f"Failed to embed segment {seg_id}: {e}")
                    # Mark as failed so we don't retry indefinitely in a tight loop
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE document_segments SET embedding_status = 'failed' WHERE id = %s",
                            (seg_id,),
                        )
                    conn.commit()

            # 3. Batch Update
            if updates:
                with conn.cursor() as cur:
                    cur.executemany(
                        """
                        UPDATE document_segments
                        SET embedding = %s,
                            embedding_status = 'ready',
                            embedding_updated_at = NOW()
                        WHERE id = %s
                        """,
                        updates,
                    )
                conn.commit()
                processed_count = len(updates)
                logger.info(
                    f"Vectorizer: Successfully embedded {processed_count} segments."
                )

    except Exception as e:
        logger.exception(f"Vectorizer failed: {e}")

    return processed_count


def backfill_loop(batch_size: int = 50, limit: Optional[int] = None) -> int:
    """
    Runs the processing loop until no more pending items exist or limit is reached.
    """
    total_processed = 0
    while True:
        count = process_pending_embeddings(batch_size=batch_size)
        if count == 0:
            break
        total_processed += count
        if limit and total_processed >= limit:
            break
    return total_processed
