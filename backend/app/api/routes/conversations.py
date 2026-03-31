"""API routes: Conversation management (list, create, delete, messages)."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.collection import Collection
from app.models.conversation import Conversation, Message
from app.schemas.chat import (
    ConversationResponse, MessageResponse, SourceChunk,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List own conversations."""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
    )
    conversations = result.scalars().all()

    response = []
    for conv in conversations:
        count_result = await db.execute(
            select(func.count()).select_from(Message).where(Message.conversation_id == conv.id)
        )
        msg_count = count_result.scalar() or 0
        response.append(ConversationResponse(
            id=conv.id, title=conv.title, created_at=conv.created_at, message_count=msg_count,
        ))
    return response


@router.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new conversation."""
    conv = Conversation(user_id=current_user.id, title="Neue Konversation")
    db.add(conv)
    await db.flush()
    await db.refresh(conv)
    return ConversationResponse(id=conv.id, title=conv.title, created_at=conv.created_at, message_count=0)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a conversation."""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Konversation nicht gefunden")
    await db.delete(conv)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
async def get_conversation_messages(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Load messages of a conversation."""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Konversation nicht gefunden")

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()

    response = []
    for msg in messages:
        sources = []
        # Reconstruct sources from rag_chunks metadata (has scores + document_id)
        stored_rag_chunks = msg.metadata_.get("rag_chunks", []) if msg.metadata_ else []
        if stored_rag_chunks:
            for i, rc in enumerate(stored_rag_chunks):
                content = rc.get("content", "")
                sources.append(SourceChunk(
                    chunk_id=msg.source_chunks[i] if msg.source_chunks and i < len(msg.source_chunks) else 0,
                    document_id=rc.get("document_id"),
                    document_name=rc.get("document_name", ""),
                    collection_name=rc.get("collection_name", ""),
                    content_preview=content[:200] + "..." if len(content) > 200 else content,
                    page_number=rc.get("page_number"),
                    similarity_score=rc.get("similarity_score", 0.0),
                ))
        elif msg.source_chunks:
            # Fallback for old messages without rag_chunks metadata
            chunk_result = await db.execute(
                select(
                    Chunk.id, Chunk.content, Chunk.page_number,
                    Chunk.document_id,
                    Document.original_name.label("document_name"),
                    Collection.name.label("collection_name"),
                )
                .join(Document, Chunk.document_id == Document.id)
                .join(Collection, Document.collection_id == Collection.id)
                .where(Chunk.id.in_(msg.source_chunks))
            )
            for row in chunk_result.fetchall():
                sources.append(SourceChunk(
                    chunk_id=row.id,
                    document_id=row.document_id,
                    document_name=row.document_name,
                    collection_name=row.collection_name,
                    content_preview=row.content[:200] + "..." if len(row.content) > 200 else row.content,
                    page_number=row.page_number,
                    similarity_score=0.0,
                ))

        response.append(MessageResponse(
            id=msg.id,
            role=msg.role,
            content=msg.content,
            sources=sources,
            enriched_query=msg.metadata_.get("enriched_query") if msg.metadata_ else None,
            rag_chunks=stored_rag_chunks,
            thinking=msg.metadata_.get("thinking") if msg.metadata_ else None,
            document_delivery=msg.metadata_.get("document_delivery") if msg.metadata_ else None,
            created_at=msg.created_at,
        ))
    return response
