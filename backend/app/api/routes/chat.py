"""API-Routen: Chat und RAG-Pipeline."""

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
    MessageResponse, SelectedCollectionsUpdate,
)

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


@router.post("/chat", response_model=ChatResponse)
async def ask_question(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Frage stellen und Antwort über die RAG-Pipeline erhalten.

    Ablauf:
    1. Ausgewählte Collections des Benutzers laden (oder aus Request übernehmen)
    2. Zugriffsrechte prüfen
    3. Query-Embedding berechnen
    4. Hybrid-Suche (Vektor + Volltext) in erlaubten Collections
    5. Reranking der Ergebnisse
    6. LLM-Prompt zusammenbauen (System-Prompt + Kontext + Frage)
    7. Antwort generieren und mit Quellen zurückgeben
    """
    # TODO: Implementierung der RAG-Pipeline
    # Hier wird der rag_pipeline Service aufgerufen:
    #
    # from app.services.rag_pipeline import RAGPipeline
    # pipeline = RAGPipeline(db, settings)
    # result = await pipeline.query(
    #     question=request.question,
    #     user=current_user,
    #     conversation_id=request.conversation_id,
    #     collection_ids=request.collection_ids,
    # )
    # return result

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="RAG-Pipeline noch nicht implementiert. Siehe IMPLEMENTATION_GUIDE.md Phase 3.",
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
