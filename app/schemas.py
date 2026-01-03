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


# -----------------------------------------------------------------------------
# Chat Schemas
# -----------------------------------------------------------------------------


class ChatConfigSchema(BaseModel):
    """Configuration for chat completion."""

    model: str = Field(default="gpt-4o", description="The LLM model to use")
    temperature: float = Field(
        default=0.7, ge=0.0, le=2.0, description="Sampling temperature"
    )
    max_tokens: int = Field(
        default=4096, ge=1, le=128000, description="Maximum tokens in response"
    )
    context_limit: int = Field(
        default=5, ge=0, le=20, description="Max segments to retrieve as context"
    )
    w_bm25: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Weight for BM25 search"
    )
    w_vec: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Weight for vector search"
    )
    include_conversation_history: int = Field(
        default=10, ge=0, le=50, description="Max previous messages to include"
    )


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""

    title: str = Field(
        ..., min_length=1, max_length=500, description="Conversation title"
    )
    config: Optional[ChatConfigSchema] = Field(
        default=None, description="Optional chat configuration"
    )


class ConversationSummary(BaseModel):
    """Summary of a conversation for listing."""

    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    config: Optional[Dict[str, Any]] = None


class ChatMessageSchema(BaseModel):
    """A message in a conversation."""

    role: str = Field(..., description="Message role: user, assistant, or system")
    content: str = Field(..., description="Message content (markdown)")
    segment_id: Optional[UUID] = Field(
        default=None, description="Segment ID if persisted"
    )
    created_at: Optional[datetime] = Field(
        default=None, description="When the message was created"
    )


class RetrievedContextSchema(BaseModel):
    """A segment retrieved as RAG context."""

    segment_id: UUID
    document_id: UUID
    document_title: str
    source_system: str
    content: str
    score: float
    rank: int
    source_role: str


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""

    content: str = Field(..., min_length=1, description="The message content")
    config_override: Optional[ChatConfigSchema] = Field(
        default=None, description="Optional config override for this message"
    )


class ChatResponseSchema(BaseModel):
    """Response from sending a message."""

    content: str = Field(..., description="The assistant's response")
    segment_id: UUID = Field(..., description="Segment ID of the response")
    context_used: List[RetrievedContextSchema] = Field(
        default_factory=list, description="Context segments used for RAG"
    )
    model: str = Field(..., description="The model used")
    tokens_used: Optional[int] = Field(default=None, description="Total tokens used")


class UpdateConversationRequest(BaseModel):
    """Request to update a conversation."""

    title: Optional[str] = Field(
        default=None, min_length=1, max_length=500, description="New title"
    )
    config: Optional[ChatConfigSchema] = Field(
        default=None, description="New chat configuration"
    )
