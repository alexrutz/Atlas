"""
Embedding Service - Berechnet Embedding-Vektoren über llama.cpp.

Verwendet die OpenAI-kompatible /v1/embeddings API von llama.cpp.
"""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Berechnet Embedding-Vektoren für Texte über llama.cpp."""

    def __init__(self):
        self.config = settings.embedding
        self.base_url = self.config.base_url

    async def embed_text(self, text: str) -> list[float]:
        """Berechnet den Embedding-Vektor für einen einzelnen Text."""
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            for attempt in range(self.config.max_retries):
                try:
                    response = await client.post(
                        f"{self.base_url}/v1/embeddings",
                        json={
                            "input": text,
                            "model": self.config.model,
                        },
                    )
                    response.raise_for_status()
                    data = response.json()
                    return data["data"][0]["embedding"]
                except Exception as e:
                    logger.warning(f"Embedding-Versuch {attempt + 1} fehlgeschlagen: {e}")
                    if attempt == self.config.max_retries - 1:
                        raise

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Berechnet Embedding-Vektoren für mehrere Texte in Batches."""
        embeddings = []
        batch_size = self.config.batch_size

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            logger.info(f"Embedding Batch {i // batch_size + 1}/{(len(texts) + batch_size - 1) // batch_size}")

            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                for attempt in range(self.config.max_retries):
                    try:
                        response = await client.post(
                            f"{self.base_url}/v1/embeddings",
                            json={
                                "input": batch,
                                "model": self.config.model,
                            },
                        )
                        response.raise_for_status()
                        data = response.json()
                        batch_embeddings = [item["embedding"] for item in data["data"]]
                        embeddings.extend(batch_embeddings)
                        break
                    except Exception as e:
                        logger.warning(f"Batch-Embedding Versuch {attempt + 1} fehlgeschlagen: {e}")
                        if attempt == self.config.max_retries - 1:
                            # Fallback: einzeln embedden
                            for text in batch:
                                emb = await self.embed_text(text)
                                embeddings.append(emb)

        return embeddings

    async def embed_query(self, query: str) -> list[float]:
        """Berechnet den Embedding-Vektor für eine Suchanfrage."""
        return await self.embed_text(query)
