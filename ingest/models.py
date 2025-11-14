from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class SegmentBlockInput:
    block_type: str
    body: str
    language: Optional[str] = None
    raw_data: Optional[dict] = None


@dataclass
class SegmentAssetInput:
    asset_type: str
    source_reference: Optional[str] = None
    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    local_path: Optional[str] = None


@dataclass
class SegmentInput:
    node_id: str
    parent_node_id: Optional[str]
    sequence: int
    source_role: str
    segment_type: str
    content_markdown: str
    plaintext: str
    content_json: Optional[dict]
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    raw_reference: Optional[str]
    blocks: List[SegmentBlockInput] = field(default_factory=list)
    assets: List[SegmentAssetInput] = field(default_factory=list)
    quality_score: Optional[float] = None
    is_noise: bool = False
