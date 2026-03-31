"""
API routes: Chat endpoints (RAG, free chat, document delivery, streaming).

This file handles the main chat functionality:
  - POST /api/chat         → Non-streaming RAG query (returns full answer at once)
  - POST /api/chat/stream  → Streaming RAG query (returns answer token by token via SSE)
  - PUT  /api/chat/collections → Set which collections the user wants to search in

Streaming uses Server-Sent Events (SSE):
  The frontend opens a connection and receives events like:
    data: {"type": "sources", "sources": [...]}     ← retrieved document chunks
    data: {"type": "thinking", "content": "..."}    ← LLM reasoning (optional)
    data: {"type": "token", "content": "..."}       ← answer text, one piece at a time
    data: {"type": "document_delivery", ...}        ← document to download (for "gib mir")
    data: {"type": "done", "conversation_id": 123}  ← finished

Document delivery ("gib mir"):
  When the user starts their message with "gib mir" (German for "give me"),
  the system searches ALL collections and asks the LLM to identify which
  specific document the user wants. The LLM responds with a special tool call
  that the frontend uses to offer the document for download.
"""

import json
import logging
import re
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.document import Document
from app.models.collection import Collection
from app.models.conversation import UserSelectedCollection
from app.schemas.chat import (
    ChatRequest, ChatResponse, SourceChunk, SelectedCollectionsUpdate,
)
from app.services.rag_pipeline import (
    run_rag_query,
    get_allowed_collection_ids,
    get_selected_collection_ids,
    save_to_conversation,
)
from app.services.retrieval_service import search_chunks
from app.services.query_enrichment_service import enrich_query
from app.services.llm_service import (
    generate_stream,
    build_rag_prompt,
    build_document_delivery_prompt,
)
from app.services.llm_diagnostic import (
    log_free_chat_call,
    log_free_chat_stream_complete,
    log_rag_stream_complete,
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
        result = await run_rag_query(
            db=db,
            question=request.question,
            user=current_user,
            conversation_id=request.conversation_id,
            collection_ids=request.collection_ids,
            enable_thinking=request.enable_thinking,
            enable_enrichment_thinking=request.enable_enrichment_thinking,
            enable_enrichment=request.enable_enrichment,
            rag_mode=request.rag_mode,
        )
        return result
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
            # Document delivery: ALWAYS search ALL accessible collections
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

        # Fallback: if enriched query found nothing, try original query
        if not results and enriched_query != request.question:
            results = await search_chunks(db=db, query=request.question, collection_ids=search_ids)

        if not results:
            return _sse_error("Keine relevanten Informationen gefunden.")

        # Build the LLM prompt (document delivery or standard RAG)
        contexts = [
            {
                "content": r.content,
                "document_name": r.document_name,
                "page_number": r.page_number,
                "document_id": r.document_id,
            }
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
# Helper: SSE generators
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

    log_free_chat_call(
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

        log_free_chat_stream_complete(
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
    # Build source info for the client
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
        {
            "document_id": r.document_id,
            "document_name": r.document_name, "collection_name": r.collection_name,
            "page_number": r.page_number, "content": r.content,
            "similarity_score": r.similarity_score,
        }
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

        log_rag_stream_complete(output=full_answer, thinking=full_thinking or None)

        # Document delivery: parse LLM response for tool call
        delivery_info = None
        if is_document_delivery:
            delivery_info = await _resolve_document_delivery(db, full_answer, results)
            if delivery_info:
                delivery_data = json.dumps({"type": "document_delivery", **delivery_info})
                yield f"data: {delivery_data}\n\n"

                # Clean the tool call markers from the saved answer
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
# Helper: Document delivery resolution
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

    # Try to find the document by ID first, then by name
    document = None
    if doc_id:
        result = await db.execute(select(Document).where(Document.id == int(doc_id)))
        document = result.scalar_one_or_none()

    if not document and doc_name:
        result = await db.execute(
            select(Document).where(Document.original_name == doc_name)
        )
        document = result.scalar_one_or_none()

    # Fallback: find document by matching against retrieval result document names
    if not document and results:
        doc_counts = Counter(r.document_name for r in results)
        most_common_name = doc_counts.most_common(1)[0][0]
        result = await db.execute(
            select(Document).where(Document.original_name == most_common_name)
        )
        document = result.scalar_one_or_none()

    if not document:
        return None

    # Get collection name
    col_result = await db.execute(
        select(Collection.name).where(Collection.id == document.collection_id)
    )
    collection_name = col_result.scalar_one_or_none() or "Unknown"

    # Get page count for PDFs
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
