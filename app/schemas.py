from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class Document(BaseModel):
    id: UUID
    source_system: str
    external_id: str
    title: str
    summary: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    raw_metadata: Dict[str, Any] = Field(default_factory=dict)


class DocumentVersion(BaseModel):
    id: UUID
    document_id: UUID
    ingested_at: datetime
    source_path: str
    checksum: str


class SegmentBlock(BaseModel):
    id: UUID
    sequence: int
    block_type: str
    language: Optional[str] = None
    body: str
    raw_data: Optional[Dict[str, Any]] = None


class SegmentAsset(BaseModel):
    id: UUID
    asset_type: str
    attachment_id: UUID
    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    created_at: datetime
    has_content: bool = False


class SegmentAnnotation(BaseModel):
    id: UUID
    annotation_type: str
    payload: Dict[str, Any]
    created_at: datetime


class Segment(BaseModel):
    id: UUID
    parent_segment_id: Optional[UUID] = None
    sequence: int
    source_role: str
    segment_type: str
    content_markdown: str
    content_json: Optional[Dict[str, Any]] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    raw_reference: Optional[str] = None
    blocks: List[SegmentBlock] = Field(default_factory=list)
    assets: List[SegmentAsset] = Field(default_factory=list)
    annotations: List[SegmentAnnotation] = Field(default_factory=list)


class Keyword(BaseModel):
    id: UUID
    term: str
    description: Optional[str] = None
    document_keyword_id: UUID


class DocumentView(BaseModel):
    document: Document
    version: DocumentVersion
    segments: List[Segment]
    keywords: List[Keyword] = Field(default_factory=list)


class DocumentTranscript(BaseModel):
    document: Document
    version: DocumentVersion
    segment_count: int
    generated_at: datetime
    markdown: str


class SegmentExport(BaseModel):
    document: Document
    version: DocumentVersion
    segment: Segment
    generated_at: datetime
    markdown: str


class DocumentSummary(BaseModel):
    id: UUID
    title: str
    source_system: str
    created_at: datetime
    updated_at: datetime
    segment_count: int
    char_count: int


class SearchResult(BaseModel):
    document_id: UUID
    document_title: str
    source_system: str
    document_updated_at: Optional[datetime] = None
    document_segment_count: Optional[int] = None
    document_char_count: Optional[int] = None
    segment_id: UUID
    sequence: int
    source_role: str
    snippet: str
    started_at: Optional[datetime] = None


class SearchSegmentMatch(BaseModel):
    segment_id: UUID
    sequence: int
    source_role: str
    score: float
    snippet: str


class DocumentSearchResult(BaseModel):
    document_id: UUID
    document_title: str
    source_system: str
    document_updated_at: Optional[datetime] = None
    document_segment_count: Optional[int] = None
    document_char_count: Optional[int] = None
    match_count: int
    match_density: float
    document_score: float
    best_segment_score: float
    topk_score: float
    top_segments: List[SearchSegmentMatch] = Field(default_factory=list)
