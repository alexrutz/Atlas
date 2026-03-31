"""
Embedding Service - Computes embedding vectors via llama-server.

Uses the OpenAI-compatible /v1/embeddings endpoint.

Functions:
    embed_text(text)       - Embed a single text string
    embed_batch(texts)     - Embed a list of texts in batches
    embed_query(query)     - Alias for embed_text (for search queries)
"""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


async def embed_text(text: str) -> list[float]:
    """Compute the embedding vector for a single text."""
    async with httpx.AsyncClient(timeout=settings.embedding_timeout) as client:
        for attempt in range(settings.embedding_max_retries):
            try:
                response = await client.post(
                    f"{settings.embedding_base_url}/v1/embeddings",
                    json={
                        "input": text,
                        "model": settings.embedding_model,
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data["data"][0]["embedding"]
            except Exception as e:
                logger.warning(f"Embedding attempt {attempt + 1} failed: {e}")
                if attempt == settings.embedding_max_retries - 1:
                    raise


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Compute embedding vectors for multiple texts in batches."""
    embeddings = []
    batch_size = settings.embedding_batch_size

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        logger.info(f"Embedding batch {i // batch_size + 1}/{(len(texts) + batch_size - 1) // batch_size}")

        async with httpx.AsyncClient(timeout=settings.embedding_timeout) as client:
            for attempt in range(settings.embedding_max_retries):
                try:
                    response = await client.post(
                        f"{settings.embedding_base_url}/v1/embeddings",
                        json={
                            "input": batch,
                            "model": settings.embedding_model,
                        },
                    )
                    response.raise_for_status()
                    data = response.json()
                    batch_embeddings = [item["embedding"] for item in data["data"]]
                    embeddings.extend(batch_embeddings)
                    break
                except Exception as e:
                    logger.warning(f"Batch embedding attempt {attempt + 1} failed: {e}")
                    if attempt == settings.embedding_max_retries - 1:
                        # Fallback: embed individually
                        for text in batch:
                            emb = await embed_text(text)
                            embeddings.append(emb)

    return embeddings


async def embed_query(query: str) -> list[float]:
    """Compute the embedding vector for a search query."""
    return await embed_text(query)
