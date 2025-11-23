from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence, Union, Any

import psycopg

from ingest.common import assign_sequences, build_ingest_metadata, payload_checksum, segment_checksum
from ingest.db import PersistResult, persist_document
from ingest.models import SegmentInput


@dataclass
class ParsedDocument:
    source_system: str
    external_id: str
    title: str
    summary: str | None
    created_at: datetime
    updated_at: datetime
    raw_metadata: Mapping[str, object]
    source_path: str
    raw_payload: Union[Mapping[str, object], list]


def ingest_document(
    conn: psycopg.Connection,
    parsed_doc: ParsedDocument,
    segments: Sequence[SegmentInput],
    *,
    ingest_batch_id: str | None = None,
    ingested_by: str | None = None,
    ingest_source: str | None = None,
    ingest_version: str | None = None,
    per_parent_sequences: bool = False,
) -> PersistResult:
    """
    Shared ingestion pipeline for all sources.

    Steps:
    - Assign sequences
    - Compute segment checksums
    - Compute payload checksum
    - Persist document/version/segments with ingest metadata
    """
    assign_sequences(segments, per_parent=per_parent_sequences)
    for seg in segments:
        seg.content_checksum = segment_checksum(seg.content_markdown)

    version_checksum = payload_checksum(parsed_doc.raw_payload)
    ingest_meta = build_ingest_metadata(
        ingest_batch_id=ingest_batch_id,
        ingested_by=ingested_by,
        ingest_source=ingest_source or parsed_doc.source_system,
        ingest_version=ingest_version,
    )

    return persist_document(
        conn,
        source_system=parsed_doc.source_system,
        external_id=parsed_doc.external_id,
        title=parsed_doc.title,
        summary=parsed_doc.summary,
        created_at=parsed_doc.created_at,
        updated_at=parsed_doc.updated_at,
        raw_metadata=parsed_doc.raw_metadata,
        source_path=parsed_doc.source_path,
        checksum=version_checksum,
        raw_payload=parsed_doc.raw_payload,
        segments=segments,
        ingest_metadata=ingest_meta,
    )
