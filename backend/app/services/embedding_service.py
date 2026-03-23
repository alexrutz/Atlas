"""
Embedding Service - Computes embedding vectors via vLLM.

Uses the OpenAI-compatible /v1/embeddings API from vLLM with GPU acceleration.
"""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Computes embedding vectors for texts via vLLM."""

    def __init__(self):
        self.config = settings.embedding
        self.base_url = self.config.base_url

    async def embed_text(self, text: str) -> list[float]:
        """Compute the embedding vector for a single text."""
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
                    logger.warning(f"Embedding attempt {attempt + 1} failed: {e}")
                    if attempt == self.config.max_retries - 1:
                        raise

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Compute embedding vectors for multiple texts in batches."""
        embeddings = []
        batch_size = self.config.batch_size

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            logger.info(f"Embedding batch {i // batch_size + 1}/{(len(texts) + batch_size - 1) // batch_size}")

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
                        logger.warning(f"Batch embedding attempt {attempt + 1} failed: {e}")
                        if attempt == self.config.max_retries - 1:
                            # Fallback: embed individually
                            for text in batch:
                                emb = await self.embed_text(text)
                                embeddings.append(emb)

        return embeddings

    async def embed_query(self, query: str) -> list[float]:
        """Compute the embedding vector for a search query."""
        return await self.embed_text(query)
