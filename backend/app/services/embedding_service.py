"""
Embedding Service - Converts text into numerical vectors for similarity search.

What is an embedding?
  An embedding is a list of numbers (e.g. 1024 floats) that represents the
  "meaning" of a text. Texts with similar meaning have similar numbers.
  This is how the RAG system finds relevant document chunks for a query.

How it works:
  1. We send text to llama-embed (a separate server running an embedding model)
  2. llama-embed returns a vector (list of floats) for each text
  3. These vectors are stored in PostgreSQL (pgvector) alongside the chunks
  4. When searching, the query is also embedded and compared using cosine similarity

The llama-embed server exposes an OpenAI-compatible /v1/embeddings endpoint.

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
    """
    Compute the embedding vector for a single text.
    Returns a list of floats (e.g. 1024 numbers).
    Retries on failure up to embedding_max_retries times.
    """
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
    """
    Compute embedding vectors for multiple texts in batches.

    Splits the texts into batches of embedding_batch_size and sends each
    batch to the embedding server. If a batch fails after all retries,
    falls back to embedding each text individually.
    """
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
                        # Fallback: embed one text at a time (slower but more reliable)
                        for text in batch:
                            emb = await embed_text(text)
                            embeddings.append(emb)

    return embeddings


async def embed_query(query: str) -> list[float]:
    """Compute the embedding vector for a search query. Same as embed_text."""
    return await embed_text(query)
