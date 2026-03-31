"""
Retrieval Service - Finds relevant document chunks for a user's question.

This is the "R" in RAG (Retrieval-Augmented Generation). Given a question,
it finds the most relevant pieces of text from the uploaded documents.

How the retrieval pipeline works:
  1. The question is converted to an embedding vector (list of numbers)
  2. pgvector finds chunks with similar embedding vectors (cosine similarity)
  3. Low-similarity results are filtered out (below threshold)
  4. A cross-encoder (FlashRank) reranks the results for better accuracy

What is reranking?
  Vector search is fast but approximate. The cross-encoder reads each
  chunk together with the query and gives a more accurate relevance score.
  It's slower but much better at ranking, so we use it as a second pass
  on the top results from vector search.

  If FlashRank is not available, falls back to a simple keyword overlap score.

Functions:
    search_chunks(db, query, collection_ids, top_k)  - Full pipeline
    vector_search(db, query_embedding, collection_ids, top_k) - Raw vector search
    rerank(query, results) - Rerank results for better accuracy
"""

import logging
import re
from collections import Counter
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.config import settings
from app.services.embedding_service import embed_query

logger = logging.getLogger(__name__)


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
    Full retrieval pipeline: embed → vector search → filter → rerank.

    Steps:
      1. Convert the query text into an embedding vector
      2. Find the top_k most similar chunks via pgvector
      3. Remove results below the similarity threshold
      4. Rerank remaining results with a cross-encoder (if enabled)

    Args:
        db: Database session
        query: The search query text
        collection_ids: Which collections to search (already permission-checked)
        top_k: How many results to retrieve (default from config)

    Returns:
        List of RetrievalResult, sorted by relevance (best first)
    """
    top_k = top_k or settings.retrieval_top_k

    if not collection_ids:
        return []

    # Step 1: Convert query to embedding vector
    logger.info(f"Retrieval: query='{query[:100]}', collections={collection_ids}, top_k={top_k}")
    query_embedding = await embed_query(query)

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
        results = rerank(query, results)
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
# Reranking (cross-encoder or keyword fallback)
# =============================================================================

# The cross-encoder model is loaded once and reused (it's ~34 MB).
_ranker = None


def _get_ranker():
    """Load the FlashRank cross-encoder model (only on first call)."""
    global _ranker
    if _ranker is None:
        try:
            from flashrank import Ranker
            model = settings.retrieval_rerank_model
            logger.info(f"Loading FlashRank cross-encoder: {model}")
            _ranker = Ranker(model_name=model, cache_dir="/tmp/flashrank")
            logger.info("FlashRank cross-encoder loaded successfully")
        except Exception as exc:
            logger.warning(f"FlashRank not available ({exc}), will use keyword fallback")
    return _ranker


def rerank(query: str, results: list[RetrievalResult]) -> list[RetrievalResult]:
    """
    Rerank results for better accuracy.

    Tries the FlashRank cross-encoder first. If FlashRank is not installed
    or fails to load, falls back to keyword-based reranking.
    """
    if not results:
        return results

    ranker = _get_ranker()
    if ranker is not None:
        return _rerank_with_cross_encoder(ranker, query, results)
    return _rerank_with_keywords(query, results)


def _rerank_with_cross_encoder(ranker, query: str, results: list[RetrievalResult]) -> list[RetrievalResult]:
    """
    Rerank using the FlashRank cross-encoder.

    The cross-encoder reads the query + each chunk together and gives a
    relevance score. This is more accurate than vector similarity because
    it sees both texts at the same time.
    """
    from flashrank import RerankRequest

    # FlashRank expects a list of {"id": ..., "text": ...} dicts
    passages = [{"id": idx, "text": r.content} for idx, r in enumerate(results)]
    ranked = ranker.rerank(RerankRequest(query=query, passages=passages))

    # Map the ranked results back to our RetrievalResult objects
    idx_to_result = {idx: r for idx, r in enumerate(results)}
    reranked = []
    for item in ranked:
        r = idx_to_result[item["id"]]
        r.similarity_score = float(item["score"])  # Replace with cross-encoder score
        reranked.append(r)

    return reranked


def _rerank_with_keywords(query: str, results: list[RetrievalResult]) -> list[RetrievalResult]:
    """
    Fallback reranker: blend vector similarity with keyword overlap.

    For each result, computes a combined score:
      combined = 0.7 * vector_similarity + 0.3 * keyword_overlap

    Keyword overlap measures how many words from the query appear in the chunk.
    """
    query_words = _tokenize(query)

    scored_results = []
    for r in results:
        chunk_words = _tokenize(r.content)
        keyword_score = _keyword_overlap(query_words, chunk_words)
        combined = 0.7 * r.similarity_score + 0.3 * keyword_score
        scored_results.append((combined, r))

    # Sort by combined score (highest first)
    scored_results.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored_results]


# =============================================================================
# Keyword scoring helpers
# =============================================================================

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

    # Jaccard similarity: shared / total unique words
    jaccard = len(shared) / len(query_set | chunk_set)

    # Term frequency: count how often query words appear in chunk (cap at 3 per word)
    chunk_counts = Counter(chunk_words)
    tf_hits = sum(min(chunk_counts[w], 3) for w in query_words if w in chunk_counts)
    tf_score = tf_hits / (len(query_words) * 3)

    return 0.5 * jaccard + 0.5 * tf_score
