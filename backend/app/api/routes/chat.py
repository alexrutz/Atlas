"""API-Routen: Chat und RAG-Pipeline."""

import json
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.document import Document
from app.models.collection import Collection
from app.models.conversation import Conversation, Message, UserSelectedCollection
from app.schemas.chat import (
    ChatRequest, ChatResponse, ConversationResponse,
    MessageResponse, SelectedCollectionsUpdate, SourceChunk,
)
from app.services.rag_pipeline import RAGPipeline
from app.services.llm_diagnostic import (
    log_free_chat_call,
    log_free_chat_stream_complete,
    log_rag_stream_complete,
)

# Pattern to detect "gib mir" trigger (case-insensitive, at start of message)
_GIB_MIR_PATTERN = re.compile(r"^\s*gib\s+mir\b", re.IGNORECASE)

# Pattern to extract the tool call from LLM response
_DELIVER_DOC_PATTERN = re.compile(
    r"<<<DELIVER_DOCUMENT>>>\s*(\{.*?\})\s*<<<END_DELIVER_DOCUMENT>>>",
    re.DOTALL,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Eigene Konversationen auflisten."""
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
    """Neue Konversation erstellen."""
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
    """Konversation löschen."""
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
    """Nachrichten einer Konversation laden."""
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
            from app.models.chunk import Chunk
            from app.models.document import Document as DocModel
            from app.models.collection import Collection as ColModel
            chunk_result = await db.execute(
                select(
                    Chunk.id, Chunk.content, Chunk.page_number,
                    Chunk.document_id,
                    DocModel.original_name.label("document_name"),
                    ColModel.name.label("collection_name"),
                )
                .join(DocModel, Chunk.document_id == DocModel.id)
                .join(ColModel, DocModel.collection_id == ColModel.id)
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


@router.post("/chat", response_model=ChatResponse)
async def ask_question(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Frage stellen und Antwort über die RAG-Pipeline erhalten."""
    try:
        pipeline = RAGPipeline(db)
        result = await pipeline.query(
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
        logger.error(f"RAG-Pipeline Fehler: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler bei der Antwortgenerierung: {str(e)}",
        )


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
        # Use the most frequently occurring document in results
        from collections import Counter
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


@router.post("/chat/stream")
async def ask_question_stream(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Frage stellen mit Streaming-Antwort über Server-Sent Events."""
    pipeline = RAGPipeline(db)
    is_document_delivery = bool(_GIB_MIR_PATTERN.search(request.question))

    try:
        # Free chat mode - no retrieval needed (but not for "gib mir")
        if not request.rag_mode and not is_document_delivery:
            system = pipeline.llm.config.free_chat_system_prompt or pipeline.llm.config.system_prompt

            async def free_chat_stream():
                full_answer = ""
                full_thinking = ""
                log_free_chat_call(
                    system_prompt=system,
                    user_prompt=request.question,
                    enable_thinking=request.enable_thinking,
                    is_stream_start=True,
                )
                try:
                    async for chunk in pipeline.llm.generate_stream(
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

                    conv_id = await pipeline._save_to_conversation(
                        user=current_user,
                        conversation_id=request.conversation_id,
                        question=request.question,
                        answer=full_answer,
                        results=[],
                        search_ids=[],
                        thinking=full_thinking or None,
                    )
                    await db.commit()

                    done_data = json.dumps({"type": "done", "conversation_id": conv_id})
                    yield f"data: {done_data}\n\n"
                except Exception as e:
                    logger.error(f"Free-Chat Streaming-Fehler: {e}", exc_info=True)
                    error_data = json.dumps({"type": "error", "content": str(e)})
                    yield f"data: {error_data}\n\n"

            return StreamingResponse(
                free_chat_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )

        # RAG mode (or document delivery mode)
        allowed_ids = await pipeline._get_allowed_collection_ids(current_user)
        if not allowed_ids:
            async def no_access():
                data = json.dumps({"type": "error", "content": "Sie haben keinen Zugriff auf Collections."})
                yield f"data: {data}\n\n"
            return StreamingResponse(no_access(), media_type="text/event-stream")

        if is_document_delivery:
            # Document delivery: ALWAYS search ALL accessible collections
            search_ids = allowed_ids
            logger.info(f"Document delivery mode: searching all {len(search_ids)} collections")
        elif request.collection_ids:
            search_ids = [cid for cid in request.collection_ids if cid in allowed_ids]
        else:
            search_ids = await pipeline._get_selected_collection_ids(current_user, allowed_ids)

        if not search_ids:
            async def no_collections():
                data = json.dumps({"type": "error", "content": "Bitte wählen Sie mindestens eine Collection aus."})
                yield f"data: {data}\n\n"
            return StreamingResponse(no_collections(), media_type="text/event-stream")

        # Query enrichment
        if request.enable_enrichment:
            enriched_query = await pipeline.query_enrichment.enrich_query(
                query=request.question, collection_ids=search_ids,
                enable_thinking=request.enable_enrichment_thinking,
            )
        else:
            enriched_query = request.question

        results = await pipeline.retrieval.search(query=enriched_query, collection_ids=search_ids)

        if not results and enriched_query != request.question:
            results = await pipeline.retrieval.search(query=request.question, collection_ids=search_ids)

        if not results:
            async def no_results():
                data = json.dumps({"type": "error", "content": "Keine relevanten Informationen gefunden."})
                yield f"data: {data}\n\n"
            return StreamingResponse(no_results(), media_type="text/event-stream")

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

        # Build contexts - include document_id for document delivery
        contexts = [
            {
                "content": r.content,
                "document_name": r.document_name,
                "page_number": r.page_number,
                "document_id": r.document_id,
            }
            for r in results
        ]

        # Use special document delivery prompt or standard RAG prompt
        if is_document_delivery:
            prompt = pipeline.llm.build_document_delivery_prompt(
                request.question, enriched_query, contexts,
            )
        else:
            prompt = pipeline.llm.build_rag_prompt(request.question, enriched_query, contexts)

        rag_chunks = [
            {
                "document_id": r.document_id,
                "document_name": r.document_name, "collection_name": r.collection_name,
                "page_number": r.page_number, "content": r.content,
                "similarity_score": r.similarity_score,
            }
            for r in results
        ]

        async def event_stream():
            full_answer = ""
            full_thinking = ""
            try:
                # Debug info
                debug_data = json.dumps({
                    "type": "debug_info",
                    "enriched_query": enriched_query,
                    "rag_chunks": rag_chunks,
                })
                yield f"data: {debug_data}\n\n"

                # Sources
                sources_data = json.dumps({
                    "type": "sources",
                    "sources": [s.model_dump() for s in sources],
                })
                yield f"data: {sources_data}\n\n"

                # Streaming answer with thinking
                async for chunk in pipeline.llm.generate_stream(
                    prompt,
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

                # Diagnostic: log stream completion
                log_rag_stream_complete(
                    output=full_answer,
                    thinking=full_thinking or None,
                )

                # Document delivery: parse LLM response for tool call
                delivery_info = None
                if is_document_delivery:
                    delivery_info = await _resolve_document_delivery(db, full_answer, results)
                    if delivery_info:
                        delivery_data = json.dumps({
                            "type": "document_delivery",
                            **delivery_info,
                        })
                        yield f"data: {delivery_data}\n\n"

                        # Clean the tool call markers from the saved answer
                        clean_answer = _DELIVER_DOC_PATTERN.sub("", full_answer).strip()
                        full_answer = clean_answer

                # Save conversation
                conv_id = await pipeline._save_to_conversation(
                    user=current_user,
                    conversation_id=request.conversation_id,
                    question=request.question,
                    answer=full_answer,
                    results=results,
                    search_ids=search_ids,
                    enriched_query=enriched_query,
                    rag_chunks=rag_chunks,
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

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    except Exception as e:
        logger.error(f"Stream-Setup Fehler: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler bei der Antwortgenerierung: {str(e)}",
        )


@router.put("/chat/collections", status_code=status.HTTP_204_NO_CONTENT)
async def update_selected_collections(
    data: SelectedCollectionsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aktive Collections für den aktuellen Benutzer setzen."""
    existing = await db.execute(
        select(UserSelectedCollection).where(UserSelectedCollection.user_id == current_user.id)
    )
    for sel in existing.scalars().all():
        await db.delete(sel)

    for cid in data.collection_ids:
        db.add(UserSelectedCollection(user_id=current_user.id, collection_id=cid))
