"""
API routes: Chat (RAG queries, streaming, document delivery) and Conversations.

This is the core of the application. It handles:
  - POST /api/chat         -> Non-streaming RAG query
  - POST /api/chat/stream  -> Streaming RAG query via Server-Sent Events (SSE)
  - PUT  /api/chat/collections -> Set which collections to search
  - GET/POST/DELETE /api/conversations -> Conversation history management

The RAG pipeline flow (for both streaming and non-streaming):
  1. Check permissions (which collections can this user access?)
  2. Optionally enrich the query with domain terminology
  3. Search for relevant document chunks (embed -> vector search -> rerank)
  4. Build a prompt with the retrieved chunks as context
  5. Generate an answer with the LLM
  6. Save the conversation to the database

Document delivery ("gib mir"):
  When the user starts their message with "gib mir" (German for "give me"),
  the system searches ALL collections and asks the LLM to identify which
  specific document the user wants.
"""

import json
import logging
import re
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.config import settings
from app.database import get_db
from app.auth import get_current_user
from app.models import (
    User, Document, Collection, Conversation, Message,
    UserSelectedCollection, GroupCollectionAccess, UserGroup, Chunk,
)
from app.schemas import (
    ChatRequest, ChatResponse, SourceChunk, SelectedCollectionsUpdate,
    ConversationResponse, MessageResponse,
)
from app.search import search_chunks
from app.llm import (
    generate, generate_stream, enrich_query, log_llm_call,
    build_rag_prompt, build_document_delivery_prompt,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Pattern to detect "gib mir" trigger (case-insensitive, at start of message)
_GIB_MIR_PATTERN = re.compile(r"^\s*gib\s+mir\b", re.IGNORECASE)

# Pattern to extract the tool call from LLM response
_DELIVER_DOC_PATTERN = re.compile(
    r"<<<DELIVER_DOCUMENT>>>\s*(\{.*?\})\s*<<<END_DELIVER_DOCUMENT>>>",
    re.DOTALL,
)


# =============================================================================
# Permission and conversation helpers (absorbed from rag_pipeline.py)
# =============================================================================

async def get_allowed_collection_ids(db: AsyncSession, user: User) -> list[int]:
    """
    Get all collection IDs the user has read access to.

    Access control: User -> belongs to Groups -> Groups have access to Collections.
    Admins can access all collections.
    """
    if user.is_admin:
        result = await db.execute(select(Collection.id))
        return [row[0] for row in result.fetchall()]

    result = await db.execute(
        select(GroupCollectionAccess.collection_id)
        .join(UserGroup, UserGroup.group_id == GroupCollectionAccess.group_id)
        .where(UserGroup.user_id == user.id, GroupCollectionAccess.can_read.is_(True))
        .distinct()
    )
    return [row[0] for row in result.fetchall()]


async def get_selected_collection_ids(
    db: AsyncSession, user: User, allowed_ids: list[int],
) -> list[int]:
    """Get the user's selected collections, filtered to only allowed ones."""
    result = await db.execute(
        select(UserSelectedCollection.collection_id)
        .where(UserSelectedCollection.user_id == user.id)
    )
    selected = [row[0] for row in result.fetchall()]

    if selected:
        return [cid for cid in selected if cid in allowed_ids]
    return allowed_ids


async def save_to_conversation(
    db: AsyncSession,
    user: User,
    conversation_id: int | None,
    question: str,
    answer: str,
    results,
    search_ids: list[int],
    enriched_query: str | None = None,
    rag_chunks: list[dict] | None = None,
    thinking: str | None = None,
    document_delivery: dict | None = None,
) -> int:
    """
    Save the user's question and the assistant's answer to conversation history.

    If conversation_id is provided, appends to that conversation.
    Otherwise creates a new conversation.
    """
    if conversation_id:
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user.id,
            )
        )
        conv = result.scalar_one_or_none()
        if not conv:
            conv = Conversation(user_id=user.id, title=question[:100])
            db.add(conv)
            await db.flush()
    else:
        conv = Conversation(user_id=user.id, title=question[:100])
        db.add(conv)
        await db.flush()

    user_msg = Message(
        conversation_id=conv.id, role="user", content=question,
        used_collections=search_ids,
        metadata_={"enriched_query": enriched_query} if enriched_query else {},
    )
    db.add(user_msg)

    assistant_metadata = {}
    if rag_chunks:
        assistant_metadata["rag_chunks"] = rag_chunks
    if thinking:
        assistant_metadata["thinking"] = thinking
    if document_delivery:
        assistant_metadata["document_delivery"] = document_delivery
    assistant_msg = Message(
        conversation_id=conv.id, role="assistant", content=answer,
        source_chunks=[r.chunk_id for r in results] if results else [],
        metadata_=assistant_metadata,
    )
    db.add(assistant_msg)
    await db.flush()

    return conv.id


# =============================================================================
# Non-streaming chat endpoint
# =============================================================================

@router.post("/chat", response_model=ChatResponse)
async def ask_question(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ask a question and get an answer via the RAG pipeline."""
    try:
        # Free chat mode (no retrieval)
        if not request.rag_mode:
            system = settings.llm_free_chat_system_prompt or settings.llm_system_prompt
            result = await generate(request.question, system_prompt=system, enable_thinking=request.enable_thinking)
            conv_id = await save_to_conversation(
                db=db, user=current_user, conversation_id=request.conversation_id,
                question=request.question, answer=result["content"],
                results=[], search_ids=[], thinking=result.get("thinking"),
            )
            return ChatResponse(answer=result["content"], conversation_id=conv_id, sources=[])

        # RAG mode
        allowed_ids = await get_allowed_collection_ids(db, current_user)
        if not allowed_ids:
            return ChatResponse(answer="Sie haben keinen Zugriff auf Collections.", conversation_id=request.conversation_id or 0, sources=[])

        if request.collection_ids:
            search_ids = [cid for cid in request.collection_ids if cid in allowed_ids]
        else:
            search_ids = await get_selected_collection_ids(db, current_user, allowed_ids)

        if not search_ids:
            return ChatResponse(answer="Bitte wählen Sie mindestens eine Collection aus.", conversation_id=request.conversation_id or 0, sources=[])

        # Query enrichment
        if request.enable_enrichment:
            enriched_query = await enrich_query(db=db, query=request.question, collection_ids=search_ids, enable_thinking=request.enable_enrichment_thinking)
        else:
            enriched_query = request.question

        # Retrieval
        results = await search_chunks(db=db, query=enriched_query, collection_ids=search_ids)
        if not results and enriched_query != request.question:
            results = await search_chunks(db=db, query=request.question, collection_ids=search_ids)
        if not results:
            return ChatResponse(answer="Keine relevanten Informationen gefunden.", conversation_id=request.conversation_id or 0, sources=[])

        # Build LLM prompt
        contexts = [
            {"content": r.content, "document_name": r.document_name, "page_number": r.page_number}
            for r in results
        ]
        prompt = build_rag_prompt(request.question, enriched_query, contexts)

        # Generate answer
        result = await generate(prompt, enable_thinking=request.enable_thinking)
        answer = result["content"]

        # Save conversation
        rag_chunks = [
            {"document_id": r.document_id, "document_name": r.document_name, "collection_name": r.collection_name,
             "page_number": r.page_number, "content": r.content, "similarity_score": r.similarity_score}
            for r in results
        ]
        conv_id = await save_to_conversation(
            db=db, user=current_user, conversation_id=request.conversation_id,
            question=request.question, answer=answer, results=results,
            search_ids=search_ids, enriched_query=enriched_query,
            rag_chunks=rag_chunks, thinking=result.get("thinking"),
        )

        sources = [
            SourceChunk(
                chunk_id=r.chunk_id, document_id=r.document_id, document_name=r.document_name,
                collection_name=r.collection_name,
                content_preview=r.content[:200] + "..." if len(r.content) > 200 else r.content,
                page_number=r.page_number, similarity_score=r.similarity_score,
            )
            for r in results
        ]

        return ChatResponse(answer=answer, conversation_id=conv_id, sources=sources)
    except Exception as e:
        logger.error(f"RAG pipeline error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler bei der Antwortgenerierung: {str(e)}",
        )


# =============================================================================
# Streaming chat endpoint (Server-Sent Events)
# =============================================================================

@router.post("/chat/stream")
async def ask_question_stream(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ask a question with streaming answer via Server-Sent Events."""
    is_document_delivery = bool(_GIB_MIR_PATTERN.search(request.question))

    try:
        # Free chat mode - no retrieval needed (but not for "gib mir")
        if not request.rag_mode and not is_document_delivery:
            return StreamingResponse(
                _free_chat_stream(request, current_user, db),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )

        # RAG mode (or document delivery mode)
        allowed_ids = await get_allowed_collection_ids(db, current_user)
        if not allowed_ids:
            return _sse_error("Sie haben keinen Zugriff auf Collections.")

        # Determine which collections to search
        if is_document_delivery:
            search_ids = allowed_ids
            logger.info(f"Document delivery mode: searching all {len(search_ids)} collections")
        elif request.collection_ids:
            search_ids = [cid for cid in request.collection_ids if cid in allowed_ids]
        else:
            search_ids = await get_selected_collection_ids(db, current_user, allowed_ids)

        if not search_ids:
            return _sse_error("Bitte wählen Sie mindestens eine Collection aus.")

        # Query enrichment
        if request.enable_enrichment:
            enriched_query = await enrich_query(
                db=db, query=request.question, collection_ids=search_ids,
                enable_thinking=request.enable_enrichment_thinking,
            )
        else:
            enriched_query = request.question

        # Retrieve relevant chunks
        results = await search_chunks(db=db, query=enriched_query, collection_ids=search_ids)
        if not results and enriched_query != request.question:
            results = await search_chunks(db=db, query=request.question, collection_ids=search_ids)
        if not results:
            return _sse_error("Keine relevanten Informationen gefunden.")

        # Build the LLM prompt
        contexts = [
            {"content": r.content, "document_name": r.document_name,
             "page_number": r.page_number, "document_id": r.document_id}
            for r in results
        ]

        if is_document_delivery:
            prompt = build_document_delivery_prompt(request.question, enriched_query, contexts)
        else:
            prompt = build_rag_prompt(request.question, enriched_query, contexts)

        return StreamingResponse(
            _rag_stream(request, current_user, db, prompt, enriched_query, results, search_ids, is_document_delivery),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    except Exception as e:
        logger.error(f"Stream setup error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler bei der Antwortgenerierung: {str(e)}",
        )


# =============================================================================
# Collection selection
# =============================================================================

@router.put("/chat/collections", status_code=status.HTTP_204_NO_CONTENT)
async def update_selected_collections(
    data: SelectedCollectionsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set active collections for the current user."""
    existing = await db.execute(
        select(UserSelectedCollection).where(UserSelectedCollection.user_id == current_user.id)
    )
    for sel in existing.scalars().all():
        await db.delete(sel)

    for cid in data.collection_ids:
        db.add(UserSelectedCollection(user_id=current_user.id, collection_id=cid))


# =============================================================================
# SSE stream generators
# =============================================================================

def _sse_error(message: str):
    """Return a StreamingResponse with a single error event."""
    async def gen():
        data = json.dumps({"type": "error", "content": message})
        yield f"data: {data}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


async def _free_chat_stream(request: ChatRequest, user: User, db: AsyncSession):
    """SSE generator for free chat mode (no retrieval)."""
    system = settings.llm_free_chat_system_prompt or settings.llm_system_prompt
    full_answer = ""
    full_thinking = ""

    log_llm_call(
        "FREE CHAT LLM",
        system_prompt=system,
        user_prompt=request.question,
        enable_thinking=request.enable_thinking,
        is_stream_start=True,
    )

    try:
        async for chunk in generate_stream(
            request.question,
            system_prompt=system,
            enable_thinking=request.enable_thinking,
        ):
            if chunk["type"] == "thinking":
                full_thinking += chunk["text"]
                data = json.dumps({"type": "thinking", "content": chunk["text"]})
                yield f"data: {data}\n\n"
            elif chunk["type"] == "content":
                full_answer += chunk["text"]
                data = json.dumps({"type": "token", "content": chunk["text"]})
                yield f"data: {data}\n\n"

        log_llm_call(
            "FREE CHAT LLM (stream complete)",
            output=full_answer,
            thinking=full_thinking or None,
        )

        conv_id = await save_to_conversation(
            db=db, user=user,
            conversation_id=request.conversation_id,
            question=request.question, answer=full_answer,
            results=[], search_ids=[],
            thinking=full_thinking or None,
        )
        await db.commit()

        done_data = json.dumps({"type": "done", "conversation_id": conv_id})
        yield f"data: {done_data}\n\n"
    except Exception as e:
        logger.error(f"Free-Chat streaming error: {e}", exc_info=True)
        error_data = json.dumps({"type": "error", "content": str(e)})
        yield f"data: {error_data}\n\n"


async def _rag_stream(
    request: ChatRequest, user: User, db: AsyncSession,
    prompt: str, enriched_query: str, results: list,
    search_ids: list[int], is_document_delivery: bool,
):
    """SSE generator for RAG mode (with retrieval, optional document delivery)."""
    sources = [
        SourceChunk(
            chunk_id=r.chunk_id, document_id=r.document_id,
            document_name=r.document_name,
            collection_name=r.collection_name,
            content_preview=r.content[:200] + "..." if len(r.content) > 200 else r.content,
            page_number=r.page_number, similarity_score=r.similarity_score,
        )
        for r in results
    ]

    rag_chunks = [
        {"document_id": r.document_id, "document_name": r.document_name,
         "collection_name": r.collection_name, "page_number": r.page_number,
         "content": r.content, "similarity_score": r.similarity_score}
        for r in results
    ]

    full_answer = ""
    full_thinking = ""

    try:
        # Send debug info
        debug_data = json.dumps({
            "type": "debug_info",
            "enriched_query": enriched_query,
            "rag_chunks": rag_chunks,
        })
        yield f"data: {debug_data}\n\n"

        # Send sources
        sources_data = json.dumps({
            "type": "sources",
            "sources": [s.model_dump() for s in sources],
        })
        yield f"data: {sources_data}\n\n"

        # Stream the LLM answer
        async for chunk in generate_stream(prompt, enable_thinking=request.enable_thinking):
            if chunk["type"] == "thinking":
                full_thinking += chunk["text"]
                data = json.dumps({"type": "thinking", "content": chunk["text"]})
                yield f"data: {data}\n\n"
            elif chunk["type"] == "content":
                full_answer += chunk["text"]
                data = json.dumps({"type": "token", "content": chunk["text"]})
                yield f"data: {data}\n\n"

        log_llm_call("FINAL RAG LLM (stream complete)", output=full_answer, thinking=full_thinking or None)

        # Document delivery: parse LLM response for tool call
        delivery_info = None
        if is_document_delivery:
            delivery_info = await _resolve_document_delivery(db, full_answer, results)
            if delivery_info:
                delivery_data = json.dumps({"type": "document_delivery", **delivery_info})
                yield f"data: {delivery_data}\n\n"
                full_answer = _DELIVER_DOC_PATTERN.sub("", full_answer).strip()

        # Save conversation
        conv_id = await save_to_conversation(
            db=db, user=user,
            conversation_id=request.conversation_id,
            question=request.question, answer=full_answer,
            results=results, search_ids=search_ids,
            enriched_query=enriched_query, rag_chunks=rag_chunks,
            thinking=full_thinking or None,
            document_delivery=delivery_info,
        )
        await db.commit()

        done_data = json.dumps({"type": "done", "conversation_id": conv_id})
        yield f"data: {done_data}\n\n"
    except Exception as e:
        logger.error(f"Streaming error: {e}", exc_info=True)
        error_data = json.dumps({"type": "error", "content": str(e)})
        yield f"data: {error_data}\n\n"


# =============================================================================
# Document delivery resolution
# =============================================================================

async def _resolve_document_delivery(
    db: AsyncSession, full_answer: str, results: list,
) -> dict | None:
    """Parse the LLM response for a <<<DELIVER_DOCUMENT>>> tool call and resolve the document."""
    match = _DELIVER_DOC_PATTERN.search(full_answer)
    if not match:
        return None

    try:
        tool_call = json.loads(match.group(1))
    except json.JSONDecodeError:
        logger.warning("Failed to parse DELIVER_DOCUMENT JSON from LLM response")
        return None

    doc_name = tool_call.get("document_name", "")
    doc_id = tool_call.get("document_id")

    document = None
    if doc_id:
        result = await db.execute(select(Document).where(Document.id == int(doc_id)))
        document = result.scalar_one_or_none()

    if not document and doc_name:
        result = await db.execute(
            select(Document).where(Document.original_name == doc_name)
        )
        document = result.scalar_one_or_none()

    if not document and results:
        doc_counts = Counter(r.document_name for r in results)
        most_common_name = doc_counts.most_common(1)[0][0]
        result = await db.execute(
            select(Document).where(Document.original_name == most_common_name)
        )
        document = result.scalar_one_or_none()

    if not document:
        return None

    col_result = await db.execute(
        select(Collection.name).where(Collection.id == document.collection_id)
    )
    collection_name = col_result.scalar_one_or_none() or "Unknown"

    page_count = 1
    if document.file_type == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(document.file_path)
            page_count = len(reader.pages)
        except Exception:
            pass

    return {
        "document_id": document.id,
        "document_name": document.original_name,
        "collection_name": collection_name,
        "file_type": document.file_type,
        "page_count": page_count,
        "reason": tool_call.get("reason", ""),
    }


# =============================================================================
# Conversation management endpoints
# =============================================================================

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
