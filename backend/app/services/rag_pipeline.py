"""
RAG Pipeline - Orchestrates the full question-answering process.

Supports:
- RAG mode: Retrieval + answer generation with document context
- Free chat mode: Direct conversation without document context
- Thinking mode: Shows the LLM's reasoning process

Functions:
    run_rag_query(db, question, user, ...) - Full RAG pipeline
    run_free_chat(db, question, user, ...) - Free chat without retrieval
    get_allowed_collection_ids(db, user)   - Get collections user can access
    get_selected_collection_ids(db, user, allowed_ids) - Get user's selected collections
    save_to_conversation(db, user, ...)    - Save messages to conversation history
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.user import User
from app.models.conversation import Conversation, Message, UserSelectedCollection
from app.models.collection import Collection, GroupCollectionAccess
from app.models.group import UserGroup
from app.services.retrieval_service import search_chunks
from app.services.llm_service import generate, build_rag_prompt
from app.services.query_enrichment_service import enrich_query
from app.schemas.chat import ChatResponse, SourceChunk

logger = logging.getLogger(__name__)


async def run_rag_query(
    db: AsyncSession,
    question: str,
    user: User,
    conversation_id: int | None = None,
    collection_ids: list[int] | None = None,
    enable_thinking: bool = False,
    enable_enrichment_thinking: bool = False,
    enable_enrichment: bool = True,
    rag_mode: bool = True,
) -> ChatResponse:
    """Process a user question through the full RAG pipeline."""
    if not rag_mode:
        return await run_free_chat(db, question, user, conversation_id, enable_thinking)

    # 1. Get allowed collections
    allowed_ids = await get_allowed_collection_ids(db, user)
    if not allowed_ids:
        return ChatResponse(
            answer="Sie haben keinen Zugriff auf Collections.",
            conversation_id=conversation_id or 0,
            sources=[],
        )

    if collection_ids:
        search_ids = [cid for cid in collection_ids if cid in allowed_ids]
    else:
        search_ids = await get_selected_collection_ids(db, user, allowed_ids)

    if not search_ids:
        return ChatResponse(
            answer="Bitte wählen Sie mindestens eine Collection aus.",
            conversation_id=conversation_id or 0,
            sources=[],
        )

    # 2. Query enrichment
    if enable_enrichment:
        enriched_query = await enrich_query(
            db=db, query=question, collection_ids=search_ids,
            enable_thinking=enable_enrichment_thinking,
        )
    else:
        enriched_query = question

    # 3. Retrieval
    results = await search_chunks(db=db, query=enriched_query, collection_ids=search_ids)

    if not results and enriched_query != question:
        results = await search_chunks(db=db, query=question, collection_ids=search_ids)

    if not results:
        return ChatResponse(
            answer="Keine relevanten Informationen gefunden.",
            conversation_id=conversation_id or 0,
            sources=[],
        )

    # 4. Build LLM prompt
    contexts = [
        {"content": r.content, "document_name": r.document_name, "page_number": r.page_number}
        for r in results
    ]
    prompt = build_rag_prompt(question, enriched_query, contexts)

    # 5. Generate answer
    result = await generate(prompt, enable_thinking=enable_thinking)
    answer = result["content"]

    # 6. Save conversation
    rag_chunks = [
        {
            "document_id": r.document_id,
            "document_name": r.document_name,
            "collection_name": r.collection_name,
            "page_number": r.page_number,
            "content": r.content,
            "similarity_score": r.similarity_score,
        }
        for r in results
    ]
    conv_id = await save_to_conversation(
        db=db, user=user, conversation_id=conversation_id,
        question=question, answer=answer, results=results,
        search_ids=search_ids, enriched_query=enriched_query,
        rag_chunks=rag_chunks, thinking=result.get("thinking"),
    )

    sources = [
        SourceChunk(
            chunk_id=r.chunk_id, document_name=r.document_name,
            collection_name=r.collection_name,
            content_preview=r.content[:200] + "..." if len(r.content) > 200 else r.content,
            page_number=r.page_number, similarity_score=r.similarity_score,
        )
        for r in results
    ]

    return ChatResponse(answer=answer, conversation_id=conv_id, sources=sources)


async def run_free_chat(
    db: AsyncSession,
    question: str,
    user: User,
    conversation_id: int | None,
    enable_thinking: bool,
) -> ChatResponse:
    """Direct conversation without RAG context."""
    config = settings.llm
    system = config.free_chat_system_prompt or config.system_prompt
    result = await generate(question, system_prompt=system, enable_thinking=enable_thinking)

    conv_id = await save_to_conversation(
        db=db, user=user, conversation_id=conversation_id,
        question=question, answer=result["content"],
        results=[], search_ids=[], thinking=result.get("thinking"),
    )

    return ChatResponse(answer=result["content"], conversation_id=conv_id, sources=[])


async def get_allowed_collection_ids(db: AsyncSession, user: User) -> list[int]:
    """Get all collection IDs the user has read access to."""
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
    """Save user question and assistant answer to conversation history."""
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
