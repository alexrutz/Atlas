"""
RAG Pipeline - Orchestriert den gesamten Frage-Antwort-Prozess.

Unterstützt:
- RAG-Modus: Retrieval + Antwortgenerierung mit Dokumentenkontext
- Free-Chat-Modus: Direkte Konversation ohne Dokumentenkontext
- Thinking-Modus: Zeigt den Denkprozess des LLMs
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.user import User
from app.models.conversation import Conversation, Message, UserSelectedCollection
from app.models.collection import GroupCollectionAccess
from app.models.group import UserGroup
from app.services.retrieval_service import RetrievalService
from app.services.llm_service import LLMService
from app.services.query_enrichment_service import QueryEnrichmentService
from app.schemas.chat import ChatResponse, SourceChunk

logger = logging.getLogger(__name__)


class RAGPipeline:
    """Orchestriert den gesamten RAG-Prozess."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.retrieval = RetrievalService(db)
        self.llm = LLMService()
        self.query_enrichment = QueryEnrichmentService(db)

    async def query(
        self,
        question: str,
        user: User,
        conversation_id: int | None = None,
        collection_ids: list[int] | None = None,
        enable_thinking: bool = False,
        enable_enrichment_thinking: bool = False,
        enable_enrichment: bool = True,
        rag_mode: bool = True,
    ) -> ChatResponse:
        """Verarbeitet eine Benutzerfrage."""
        if not rag_mode:
            return await self._free_chat(question, user, conversation_id, enable_thinking)

        # 1. Erlaubte Collections ermitteln
        allowed_ids = await self._get_allowed_collection_ids(user)
        if not allowed_ids:
            return ChatResponse(
                answer="Sie haben keinen Zugriff auf Collections.",
                conversation_id=conversation_id or 0,
                sources=[],
            )

        if collection_ids:
            search_ids = [cid for cid in collection_ids if cid in allowed_ids]
        else:
            search_ids = await self._get_selected_collection_ids(user, allowed_ids)

        if not search_ids:
            return ChatResponse(
                answer="Bitte wählen Sie mindestens eine Collection aus.",
                conversation_id=conversation_id or 0,
                sources=[],
            )

        # 2. Query-Anreicherung
        if enable_enrichment:
            enriched_query = await self.query_enrichment.enrich_query(
                query=question, collection_ids=search_ids,
                enable_thinking=enable_enrichment_thinking,
            )
        else:
            enriched_query = question

        # 3. Retrieval
        results = await self.retrieval.search(query=enriched_query, collection_ids=search_ids)

        if not results and enriched_query != question:
            results = await self.retrieval.search(query=question, collection_ids=search_ids)

        if not results:
            return ChatResponse(
                answer="Keine relevanten Informationen gefunden.",
                conversation_id=conversation_id or 0,
                sources=[],
            )

        # 4. LLM-Prompt bauen
        contexts = [
            {"content": r.content, "document_name": r.document_name, "page_number": r.page_number}
            for r in results
        ]
        prompt = self.llm.build_rag_prompt(question, enriched_query, contexts)

        # 5. Antwort generieren
        result = await self.llm.generate(prompt, enable_thinking=enable_thinking)
        answer = result["content"]

        # 6. Konversation speichern
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
        conv_id = await self._save_to_conversation(
            user=user, conversation_id=conversation_id,
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

    async def _free_chat(
        self, question: str, user: User,
        conversation_id: int | None, enable_thinking: bool,
    ) -> ChatResponse:
        """Direkte Konversation ohne RAG-Kontext."""
        system = self.llm.config.free_chat_system_prompt or self.llm.config.system_prompt
        result = await self.llm.generate(question, system_prompt=system, enable_thinking=enable_thinking)

        conv_id = await self._save_to_conversation(
            user=user, conversation_id=conversation_id,
            question=question, answer=result["content"],
            results=[], search_ids=[], thinking=result.get("thinking"),
        )

        return ChatResponse(answer=result["content"], conversation_id=conv_id, sources=[])

    async def _get_allowed_collection_ids(self, user: User) -> list[int]:
        if user.is_admin:
            from app.models.collection import Collection
            result = await self.db.execute(select(Collection.id))
            return [row[0] for row in result.fetchall()]

        result = await self.db.execute(
            select(GroupCollectionAccess.collection_id)
            .join(UserGroup, UserGroup.group_id == GroupCollectionAccess.group_id)
            .where(UserGroup.user_id == user.id, GroupCollectionAccess.can_read.is_(True))
            .distinct()
        )
        return [row[0] for row in result.fetchall()]

    async def _get_selected_collection_ids(self, user: User, allowed_ids: list[int]) -> list[int]:
        result = await self.db.execute(
            select(UserSelectedCollection.collection_id)
            .where(UserSelectedCollection.user_id == user.id)
        )
        selected = [row[0] for row in result.fetchall()]

        if selected:
            return [cid for cid in selected if cid in allowed_ids]
        return allowed_ids

    async def _save_to_conversation(
        self, user: User, conversation_id: int | None,
        question: str, answer: str, results, search_ids: list[int],
        enriched_query: str | None = None,
        rag_chunks: list[dict] | None = None,
        thinking: str | None = None,
        document_delivery: dict | None = None,
    ) -> int:
        if conversation_id:
            result = await self.db.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user.id,
                )
            )
            conv = result.scalar_one_or_none()
            if not conv:
                conv = Conversation(user_id=user.id, title=question[:100])
                self.db.add(conv)
                await self.db.flush()
        else:
            conv = Conversation(user_id=user.id, title=question[:100])
            self.db.add(conv)
            await self.db.flush()

        user_msg = Message(
            conversation_id=conv.id, role="user", content=question,
            used_collections=search_ids,
            metadata_={"enriched_query": enriched_query} if enriched_query else {},
        )
        self.db.add(user_msg)

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
        self.db.add(assistant_msg)
        await self.db.flush()

        return conv.id
