from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncGenerator, Generator, List, Optional, Tuple
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Json

from app.config import get_settings
from app.services.search import embed_query_openai, search_segments_hybrid_rrf

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Data Classes
# -----------------------------------------------------------------------------


@dataclass
class ChatMessage:
    """Represents a message in a conversation."""

    role: str  # 'user', 'assistant', 'system'
    content: str
    segment_id: Optional[UUID] = None
    created_at: Optional[datetime] = None


@dataclass
class RetrievedContext:
    """Represents a segment retrieved as RAG context."""

    segment_id: UUID
    document_id: UUID
    document_title: str
    source_system: str
    content: str
    score: float
    rank: int
    source_role: str


@dataclass
class ChatConfig:
    """Configuration for chat completion."""

    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4096
    # RAG settings
    context_limit: int = 10  # Max segments to retrieve (increased from 5)
    max_context_chars: int = 50000  # Max total characters of context (~12k tokens)
    w_bm25: float = 0.5
    w_vec: float = 0.5
    include_conversation_history: int = 10  # Max previous messages to include


@dataclass
class GenerationResult:
    """Result of generating a response."""

    content: str
    segment_id: UUID
    context_used: List[RetrievedContext]
    model: str
    tokens_used: Optional[int] = None


# -----------------------------------------------------------------------------
# Conversation Management
# -----------------------------------------------------------------------------


def create_conversation(
    conn: psycopg.Connection,
    *,
    title: str,
    config: Optional[ChatConfig] = None,
) -> UUID:
    """
    Create a new native 2brain conversation.

    Returns the document ID of the new conversation.
    """
    config = config or ChatConfig()
    now = datetime.now(timezone.utc)
    external_id = f"2brain-{uuid4().hex[:12]}"

    with conn.cursor() as cur:
        # Create the document
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
            VALUES ('2brain', %s, %s, NULL, %s, %s, %s)
            RETURNING id
            """,
            (
                external_id,
                title,
                now,
                now,
                Json({"chat_config": _config_to_dict(config)}),
            ),
        )
        row = cur.fetchone()
        document_id = row["id"] if isinstance(row, dict) else row[0]

        # Create a document version (required by the schema)
        # For native chats, we use a placeholder checksum that updates with each message
        cur.execute(
            """
            INSERT INTO document_versions (
                document_id,
                source_path,
                checksum,
                raw_payload
            )
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (
                document_id,
                "2brain://native",
                _compute_checksum(f"{document_id}-{now.isoformat()}"),
                Json({"type": "native_conversation", "created_at": now.isoformat()}),
            ),
        )

        conn.commit()
        logger.info(f"Created conversation {document_id} with title: {title}")

        return document_id


def get_conversation_config(conn: psycopg.Connection, document_id: UUID) -> ChatConfig:
    """Get the chat configuration for a conversation."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT raw_metadata
            FROM documents
            WHERE id = %s AND source_system = '2brain'
            """,
            (document_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Conversation {document_id} not found")

        metadata = row["raw_metadata"] if isinstance(row, dict) else row[0]
        if metadata and "chat_config" in metadata:
            return _dict_to_config(metadata["chat_config"])
        return ChatConfig()


def update_conversation_config(
    conn: psycopg.Connection,
    document_id: UUID,
    config: ChatConfig,
) -> None:
    """Update the chat configuration for a conversation."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE documents
            SET raw_metadata = raw_metadata || %s::jsonb
            WHERE id = %s AND source_system = '2brain'
            """,
            (Json({"chat_config": _config_to_dict(config)}), document_id),
        )
        conn.commit()


def update_conversation_title(
    conn: psycopg.Connection,
    document_id: UUID,
    title: str,
) -> None:
    """Update the title of a conversation."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE documents
            SET title = %s, updated_at = %s
            WHERE id = %s AND source_system = '2brain'
            """,
            (title, datetime.now(timezone.utc), document_id),
        )
        conn.commit()


def delete_conversation(conn: psycopg.Connection, document_id: UUID) -> bool:
    """
    Delete a native conversation.

    Returns True if the conversation was deleted, False if not found.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM documents
            WHERE id = %s AND source_system = '2brain'
            RETURNING id
            """,
            (document_id,),
        )
        row = cur.fetchone()
        conn.commit()
        return row is not None


def list_conversations(
    conn: psycopg.Connection,
    *,
    limit: int = 50,
    offset: int = 0,
) -> List[dict]:
    """List all native 2brain conversations."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                d.id,
                d.title,
                d.created_at,
                d.updated_at,
                d.raw_metadata,
                COUNT(ds.id) AS message_count
            FROM documents d
            LEFT JOIN document_versions dv ON dv.document_id = d.id
            LEFT JOIN document_segments ds ON ds.document_version_id = dv.id
            WHERE d.source_system = '2brain'
            GROUP BY d.id, d.title, d.created_at, d.updated_at, d.raw_metadata
            ORDER BY d.updated_at DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        rows = cur.fetchall()
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "message_count": row["message_count"],
                "config": row["raw_metadata"].get("chat_config")
                if row["raw_metadata"]
                else None,
            }
            for row in rows
        ]


# -----------------------------------------------------------------------------
# Message Management
# -----------------------------------------------------------------------------


def get_conversation_messages(
    conn: psycopg.Connection,
    document_id: UUID,
) -> List[ChatMessage]:
    """Get all messages in a conversation, ordered by sequence."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                ds.id,
                ds.source_role,
                ds.content_markdown,
                ds.started_at
            FROM document_segments ds
            JOIN document_versions dv ON dv.id = ds.document_version_id
            WHERE dv.document_id = %s
            ORDER BY ds.sequence ASC
            """,
            (document_id,),
        )
        rows = cur.fetchall()
        return [
            ChatMessage(
                role=row["source_role"],
                content=row["content_markdown"],
                segment_id=row["id"],
                created_at=row["started_at"],
            )
            for row in rows
        ]


def add_message(
    conn: psycopg.Connection,
    document_id: UUID,
    *,
    role: str,
    content: str,
    context_refs: Optional[List[Tuple[UUID, float, int]]] = None,
) -> UUID:
    """
    Add a message to a conversation.

    Args:
        conn: Database connection
        document_id: The conversation document ID
        role: Message role ('user', 'assistant', 'system')
        content: Message content (markdown)
        context_refs: Optional list of (source_segment_id, score, rank) tuples
                     for tracking RAG context (only for assistant messages)

    Returns:
        The segment ID of the new message
    """
    now = datetime.now(timezone.utc)

    with conn.cursor() as cur:
        # Get the document version ID and next sequence number
        cur.execute(
            """
            SELECT dv.id AS version_id, COALESCE(MAX(ds.sequence), 0) + 1 AS next_seq
            FROM document_versions dv
            LEFT JOIN document_segments ds ON ds.document_version_id = dv.id
            WHERE dv.document_id = %s
            GROUP BY dv.id
            ORDER BY dv.ingested_at DESC
            LIMIT 1
            """,
            (document_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Conversation {document_id} not found")

        version_id = row["version_id"]
        sequence = row["next_seq"]

        # Insert the segment
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
                quality_score,
                is_noise,
                embedding_status
            )
            VALUES (
                %s, NULL, %s, %s, 'message', %s,
                to_tsvector('english', %s),
                NULL, %s, %s, 1.0, FALSE, 'pending'
            )
            RETURNING id
            """,
            (version_id, sequence, role, content, content, now, now),
        )
        segment_row = cur.fetchone()
        segment_id = (
            segment_row["id"] if isinstance(segment_row, dict) else segment_row[0]
        )

        # Update document's updated_at timestamp
        cur.execute(
            """
            UPDATE documents
            SET updated_at = %s
            WHERE id = %s
            """,
            (now, document_id),
        )

        # If this is an assistant message with context refs, store them
        if role == "assistant" and context_refs:
            for source_segment_id, score, rank in context_refs:
                cur.execute(
                    """
                    INSERT INTO segment_context_refs (
                        target_segment_id,
                        source_segment_id,
                        relevance_score,
                        search_method,
                        rank
                    )
                    VALUES (%s, %s, %s, 'hybrid', %s)
                    ON CONFLICT (target_segment_id, source_segment_id) DO NOTHING
                    """,
                    (segment_id, source_segment_id, score, rank),
                )

        conn.commit()
        return segment_id


def get_context_for_segment(
    conn: psycopg.Connection,
    segment_id: UUID,
) -> List[RetrievedContext]:
    """Get the RAG context that was used to generate a specific response."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                scr.source_segment_id,
                scr.relevance_score,
                scr.rank,
                scr.search_query,
                scr.search_method,
                ds.content_markdown,
                ds.source_role,
                d.id AS document_id,
                d.title AS document_title,
                d.source_system
            FROM segment_context_refs scr
            JOIN document_segments ds ON ds.id = scr.source_segment_id
            JOIN document_versions dv ON dv.id = ds.document_version_id
            JOIN documents d ON d.id = dv.document_id
            WHERE scr.target_segment_id = %s
            ORDER BY scr.rank ASC
            """,
            (segment_id,),
        )
        rows = cur.fetchall()
        return [
            RetrievedContext(
                segment_id=row["source_segment_id"],
                document_id=row["document_id"],
                document_title=row["document_title"],
                source_system=row["source_system"],
                content=row["content_markdown"],
                score=row["relevance_score"] or 0.0,
                rank=row["rank"] or 0,
                source_role=row["source_role"],
            )
            for row in rows
        ]


# -----------------------------------------------------------------------------
# RAG Pipeline
# -----------------------------------------------------------------------------


def retrieve_context(
    conn: psycopg.Connection,
    query: str,
    *,
    limit: int = 10,
    max_context_chars: int = 50000,
    w_bm25: float = 0.5,
    w_vec: float = 0.5,
    exclude_document_id: Optional[UUID] = None,
) -> List[RetrievedContext]:
    """
    Retrieve relevant segments from the knowledge base using hybrid search.

    Args:
        conn: Database connection
        query: The search query (typically the user's message)
        limit: Maximum number of segments to retrieve
        max_context_chars: Maximum total characters of context to include
        w_bm25: Weight for BM25 component
        w_vec: Weight for vector similarity component
        exclude_document_id: Optional document ID to exclude from results
                            (e.g., exclude the current conversation)

    Returns:
        List of retrieved context segments
    """
    # Embed the query
    query_embedding = embed_query_openai(query, conn=conn)

    # Perform hybrid search - fetch more candidates for filtering
    results, _meta = search_segments_hybrid_rrf(
        conn,
        q=query,
        q_embedding=query_embedding,
        limit=limit * 3,  # Fetch extra for filtering and full content lookup
        offset=0,
        w_bm25=w_bm25,
        w_vec=w_vec,
    )

    if not results:
        return []

    # Fetch full content and timestamps for the candidate segments (snippets are truncated to 280 chars)
    segment_ids = [r.segment_id for r in results]
    segment_details = _fetch_full_segment_details(conn, segment_ids)

    # Convert to RetrievedContext with full content, respecting limits
    context_list = []
    total_chars = 0

    for rank, result in enumerate(results, start=1):
        if exclude_document_id and result.document_id == exclude_document_id:
            continue
        if len(context_list) >= limit:
            break

        # Get full content, fall back to snippet if not found
        details = segment_details.get(result.segment_id)
        full_content = details.content if details else result.snippet

        # Check if adding this segment would exceed char limit
        if total_chars + len(full_content) > max_context_chars and context_list:
            # Already have some context, stop here
            logger.info(
                f"[retrieve_context] Stopping at {len(context_list)} segments "
                f"({total_chars} chars) to stay under {max_context_chars} char limit"
            )
            break

        context_list.append(
            RetrievedContext(
                segment_id=result.segment_id,
                document_id=result.document_id,
                document_title=result.document_title,
                source_system=result.source_system,
                content=full_content,
                score=0.0,  # RRF doesn't give us a simple score
                rank=rank,
                source_role=result.source_role,
            )
        )
        total_chars += len(full_content)

    # Sort context chronologically (oldest first, newest last)
    # This helps the LLM understand the temporal flow of information
    def get_sort_key(ctx: RetrievedContext) -> tuple:
        details = segment_details.get(ctx.segment_id)
        ts = details.started_at if details else None
        # Use a very old date for None timestamps so they sort first
        return (ts or datetime.min.replace(tzinfo=timezone.utc),)

    context_list.sort(key=get_sort_key)

    logger.info(
        f"[retrieve_context] Retrieved {len(context_list)} segments, "
        f"{total_chars} total chars for query: {query[:50]}..."
    )
    return context_list


@dataclass
class SegmentDetails:
    """Full content and metadata for a segment."""

    content: str
    started_at: Optional[datetime] = None


def _fetch_full_segment_details(
    conn: psycopg.Connection,
    segment_ids: List[UUID],
) -> dict[UUID, SegmentDetails]:
    """Fetch the full content_markdown and timestamps for a list of segment IDs."""
    if not segment_ids:
        return {}

    with conn.cursor() as cur:
        # Use ANY to fetch all in one query
        cur.execute(
            """
            SELECT id, content_markdown, started_at
            FROM document_segments
            WHERE id = ANY(%s)
            """,
            (segment_ids,),
        )
        rows = cur.fetchall()
        return {
            row["id"]: SegmentDetails(
                content=row["content_markdown"],
                started_at=row["started_at"],
            )
            for row in rows
        }


def build_prompt_messages(
    conversation_history: List[ChatMessage],
    user_message: str,
    context: List[RetrievedContext],
    *,
    history_limit: int = 10,
) -> List[dict]:
    """
    Build the messages array for the chat completion API.

    This constructs a prompt that includes:
    1. A system message explaining the assistant's role and the context
    2. Recent conversation history
    3. The current user message
    """
    messages = []

    # System message with RAG context
    system_parts = [
        "You are a helpful assistant with access to the user's knowledge base of previous conversations.",
        "Use the provided context to give informed, relevant answers.",
        "If the context doesn't contain relevant information, say so and answer based on your general knowledge.",
        "Always cite which conversation the information came from when using context.",
    ]

    if context:
        system_parts.append("\n--- RELEVANT CONTEXT FROM KNOWLEDGE BASE ---\n")
        for ctx in context:
            system_parts.append(
                f"[From: {ctx.document_title} ({ctx.source_system}) - {ctx.source_role}]\n{ctx.content}\n"
            )
        system_parts.append("--- END CONTEXT ---\n")

    messages.append({"role": "system", "content": "\n".join(system_parts)})

    # Add conversation history (limited)
    recent_history = conversation_history[-history_limit:] if history_limit > 0 else []
    for msg in recent_history:
        messages.append({"role": msg.role, "content": msg.content})

    # Add the current user message
    messages.append({"role": "user", "content": user_message})

    return messages


def generate_response(
    conn: psycopg.Connection,
    document_id: UUID,
    user_message: str,
    *,
    config: Optional[ChatConfig] = None,
) -> GenerationResult:
    """
    Generate an assistant response using RAG.

    This is the main entry point for the chat pipeline:
    1. Add the user message to the conversation
    2. Retrieve relevant context from the knowledge base
    3. Build the prompt with context and history
    4. Call the LLM
    5. Store the response and context references

    Returns:
        GenerationResult with the response content and metadata
    """
    config = config or get_conversation_config(conn, document_id)

    # 1. Add user message
    add_message(conn, document_id, role="user", content=user_message)

    # 2. Get conversation history
    history = get_conversation_messages(conn, document_id)

    # 3. Retrieve context (exclude current conversation to avoid self-reference)
    context = retrieve_context(
        conn,
        user_message,
        limit=config.context_limit,
        max_context_chars=config.max_context_chars,
        w_bm25=config.w_bm25,
        w_vec=config.w_vec,
        exclude_document_id=document_id,
    )

    # 4. Build prompt
    messages = build_prompt_messages(
        history[:-1],  # Exclude the message we just added (it's in user_message)
        user_message,
        context,
        history_limit=config.include_conversation_history,
    )

    # 5. Call OpenAI
    response_content, tokens_used = _call_openai_chat(
        messages,
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )

    # 6. Store response with context references
    context_refs = [(ctx.segment_id, ctx.score, ctx.rank) for ctx in context]
    segment_id = add_message(
        conn,
        document_id,
        role="assistant",
        content=response_content,
        context_refs=context_refs,
    )

    return GenerationResult(
        content=response_content,
        segment_id=segment_id,
        context_used=context,
        model=config.model,
        tokens_used=tokens_used,
    )


def generate_response_stream(
    conn: psycopg.Connection,
    document_id: UUID,
    user_message: str,
    *,
    config: Optional[ChatConfig] = None,
) -> Generator[str, None, GenerationResult]:
    """
    Generate an assistant response using RAG with streaming.

    Yields content chunks as they arrive from the LLM.
    Returns the final GenerationResult when complete.

    Usage:
        gen = generate_response_stream(conn, doc_id, "Hello")
        for chunk in gen:
            print(chunk, end="", flush=True)
        result = gen.value  # Access after iteration complete
    """
    config = config or get_conversation_config(conn, document_id)

    # 1. Add user message
    add_message(conn, document_id, role="user", content=user_message)

    # 2. Get conversation history
    history = get_conversation_messages(conn, document_id)

    # 3. Retrieve context
    context = retrieve_context(
        conn,
        user_message,
        limit=config.context_limit,
        max_context_chars=config.max_context_chars,
        w_bm25=config.w_bm25,
        w_vec=config.w_vec,
        exclude_document_id=document_id,
    )

    # 4. Build prompt
    messages = build_prompt_messages(
        history[:-1],
        user_message,
        context,
        history_limit=config.include_conversation_history,
    )

    # 5. Stream from OpenAI
    full_content = []
    for chunk in _stream_openai_chat(
        messages,
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    ):
        full_content.append(chunk)
        yield chunk

    response_content = "".join(full_content)

    # 6. Store response with context references
    context_refs = [(ctx.segment_id, ctx.score, ctx.rank) for ctx in context]
    segment_id = add_message(
        conn,
        document_id,
        role="assistant",
        content=response_content,
        context_refs=context_refs,
    )

    return GenerationResult(
        content=response_content,
        segment_id=segment_id,
        context_used=context,
        model=config.model,
        tokens_used=None,  # Not available in streaming mode
    )


# -----------------------------------------------------------------------------
# OpenAI Integration
# -----------------------------------------------------------------------------


def _call_openai_chat(
    messages: List[dict],
    *,
    model: str = "gpt-4o",
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> Tuple[str, Optional[int]]:
    """Call OpenAI chat completion API (non-streaming)."""
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError(
            "openai package not available. Install `openai>=1.0` for chat."
        ) from e

    api_key = get_settings().openai_api_key
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set in environment")

    client = OpenAI(api_key=api_key)

    t0 = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    content = response.choices[0].message.content or ""
    tokens_used = response.usage.total_tokens if response.usage else None

    logger.info(
        f"[chat] model={model} tokens={tokens_used} elapsed_ms={elapsed_ms:.2f}"
    )

    return content, tokens_used


def _stream_openai_chat(
    messages: List[dict],
    *,
    model: str = "gpt-4o",
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> Generator[str, None, None]:
    """Stream OpenAI chat completion API responses."""
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError(
            "openai package not available. Install `openai>=1.0` for chat."
        ) from e

    api_key = get_settings().openai_api_key
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set in environment")

    client = OpenAI(api_key=api_key)

    t0 = time.perf_counter()
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )

    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    logger.info(f"[chat_stream] model={model} elapsed_ms={elapsed_ms:.2f}")


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _config_to_dict(config: ChatConfig) -> dict:
    """Convert ChatConfig to a dictionary for JSON storage."""
    return {
        "model": config.model,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "context_limit": config.context_limit,
        "max_context_chars": config.max_context_chars,
        "w_bm25": config.w_bm25,
        "w_vec": config.w_vec,
        "include_conversation_history": config.include_conversation_history,
    }


def _dict_to_config(d: dict) -> ChatConfig:
    """Convert a dictionary to ChatConfig."""
    return ChatConfig(
        model=d.get("model", "gpt-4o"),
        temperature=d.get("temperature", 0.7),
        max_tokens=d.get("max_tokens", 4096),
        context_limit=d.get("context_limit", 10),
        max_context_chars=d.get("max_context_chars", 50000),
        w_bm25=d.get("w_bm25", 0.5),
        w_vec=d.get("w_vec", 0.5),
        include_conversation_history=d.get("include_conversation_history", 10),
    )


def _compute_checksum(data: str) -> bytes:
    """Compute a SHA-256 checksum for the given data."""
    import hashlib

    return hashlib.sha256(data.encode("utf-8")).digest()
