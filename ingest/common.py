from __future__ import annotations

import hashlib
import json
import re
from typing import Iterable, Mapping, Optional, Union

from ingest.models import SegmentInput

WHITESPACE_RE = re.compile(r"\s+")


def normalize_markdown(markdown: str) -> str:
    """Normalize markdown for stable checksum computation."""
    return WHITESPACE_RE.sub(" ", (markdown or "").strip())


def segment_checksum(markdown: str) -> Optional[bytes]:
    """
    Return a SHA-256 digest of normalized markdown content.

    If the normalized content is empty, return None to avoid spurious
    duplicate checksums for empty segments.
    """
    normalized = normalize_markdown(markdown)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).digest()


def assign_sequences(segments: Iterable[SegmentInput], *, per_parent: bool = False) -> None:
    """
    Enforce monotonic, 1-based sequences.

    If per_parent=True, sequences are assigned per parent_segment_id; otherwise, globally per list order.
    """
    if per_parent:
        buckets: dict[Optional[str], int] = {}
        for seg in segments:
            parent = seg.parent_node_id
            buckets[parent] = buckets.get(parent, 0) + 1
            seg.sequence = buckets[parent]
    else:
        for idx, seg in enumerate(segments, start=1):
            seg.sequence = idx


def payload_checksum(raw_payload: Union[Mapping[str, object], list]) -> bytes:
    """Stable checksum for a payload using sorted JSON."""
    return hashlib.sha256(json.dumps(raw_payload, sort_keys=True).encode("utf-8")).digest()


def build_ingest_metadata(
    *,
    ingest_batch_id: Optional[str] = None,
    ingested_by: Optional[str] = None,
    ingest_source: Optional[str] = None,
    ingest_version: Optional[str] = None,
) -> dict:
    return {
        "ingest_batch_id": ingest_batch_id,
        "ingested_by": ingested_by,
        "ingest_source": ingest_source,
        "ingest_version": ingest_version,
    }
