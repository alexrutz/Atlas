"""API-Routen: Chat und RAG-Pipeline."""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.conversation import Conversation, Message, UserSelectedCollection
from app.schemas.chat import (
    ChatRequest, ChatResponse, ConversationResponse,
    MessageResponse, SelectedCollectionsUpdate, SourceChunk,
)
from app.services.rag_pipeline import RAGPipeline

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
    # Prüfen ob Konversation dem Benutzer gehört
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Konversation nicht gefunden")

    # Nachrichten laden
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()

    response = []
    for msg in messages:
        sources = []
        if msg.source_chunks:
            # Chunk-Infos für Quellenangaben laden
            from app.models.chunk import Chunk
            from app.models.document import Document
            from app.models.collection import Collection
            chunk_result = await db.execute(
                select(
                    Chunk.id, Chunk.content, Chunk.page_number,
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
            rag_chunks=msg.metadata_.get("rag_chunks", []) if msg.metadata_ else [],
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
        )
        return result
    except Exception as e:
        logger.error(f"RAG-Pipeline Fehler: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler bei der Antwortgenerierung: {str(e)}",
        )


@router.post("/chat/stream")
async def ask_question_stream(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Frage stellen mit Streaming-Antwort über Server-Sent Events."""
    pipeline = RAGPipeline(db)

    try:
        # Retrieval durchführen (nicht-streaming Teil)
        allowed_ids = await pipeline._get_allowed_collection_ids(current_user)
        if not allowed_ids:
            async def no_access():
                data = json.dumps({"type": "error", "content": "Sie haben keinen Zugriff auf Collections."})
                yield f"data: {data}\n\n"
            return StreamingResponse(no_access(), media_type="text/event-stream")

        if request.collection_ids:
            search_ids = [cid for cid in request.collection_ids if cid in allowed_ids]
        else:
            search_ids = await pipeline._get_selected_collection_ids(current_user, allowed_ids)

        if not search_ids:
            async def no_collections():
                data = json.dumps({"type": "error", "content": "Bitte wählen Sie mindestens eine Collection aus."})
                yield f"data: {data}\n\n"
            return StreamingResponse(no_collections(), media_type="text/event-stream")

        # Query-Anreicherung: Suchanfrage mit Glossar/Kontext erweitern
        enriched_query = await pipeline.query_enrichment.enrich_query(
            query=request.question, collection_ids=search_ids,
        )

        results = await pipeline.retrieval.search(query=enriched_query, collection_ids=search_ids)

        # Fallback: Bei leeren Ergebnissen mit Original-Query erneut suchen
        if not results and enriched_query != request.question:
            logger.info("Angereicherte Query lieferte keine Ergebnisse, Fallback auf Original-Query")
            results = await pipeline.retrieval.search(query=request.question, collection_ids=search_ids)

        if not results:
            logger.warning(f"Keine Ergebnisse für Query '{request.question}' in Collections {search_ids}")
            async def no_results():
                data = json.dumps({"type": "error", "content": "Keine relevanten Informationen gefunden."})
                yield f"data: {data}\n\n"
            return StreamingResponse(no_results(), media_type="text/event-stream")

        # Quellen aufbauen
        sources = [
            SourceChunk(
                chunk_id=r.chunk_id,
                document_name=r.document_name,
                collection_name=r.collection_name,
                content_preview=r.content[:200] + "..." if len(r.content) > 200 else r.content,
                page_number=r.page_number,
                similarity_score=r.similarity_score,
            )
            for r in results
        ]

        # Prompt bauen
        contexts = [
            {"content": r.content, "document_name": r.document_name, "page_number": r.page_number}
            for r in results
        ]
        prompt = pipeline.llm.build_rag_prompt(request.question, contexts)

        # Vollständige Chunk-Kontexte für Debug-Anzeige aufbauen
        rag_chunks = [
            {
                "document_name": r.document_name,
                "collection_name": r.collection_name,
                "page_number": r.page_number,
                "content": r.content,
                "similarity_score": r.similarity_score,
            }
            for r in results
        ]

        async def event_stream():
            full_answer = ""
            try:
                # Enriched Query + RAG-Kontext senden (für Debug-Panel)
                debug_data = json.dumps({
                    "type": "debug_info",
                    "enriched_query": enriched_query,
                    "rag_chunks": rag_chunks,
                })
                yield f"data: {debug_data}\n\n"

                # Quellen zuerst senden
                sources_data = json.dumps({
                    "type": "sources",
                    "sources": [s.model_dump() for s in sources],
                })
                yield f"data: {sources_data}\n\n"

                # Streaming-Antwort
                async for token in pipeline.llm.generate_stream(prompt):
                    full_answer += token
                    data = json.dumps({"type": "token", "content": token})
                    yield f"data: {data}\n\n"

                # Konversation speichern
                conv_id = await pipeline._save_to_conversation(
                    user=current_user,
                    conversation_id=request.conversation_id,
                    question=request.question,
                    answer=full_answer,
                    results=results,
                    search_ids=search_ids,
                    enriched_query=enriched_query,
                    rag_chunks=rag_chunks,
                )
                await db.commit()

                done_data = json.dumps({"type": "done", "conversation_id": conv_id})
                yield f"data: {done_data}\n\n"
            except Exception as e:
                logger.error(f"Streaming-Fehler: {e}", exc_info=True)
                error_data = json.dumps({"type": "error", "content": str(e)})
                yield f"data: {error_data}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
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
    # Alte Auswahl löschen
    existing = await db.execute(
        select(UserSelectedCollection).where(UserSelectedCollection.user_id == current_user.id)
    )
    for sel in existing.scalars().all():
        await db.delete(sel)

    # Neue Auswahl setzen
    for cid in data.collection_ids:
        db.add(UserSelectedCollection(user_id=current_user.id, collection_id=cid))
