"""
Query Enrichment Service - Enriches search queries with context knowledge.

Loads global context and per-collection context, then asks the LLM to
rephrase the query to include domain-specific terms.

Functions:
    enrich_query(db, query, collection_ids, enable_thinking) - Enrich a search query
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.collection import Collection
from app.models.system_setting import SystemSetting
from app.services.llm_service import generate_enrichment

logger = logging.getLogger(__name__)


async def enrich_query(
    db: AsyncSession,
    query: str,
    collection_ids: list[int],
    enable_thinking: bool = False,
) -> str:
    """
    Enrich a search query with context information.

    Loads global + per-collection context, then asks the LLM to rephrase
    the query. If no context is available, returns the original query unchanged.
    """
    context = await _load_context(db, collection_ids)

    if not context:
        logger.info("No context available - enriched_query = original_query")
        return query

    enriched = await _generate_enriched_query(query, context, enable_thinking)
    return enriched


async def _load_context(db: AsyncSession, collection_ids: list[int]) -> str:
    """Load global context and per-collection context texts."""
    parts = []

    # 1. Load global context
    result = await db.execute(
        select(SystemSetting.value).where(SystemSetting.key == "global_context")
    )
    global_context = result.scalar_one_or_none()
    if global_context:
        parts.append("Global context:\n" + global_context)

    # 2. Load per-collection context texts
    result = await db.execute(
        select(Collection.name, Collection.context_text)
        .where(Collection.id.in_(collection_ids))
    )
    collection_contexts = result.fetchall()

    col_context_lines = []
    for col in collection_contexts:
        if col.context_text:
            col_context_lines.append(f"- {col.name}: {col.context_text}")
    if col_context_lines:
        parts.append("Collection context:\n" + "\n".join(col_context_lines))

    return "\n\n".join(parts)


async def _generate_enriched_query(query: str, context: str, enable_thinking: bool = False) -> str:
    """Ask the LLM to enrich the query using the loaded context."""
    prompt = settings.enrichment_prompt_template.format(
        context=context,
        query=query,
    )

    try:
        enriched_query = await generate_enrichment(prompt, enable_thinking=enable_thinking)

        if enriched_query:
            logger.info(f"Query enriched: '{query}' → '{enriched_query}'")
            return enriched_query
        else:
            logger.warning("LLM returned empty response for query enrichment")
            return query

    except Exception as e:
        logger.warning(f"Query enrichment failed, using original query: {e}")
        return query
