from __future__ import annotations

import json
import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.db import get_connection
from app.schemas import (
    ChatConfigSchema,
    ChatMessageSchema,
    ChatResponseSchema,
    ConversationSummary,
    CreateConversationRequest,
    RetrievedContextSchema,
    SendMessageRequest,
    UpdateConversationRequest,
)
from app.services.chat import (
    ChatConfig,
    add_message,
    create_conversation,
    delete_conversation,
    generate_response,
    generate_response_stream,
    get_context_for_segment,
    get_conversation_config,
    get_conversation_messages,
    list_conversations,
    update_conversation_config,
    update_conversation_title,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


# -----------------------------------------------------------------------------
# Conversation Management
# -----------------------------------------------------------------------------


@router.post("/conversations", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_conversation_endpoint(
    request: CreateConversationRequest,
    conn=Depends(get_connection),
) -> dict:
    """Create a new native 2brain conversation."""
    config = None
    if request.config:
        config = ChatConfig(
            model=request.config.model,
            temperature=request.config.temperature,
            max_tokens=request.config.max_tokens,
            context_limit=request.config.context_limit,
            max_context_chars=request.config.max_context_chars,
            w_bm25=request.config.w_bm25,
            w_vec=request.config.w_vec,
            include_conversation_history=request.config.include_conversation_history,
        )

    document_id = create_conversation(conn, title=request.title, config=config)
    return {"id": document_id, "title": request.title}


@router.get("/conversations", response_model=List[ConversationSummary])
def list_conversations_endpoint(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    conn=Depends(get_connection),
) -> List[ConversationSummary]:
    """List all native 2brain conversations."""
    conversations = list_conversations(conn, limit=limit, offset=offset)
    return [
        ConversationSummary(
            id=c["id"],
            title=c["title"],
            created_at=c["created_at"],
            updated_at=c["updated_at"],
            message_count=c["message_count"],
            config=c["config"],
        )
        for c in conversations
    ]


@router.get("/conversations/{conversation_id}", response_model=ConversationSummary)
def get_conversation_endpoint(
    conversation_id: UUID,
    conn=Depends(get_connection),
) -> ConversationSummary:
    """Get a specific conversation's metadata."""
    conversations = list_conversations(conn, limit=1000, offset=0)
    for c in conversations:
        if c["id"] == conversation_id:
            return ConversationSummary(
                id=c["id"],
                title=c["title"],
                created_at=c["created_at"],
                updated_at=c["updated_at"],
                message_count=c["message_count"],
                config=c["config"],
            )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Conversation {conversation_id} not found",
    )


@router.patch("/conversations/{conversation_id}", response_model=dict)
def update_conversation_endpoint(
    conversation_id: UUID,
    request: UpdateConversationRequest,
    conn=Depends(get_connection),
) -> dict:
    """Update a conversation's title or configuration."""
    try:
        if request.title is not None:
            update_conversation_title(conn, conversation_id, request.title)

        if request.config is not None:
            config = ChatConfig(
                model=request.config.model,
                temperature=request.config.temperature,
                max_tokens=request.config.max_tokens,
                context_limit=request.config.context_limit,
                max_context_chars=request.config.max_context_chars,
                w_bm25=request.config.w_bm25,
                w_vec=request.config.w_vec,
                include_conversation_history=request.config.include_conversation_history,
            )
            update_conversation_config(conn, conversation_id, config)

        return {"status": "updated", "id": conversation_id}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.delete(
    "/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_conversation_endpoint(
    conversation_id: UUID,
    conn=Depends(get_connection),
) -> None:
    """Delete a conversation."""
    deleted = delete_conversation(conn, conversation_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation {conversation_id} not found",
        )


@router.get("/conversations/{conversation_id}/config", response_model=ChatConfigSchema)
def get_conversation_config_endpoint(
    conversation_id: UUID,
    conn=Depends(get_connection),
) -> ChatConfigSchema:
    """Get the chat configuration for a conversation."""
    try:
        config = get_conversation_config(conn, conversation_id)
        return ChatConfigSchema(
            model=config.model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            context_limit=config.context_limit,
            max_context_chars=config.max_context_chars,
            w_bm25=config.w_bm25,
            w_vec=config.w_vec,
            include_conversation_history=config.include_conversation_history,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


# -----------------------------------------------------------------------------
# Message Management
# -----------------------------------------------------------------------------


@router.get(
    "/conversations/{conversation_id}/messages", response_model=List[ChatMessageSchema]
)
def get_messages_endpoint(
    conversation_id: UUID,
    conn=Depends(get_connection),
) -> List[ChatMessageSchema]:
    """Get all messages in a conversation."""
    try:
        messages = get_conversation_messages(conn, conversation_id)
        return [
            ChatMessageSchema(
                role=m.role,
                content=m.content,
                segment_id=m.segment_id,
                created_at=m.created_at,
            )
            for m in messages
        ]
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.post(
    "/conversations/{conversation_id}/messages", response_model=ChatResponseSchema
)
def send_message_endpoint(
    conversation_id: UUID,
    request: SendMessageRequest,
    conn=Depends(get_connection),
) -> ChatResponseSchema:
    """
    Send a message and get an AI response.

    This performs the full RAG pipeline:
    1. Stores the user message
    2. Retrieves relevant context from the knowledge base
    3. Generates an AI response
    4. Stores the response with context references
    """
    try:
        config = None
        if request.config_override:
            config = ChatConfig(
                model=request.config_override.model,
                temperature=request.config_override.temperature,
                max_tokens=request.config_override.max_tokens,
                context_limit=request.config_override.context_limit,
                max_context_chars=request.config_override.max_context_chars,
                w_bm25=request.config_override.w_bm25,
                w_vec=request.config_override.w_vec,
                include_conversation_history=request.config_override.include_conversation_history,
            )

        result = generate_response(
            conn, conversation_id, request.content, config=config
        )

        return ChatResponseSchema(
            content=result.content,
            segment_id=result.segment_id,
            context_used=[
                RetrievedContextSchema(
                    segment_id=ctx.segment_id,
                    document_id=ctx.document_id,
                    document_title=ctx.document_title,
                    source_system=ctx.source_system,
                    content=ctx.content,
                    score=ctx.score,
                    rank=ctx.rank,
                    source_role=ctx.source_role,
                )
                for ctx in result.context_used
            ],
            model=result.model,
            tokens_used=result.tokens_used,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/conversations/{conversation_id}/messages/stream")
def stream_message_endpoint(
    conversation_id: UUID,
    request: SendMessageRequest,
    conn=Depends(get_connection),
):
    """
    Send a message and stream the AI response via Server-Sent Events.

    The stream sends:
    - 'content' events with response chunks
    - 'context' event with the RAG context used
    - 'done' event with final metadata when complete
    """

    def generate_sse():
        try:
            config = None
            if request.config_override:
                config = ChatConfig(
                    model=request.config_override.model,
                    temperature=request.config_override.temperature,
                    max_tokens=request.config_override.max_tokens,
                    context_limit=request.config_override.context_limit,
                    max_context_chars=request.config_override.max_context_chars,
                    w_bm25=request.config_override.w_bm25,
                    w_vec=request.config_override.w_vec,
                    include_conversation_history=request.config_override.include_conversation_history,
                )

            # Use the streaming generator
            gen = generate_response_stream(
                conn, conversation_id, request.content, config=config
            )

            # Stream content chunks
            full_content = []
            try:
                while True:
                    chunk = next(gen)
                    full_content.append(chunk)
                    # SSE format: data: <json>\n\n
                    data = json.dumps({"type": "content", "content": chunk})
                    yield f"data: {data}\n\n"
            except StopIteration as e:
                # Generator finished, get the result
                result = e.value

            # Send context information
            context_data = [
                {
                    "segment_id": str(ctx.segment_id),
                    "document_id": str(ctx.document_id),
                    "document_title": ctx.document_title,
                    "source_system": ctx.source_system,
                    "content": ctx.content,
                    "score": ctx.score,
                    "rank": ctx.rank,
                    "source_role": ctx.source_role,
                }
                for ctx in result.context_used
            ]
            yield f"data: {json.dumps({'type': 'context', 'context': context_data})}\n\n"

            # Send completion event
            done_data = {
                "type": "done",
                "segment_id": str(result.segment_id),
                "model": result.model,
                "tokens_used": result.tokens_used,
            }
            yield f"data: {json.dumps(done_data)}\n\n"

        except ValueError as e:
            error_data = {"type": "error", "error": str(e)}
            yield f"data: {json.dumps(error_data)}\n\n"
        except RuntimeError as e:
            error_data = {"type": "error", "error": str(e)}
            yield f"data: {json.dumps(error_data)}\n\n"
        except Exception as e:
            logger.exception("Streaming error")
            error_data = {"type": "error", "error": "Internal server error"}
            yield f"data: {json.dumps(error_data)}\n\n"

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


# -----------------------------------------------------------------------------
# Context Retrieval
# -----------------------------------------------------------------------------


@router.get(
    "/segments/{segment_id}/context", response_model=List[RetrievedContextSchema]
)
def get_segment_context_endpoint(
    segment_id: UUID,
    conn=Depends(get_connection),
) -> List[RetrievedContextSchema]:
    """
    Get the RAG context that was used to generate a specific assistant response.

    This enables the "view sources" feature.
    """
    context = get_context_for_segment(conn, segment_id)
    return [
        RetrievedContextSchema(
            segment_id=ctx.segment_id,
            document_id=ctx.document_id,
            document_title=ctx.document_title,
            source_system=ctx.source_system,
            content=ctx.content,
            score=ctx.score,
            rank=ctx.rank,
            source_role=ctx.source_role,
        )
        for ctx in context
    ]
