"""
Search Service - Embedding and retrieval for RAG.

This module handles:
  1. Text embedding (converting text to numerical vectors via llama-embed)
  2. Vector search (finding similar chunks in PostgreSQL via pgvector)
  3. Reranking (Qwen3-Reranker-4B via llama-server, with keyword fallback)

How the retrieval pipeline works:
  1. The question is converted to an embedding vector (list of numbers)
  2. pgvector finds chunks with similar embedding vectors (cosine similarity)
  3. Low-similarity results are filtered out (below threshold)
  4. A reranker scores (query, chunk) pairs for more accurate ordering

Reranking is provided by Qwen/Qwen3-Reranker-4B served via llama.cpp's
--reranking mode (HTTP endpoint /v1/rerank). The endpoint sees both the
query and each chunk together, so its scores are more accurate than the
vector similarity used for the initial recall step.
"""

import logging
import re
from collections import Counter
from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.config import settings

logger = logging.getLogger(__name__)


# =============================================================================
# Embedding (text -> vector)
# =============================================================================

async def embed_text(text_input: str) -> list[float]:
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
                        "input": text_input,
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
                        for single_text in batch:
                            emb = await embed_text(single_text)
                            embeddings.append(emb)

    return embeddings


# =============================================================================
# Data types
# =============================================================================

@dataclass
class RetrievalResult:
    """A single search result with its metadata and relevance score."""
    chunk_id: int
    document_id: int
    document_name: str
    collection_name: str
    content: str
    section_header: str | None
    page_number: int | None
    similarity_score: float


# =============================================================================
# Main retrieval pipeline
# =============================================================================

async def search_chunks(
    db: AsyncSession,
    query: str,
    collection_ids: list[int],
    top_k: int | None = None,
) -> list[RetrievalResult]:
    """
    Full retrieval pipeline: embed -> vector search -> filter -> rerank.

    Steps:
      1. Convert the query text into an embedding vector
      2. Find the top_k most similar chunks via pgvector
      3. Remove results below the similarity threshold
      4. Rerank remaining results with a cross-encoder (if enabled)
    """
    top_k = top_k or settings.retrieval_top_k

    if not collection_ids:
        return []

    # Step 1: Convert query to embedding vector
    logger.info(f"Retrieval: query='{query[:100]}', collections={collection_ids}, top_k={top_k}")
    query_embedding = await embed_text(query)

    # Step 2: Vector similarity search
    results = await vector_search(db, query_embedding, collection_ids, top_k)

    # Step 3: Filter out results below the similarity threshold
    threshold = settings.retrieval_similarity_threshold
    if threshold > 0 and results:
        before = len(results)
        results = [r for r in results if r.similarity_score >= threshold]
        if len(results) < before:
            logger.info(f"Threshold filter ({threshold}): {before} -> {len(results)} results")

    if results:
        scores = [r.similarity_score for r in results]
        logger.info(
            f"Retrieval: {len(results)} results, "
            f"scores: max={max(scores):.3f}, min={min(scores):.3f}, avg={sum(scores)/len(scores):.3f}"
        )
    else:
        logger.warning(f"Retrieval: 0 results for query='{query[:100]}'")

    # Step 4: Rerank for better accuracy (only if we have more results than rerank_top_k)
    if settings.retrieval_rerank and len(results) > settings.retrieval_rerank_top_k:
        results = await rerank(query, results)
        results = results[:settings.retrieval_rerank_top_k]

    return results


# =============================================================================
# Vector search (pgvector)
# =============================================================================

async def vector_search(
    db: AsyncSession,
    query_embedding: list[float],
    collection_ids: list[int],
    top_k: int,
) -> list[RetrievalResult]:
    """
    Find chunks with similar embeddings using pgvector.

    The <=> operator computes cosine distance (0 = identical, 2 = opposite).
    We convert to similarity with: similarity = 1 - distance.
    """
    # Convert the embedding list to a PostgreSQL vector string like "[0.1,0.2,...]"
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

    sql = text(f"""
        SELECT c.id, c.document_id, c.content, c.section_header, c.page_number,
               d.original_name as document_name, col.name as collection_name,
               1 - (ce.embedding <=> '{embedding_str}'::vector) as similarity
        FROM chunk_embeddings ce
        JOIN chunks c ON ce.chunk_id = c.id
        JOIN documents d ON c.document_id = d.id
        JOIN collections col ON d.collection_id = col.id
        WHERE d.collection_id = ANY(:collection_ids)
          AND d.processing_status = 'completed'
          AND ce.model_name = :model_name
        ORDER BY ce.embedding <=> '{embedding_str}'::vector
        LIMIT :top_k
    """)

    result = await db.execute(sql, {
        "collection_ids": collection_ids,
        "model_name": settings.embedding_model,
        "top_k": top_k,
    })

    return [
        RetrievalResult(
            chunk_id=row.id, document_id=row.document_id,
            document_name=row.document_name, collection_name=row.collection_name,
            content=row.content, section_header=row.section_header,
            page_number=row.page_number, similarity_score=float(row.similarity),
        )
        for row in result.fetchall()
    ]


# =============================================================================
# Reranking (Qwen3-Reranker via llama-server, keyword fallback)
# =============================================================================

async def rerank(query: str, results: list[RetrievalResult]) -> list[RetrievalResult]:
    """
    Rerank results for better accuracy.

    Calls Qwen3-Reranker-4B via llama.cpp's /v1/rerank endpoint. If the
    reranker server is unreachable, falls back to keyword-based reranking.
    """
    if not results:
        return results

    try:
        return await _rerank_with_llama_server(query, results)
    except Exception as exc:
        logger.warning(f"Reranker server unavailable ({exc}), using keyword fallback")
        return _rerank_with_keywords(query, results)


async def _rerank_with_llama_server(query: str, results: list[RetrievalResult]) -> list[RetrievalResult]:
    """
    Rerank using llama-server's /v1/rerank endpoint (Qwen3-Reranker-4B).

    Body: {"model": "rerank", "query": str, "documents": [str, ...]}
    Response: {"results": [{"index": int, "relevance_score": float}, ...]}
    """
    documents = [r.content for r in results]
    url = f"{settings.retrieval_rerank_base_url}/v1/rerank"

    async with httpx.AsyncClient(timeout=settings.retrieval_rerank_timeout) as client:
        response = await client.post(
            url,
            json={
                "model": settings.retrieval_rerank_model,
                "query": query,
                "documents": documents,
            },
        )
        response.raise_for_status()
        data = response.json()

    items = data.get("results", [])
    reranked: list[RetrievalResult] = []
    for item in items:
        idx = item["index"]
        score = float(item.get("relevance_score", item.get("score", 0.0)))
        r = results[idx]
        r.similarity_score = score
        reranked.append(r)

    reranked.sort(key=lambda r: r.similarity_score, reverse=True)
    return reranked


def _rerank_with_keywords(query: str, results: list[RetrievalResult]) -> list[RetrievalResult]:
    """
    Fallback reranker: blend vector similarity with keyword overlap.

    For each result, computes a combined score:
      combined = 0.7 * vector_similarity + 0.3 * keyword_overlap
    """
    query_words = _tokenize(query)

    scored_results = []
    for r in results:
        chunk_words = _tokenize(r.content)
        keyword_score = _keyword_overlap(query_words, chunk_words)
        combined = 0.7 * r.similarity_score + 0.3 * keyword_score
        scored_results.append((combined, r))

    scored_results.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored_results]


# Splits text into words (removes punctuation, keeps only words with 2+ chars)
_WORD_SPLIT = re.compile(r"[^\w]+", re.UNICODE)


def _tokenize(text_str: str) -> list[str]:
    """Split text into lowercase words."""
    return [word for word in _WORD_SPLIT.split(text_str.lower()) if len(word) > 1]


def _keyword_overlap(query_words: list[str], chunk_words: list[str]) -> float:
    """
    Compute keyword overlap between query and chunk (0.0 to 1.0).

    Blends two simple measures:
      - Jaccard: what fraction of unique words appear in both texts
      - Term frequency: how often query words appear in the chunk
    """
    if not query_words or not chunk_words:
        return 0.0

    query_set = set(query_words)
    chunk_set = set(chunk_words)
    shared = query_set & chunk_set

    if not shared:
        return 0.0

    jaccard = len(shared) / len(query_set | chunk_set)

    chunk_counts = Counter(chunk_words)
    tf_hits = sum(min(chunk_counts[w], 3) for w in query_words if w in chunk_counts)
    tf_score = tf_hits / (len(query_words) * 3)

    return 0.5 * jaccard + 0.5 * tf_score
