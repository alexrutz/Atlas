"""
RAG Pipeline - Orchestriert den gesamten Frage-Antwort-Prozess.

Dies ist die zentrale Komponente, die alle Services zusammenführt:
1. Berechtigungsprüfung
2. Query-Anreicherung (Kontext → erweiterte Suchanfrage)
3. Retrieval (Hybrid-Suche mit angereicherter Query)
4. LLM-Prompt-Erstellung
5. Antwort-Generierung
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
from app.schemas.chat import ChatResponse, SourceChunk, ChatMode

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
        mode: ChatMode = ChatMode.rag,
    ) -> ChatResponse:
        """
        Verarbeitet eine Benutzerfrage durch die RAG-Pipeline.

        Args:
            question: Die Frage des Benutzers
            user: Der authentifizierte Benutzer
            conversation_id: Optionale Konversations-ID für Chatverlauf
            collection_ids: Optionale Collection-IDs (überschreibt Benutzerauswahl)

        Returns:
            ChatResponse mit Antwort und Quellen
        """
        if mode == ChatMode.chat:
            answer = await self.llm.generate(question, system_prompt=settings.llm.answer_system_prompt)
            conv_id = await self._save_to_conversation(
                user=user,
                conversation_id=conversation_id,
                question=question,
                answer=answer,
                results=[],
                search_ids=[],
            )
            return ChatResponse(answer=answer, conversation_id=conv_id, sources=[])

        # 1. Erlaubte Collections ermitteln
        allowed_ids = await self._get_allowed_collection_ids(user)
        if not allowed_ids:
            return ChatResponse(
                answer="Sie haben keinen Zugriff auf Collections. Bitte wenden Sie sich an einen Administrator.",
                conversation_id=conversation_id or 0,
                sources=[],
            )

        # Ausgewählte Collections filtern (nur erlaubte)
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

        # 2. Query-Anreicherung - Suchanfrage mit Kontext erweitern
        enriched_query = await self.query_enrichment.enrich_query(
            query=question, collection_ids=search_ids,
        )

        # 3. Retrieval - relevante Chunks suchen (mit angereicherter Query)
        logger.info(f"Suche in Collections: {search_ids}")
        results = await self.retrieval.search(query=enriched_query, collection_ids=search_ids)

        # Fallback: Bei leeren Ergebnissen mit Original-Query erneut suchen
        if not results and enriched_query != question:
            logger.info("Angereicherte Query lieferte keine Ergebnisse, Fallback auf Original-Query")
            results = await self.retrieval.search(query=question, collection_ids=search_ids)

        if not results:
            logger.warning(f"Keine Ergebnisse für Query '{question}' in Collections {search_ids}")
            return ChatResponse(
                answer="Zu Ihrer Frage wurden keine relevanten Informationen in den ausgewählten Dokumenten gefunden.",
                conversation_id=conversation_id or 0,
                sources=[],
            )

        # 4. LLM-Prompt bauen (mit Original-Frage, nicht angereicherter Query)
        contexts = [
            {
                "content": r.content,
                "document_name": r.document_name,
                "page_number": r.page_number,
            }
            for r in results
        ]
        prompt = self.llm.build_rag_prompt(question, contexts)

        # 5. Antwort generieren
        answer = await self.llm.generate(prompt, system_prompt=settings.llm.answer_system_prompt)

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
            user=user,
            conversation_id=conversation_id,
            question=question,
            answer=answer,
            results=results,
            search_ids=search_ids,
            enriched_query=enriched_query,
            rag_chunks=rag_chunks,
        )

        # 7. Response zusammenbauen
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

        return ChatResponse(answer=answer, conversation_id=conv_id, sources=sources)

    async def _get_allowed_collection_ids(self, user: User) -> list[int]:
        """Ermittelt alle Collection-IDs, auf die der Benutzer Zugriff hat."""
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
        """Ermittelt die vom Benutzer ausgewählten Collections (gefiltert auf erlaubte)."""
        result = await self.db.execute(
            select(UserSelectedCollection.collection_id)
            .where(UserSelectedCollection.user_id == user.id)
        )
        selected = [row[0] for row in result.fetchall()]

        if selected:
            return [cid for cid in selected if cid in allowed_ids]
        return allowed_ids  # Fallback: alle erlaubten Collections

    async def _save_to_conversation(
        self, user: User, conversation_id: int | None,
        question: str, answer: str, results, search_ids: list[int],
        enriched_query: str | None = None,
        rag_chunks: list[dict] | None = None,
    ) -> int:
        """Speichert Frage und Antwort in der Konversation."""
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

        # Frage speichern
        user_msg = Message(
            conversation_id=conv.id, role="user", content=question,
            used_collections=search_ids,
            metadata_={"enriched_query": enriched_query} if enriched_query else {},
        )
        self.db.add(user_msg)

        # Antwort speichern
        assistant_metadata = {}
        if rag_chunks:
            assistant_metadata["rag_chunks"] = rag_chunks
        assistant_msg = Message(
            conversation_id=conv.id, role="assistant", content=answer,
            source_chunks=[r.chunk_id for r in results],
            metadata_=assistant_metadata,
        )
        self.db.add(assistant_msg)
        await self.db.flush()

        return conv.id
