"""
Embedding Service - Berechnet Embedding-Vektoren über Ollama.

Verwendet den in config.yaml konfigurierten Embedding-Provider und das Modell.
Unterstützt Batch-Verarbeitung für effizientes Embedding vieler Chunks.
"""

import logging

import httpx
import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Berechnet Embedding-Vektoren für Texte."""

    def __init__(self):
        self.config = settings.embedding
        self.base_url = self.config.base_url

    async def embed_text(self, text: str) -> list[float]:
        """
        Berechnet den Embedding-Vektor für einen einzelnen Text.

        Args:
            text: Der zu embeddende Text (idealerweise bereits kontextangereichert)

        Returns:
            Liste von Floats (Embedding-Vektor)
        """
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            for attempt in range(self.config.max_retries):
                try:
                    response = await client.post(
                        f"{self.base_url}/api/embeddings",
                        json={"model": self.config.model, "prompt": text},
                    )
                    response.raise_for_status()
                    data = response.json()
                    return data["embedding"]
                except Exception as e:
                    logger.warning(f"Embedding-Versuch {attempt + 1} fehlgeschlagen: {e}")
                    if attempt == self.config.max_retries - 1:
                        raise

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Berechnet Embedding-Vektoren für mehrere Texte in Batches.

        Args:
            texts: Liste der zu embeddenden Texte

        Returns:
            Liste von Embedding-Vektoren
        """
        embeddings = []
        batch_size = self.config.batch_size

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            logger.info(f"Embedding Batch {i // batch_size + 1}/{(len(texts) + batch_size - 1) // batch_size}")
            batch_embeddings = []
            for text in batch:
                emb = await self.embed_text(text)
                batch_embeddings.append(emb)
            embeddings.extend(batch_embeddings)

        return embeddings

    async def embed_query(self, query: str) -> list[float]:
        """
        Berechnet den Embedding-Vektor für eine Suchanfrage.
        Kann ggf. andere Prefix-Strategien verwenden als für Dokumente.

        Args:
            query: Die Suchanfrage des Benutzers

        Returns:
            Embedding-Vektor
        """
        # Manche Embedding-Modelle verwenden Prefixes für Query vs. Document
        # z.B. nomic-embed-text verwendet "search_query:" und "search_document:"
        prefixed_query = f"search_query: {query}"
        return await self.embed_text(prefixed_query)
