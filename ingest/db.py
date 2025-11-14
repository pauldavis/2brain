from __future__ import annotations

import string
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

import psycopg
from psycopg.types.json import Json

from ingest.models import SegmentInput

QUALITY_NOISE_THRESHOLD = 0.2


def _read_asset_bytes(local_path: str | None) -> bytes | None:
    if not local_path:
        return None
    try:
        return Path(local_path).read_bytes()
    except (FileNotFoundError, OSError):
        return None


def estimate_segment_quality(markdown: str, plaintext: str) -> tuple[float, bool]:
    """
    Produce a lightweight quality score and noise flag for a segment.

    The heuristic favours segments with enough lexical variety and alphabetic
    content, while aggressively pruning extremely short or punctuation-heavy
    chunks that tend to be export noise.
    """
    text = (plaintext or "").strip()
    if not text:
        text = (markdown or "").strip()
    if not text:
        return 0.0, True

    normalized = " ".join(text.split())
    length = len(normalized)
    tokens = normalized.split()
    token_count = len(tokens)
    unique_tokens = len(set(tokens))

    alnum_chars = sum(ch.isalnum() for ch in normalized)
    punctuation_chars = sum(ch in string.punctuation for ch in normalized)

    alpha_ratio = alnum_chars / length if length else 0.0
    punctuation_ratio = punctuation_chars / length if length else 0.0
    diversity_ratio = unique_tokens / token_count if token_count else 0.0

    length_score = min(1.0, token_count / 80)
    diversity_score = diversity_ratio
    character_score = alpha_ratio
    noise_penalty = max(0.0, punctuation_ratio - 0.15)

    score = (
        0.5 * length_score
        + 0.3 * character_score
        + 0.2 * diversity_score
        - 0.4 * noise_penalty
    )
    score = max(0.0, min(1.0, score))

    is_noise = (
        score < 0.2
        or token_count < 3
        or unique_tokens <= 1
        or alpha_ratio < 0.25
    )
    return score, is_noise


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
        document_row = cur.fetchone()
        if document_row is None:
            raise RuntimeError("Failed to insert or update document record.")
        document_id = document_row[0]

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
            parent_segment_id = (
                node_to_segment_id.get(segment.parent_node_id)
                if segment.parent_node_id
                else None
            )
            auto_score, auto_noise = estimate_segment_quality(
                segment.content_markdown,
                segment.plaintext,
            )
            quality_score = (
                segment.quality_score
                if segment.quality_score is not None
                else auto_score
            )
            if segment.is_noise:
                is_noise = True
            elif segment.quality_score is not None:
                is_noise = segment.quality_score < QUALITY_NOISE_THRESHOLD
            else:
                is_noise = auto_noise
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
                    quality_score,
                    is_noise,
                    started_at,
                    ended_at,
                    raw_reference
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    to_tsvector('english', %s),
                    %s, %s, %s, %s, %s, %s
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
                    quality_score,
                    is_noise,
                    segment.started_at,
                    segment.ended_at,
                    segment.raw_reference,
                ),
            )
            segment_row = cur.fetchone()
            if segment_row is None:
                raise RuntimeError("Failed to insert segment record.")
            segment_id = segment_row[0]
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
                content_bytes = _read_asset_bytes(asset.local_path)
                size_bytes = asset.size_bytes
                if content_bytes is not None and size_bytes is None:
                    size_bytes = len(content_bytes)

                cur.execute(
                    """
                    INSERT INTO attachments (
                        file_name,
                        mime_type,
                        size_bytes,
                        local_path,
                        source_reference,
                        content
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        asset.file_name,
                        asset.mime_type,
                        size_bytes,
                        asset.local_path,
                        asset.source_reference,
                        content_bytes,
                    ),
                )
                attachment_row = cur.fetchone()
                if attachment_row is None:
                    raise RuntimeError("Failed to create attachment record.")
                attachment_id = attachment_row[0]

                cur.execute(
                    """
                    INSERT INTO segment_assets (
                        segment_id,
                        asset_type,
                        attachment_id
                    )
                    VALUES (%s, %s, %s)
                    """,
                    (
                        segment_id,
                        asset.asset_type,
                        attachment_id,
                    ),
                )
    return True
