from __future__ import annotations

from datetime import datetime
from typing import Mapping, Sequence

import psycopg
from psycopg.types.json import Json

from ingest.models import SegmentInput


def persist_document(
    conn: psycopg.Connection,
    *,
    source_system: str,
    external_id: str,
    title: str,
    summary: str | None,
    created_at: datetime,
    updated_at: datetime,
    raw_metadata: Mapping[str, object],
    source_path: str,
    checksum: bytes,
    raw_payload: Mapping[str, object],
    segments: Sequence[SegmentInput],
) -> bool:
    """Insert or update a document and its segments. Returns True if a new version was created."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (
                source_system,
                external_id,
                title,
                summary,
                created_at,
                updated_at,
                raw_metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_system, external_id)
            DO UPDATE SET
                title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                created_at = EXCLUDED.created_at,
                updated_at = EXCLUDED.updated_at,
                raw_metadata = EXCLUDED.raw_metadata
            RETURNING id
            """,
            (
                source_system,
                external_id,
                title,
                summary,
                created_at,
                updated_at,
                Json(raw_metadata),
            ),
        )
        document_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO document_versions (
                document_id,
                source_path,
                checksum,
                raw_payload
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (document_id, checksum)
            DO NOTHING
            RETURNING id
            """,
            (
                document_id,
                source_path,
                checksum,
                Json(raw_payload),
            ),
        )
        version_row = cur.fetchone()
        if not version_row:
            return False
        document_version_id = version_row[0]

        node_to_segment_id: dict[str, str] = {}
        for segment in segments:
            parent_segment_id = node_to_segment_id.get(segment.parent_node_id)
            cur.execute(
                """
                INSERT INTO document_segments (
                    document_version_id,
                    parent_segment_id,
                    sequence,
                    source_role,
                    segment_type,
                    content_markdown,
                    content_plaintext,
                    content_json,
                    started_at,
                    ended_at,
                    raw_reference
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    to_tsvector('english', %s),
                    %s, %s, %s, %s
                )
                RETURNING id
                """,
                (
                    document_version_id,
                    parent_segment_id,
                    segment.sequence,
                    segment.source_role,
                    segment.segment_type,
                    segment.content_markdown,
                    segment.plaintext,
                    Json(segment.content_json) if segment.content_json is not None else None,
                    segment.started_at,
                    segment.ended_at,
                    segment.raw_reference,
                ),
            )
            segment_id = cur.fetchone()[0]
            node_to_segment_id[segment.node_id] = segment_id

            for index, block in enumerate(segment.blocks, start=1):
                cur.execute(
                    """
                    INSERT INTO segment_blocks (
                        segment_id,
                        sequence,
                        block_type,
                        language,
                        body,
                        raw_data
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        segment_id,
                        index,
                        block.block_type,
                        block.language,
                        block.body,
                        Json(block.raw_data) if block.raw_data is not None else None,
                    ),
                )

            for asset in segment.assets:
                cur.execute(
                    """
                    INSERT INTO segment_assets (
                        segment_id,
                        asset_type,
                        file_name,
                        mime_type,
                        size_bytes,
                        local_path,
                        source_reference
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        segment_id,
                        asset.asset_type,
                        asset.file_name,
                        asset.mime_type,
                        asset.size_bytes,
                        asset.local_path,
                        asset.source_reference,
                    ),
                )
    return True
