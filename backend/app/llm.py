"""
LLM Service - Everything related to the language model.

This module handles:
  1. LLM generation (non-streaming and streaming)
  2. Prompt building (RAG prompts and document delivery prompts)
  3. Query enrichment (rephrasing queries with domain terminology)
  4. Diagnostic logging (colored output for Docker logs)

How it works:
  - llama-server runs locally and exposes an OpenAI-compatible API
  - We send HTTP requests to /v1/chat/completions (same format as OpenAI)
  - The LLM generates text based on a system prompt + user prompt

Key concepts:
  - Thinking mode: The LLM shows its reasoning process before the final answer.
    Uses different sampling parameters (higher temperature for more creative reasoning).
  - Streaming: Tokens arrive one at a time via Server-Sent Events (SSE).
  - Query enrichment: Before searching, the LLM rephrases the query using
    domain-specific terminology loaded from the database.
"""

import json
import logging
import os
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models import Collection, SystemSetting

logger = logging.getLogger(__name__)


# =============================================================================
# Diagnostic logging (colored output for Docker logs)
# =============================================================================

_diag_logger = logging.getLogger("atlas.llm_diagnostic")

# ANSI colors for terminal output via Docker logs
CYAN = "\033[96m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
RED = "\033[91m"
DIM = "\033[2m"
RESET = "\033[0m"
BOLD = "\033[1m"


def log_llm_call(
    label: str,
    *,
    system_prompt: str | None = None,
    user_prompt: str | None = None,
    enable_thinking: bool | None = None,
    output: str | None = None,
    thinking: str | None = None,
    error: str | None = None,
    is_stream_start: bool = False,
) -> None:
    """
    Log an LLM call with colored output.

    The `label` determines the header and color:
      - Labels containing "ENRICHMENT" use cyan
      - Everything else uses yellow
    """
    color = CYAN if "ENRICHMENT" in label else YELLOW

    ts = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
    parts = [f"{color}{BOLD}{'=' * 80}\n[{ts}] {label}\n{'=' * 80}{RESET}"]

    if system_prompt is not None:
        parts.append(f"{color}{BOLD}SYSTEM PROMPT:{RESET}")
        parts.append(f"{color}{system_prompt}{RESET}")
    if user_prompt is not None:
        parts.append(f"{color}{BOLD}USER PROMPT:{RESET}")
        parts.append(f"{color}{user_prompt}{RESET}")
    if enable_thinking is not None:
        parts.append(f"{color}{DIM}enable_thinking={enable_thinking}{RESET}")

    if is_stream_start:
        parts.append(f"{color}{DIM}(streaming started...){RESET}")
    elif error:
        parts.append(f"{RED}{BOLD}ERROR:{RESET} {RED}{error}{RESET}")
    else:
        if thinking:
            parts.append(f"{color}{BOLD}THINKING:{RESET}")
            parts.append(f"{DIM}{thinking}{RESET}")
        if output is not None:
            parts.append(f"{GREEN}{BOLD}OUTPUT:{RESET}")
            parts.append(f"{GREEN}{output}{RESET}")

    parts.append(f"{color}{DIM}{'─' * 80}{RESET}")

    _diag_logger.info("\n".join(parts))


def setup_diagnostic_logging(log_path: str = "/app/logs/llm_diagnostic.log") -> None:
    """Set up the diagnostic logger to write to a dedicated file only.

    The sidecar container (llm-diagnostic) tails this file. We intentionally
    do NOT add a stderr handler here so that the same diagnostic output does
    not appear in both ``docker compose logs backend`` and
    ``docker compose logs llm-diagnostic``.
    """
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    diag = logging.getLogger("atlas.llm_diagnostic")
    diag.setLevel(logging.DEBUG)
    diag.propagate = False

    fh = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(message)s"))
    diag.addHandler(fh)


# =============================================================================
# Sampling parameters
# =============================================================================

def _sampling_params(enable_thinking: bool) -> dict:
    """
    Return sampling parameters based on thinking mode.

    Thinking mode uses higher temperature (more creative/exploratory reasoning).
    Non-thinking mode uses lower temperature (more focused/deterministic answers).
    """
    if enable_thinking:
        return {
            "temperature": settings.llm_thinking_temperature,
            "top_p": settings.llm_thinking_top_p,
            "top_k": settings.llm_thinking_top_k,
            "min_p": settings.llm_thinking_min_p,
            "presence_penalty": settings.llm_thinking_presence_penalty,
            "repeat_penalty": settings.llm_thinking_repetition_penalty,
        }
    else:
        return {
            "temperature": settings.llm_temperature,
            "top_p": settings.llm_top_p,
            "top_k": settings.llm_top_k,
            "min_p": settings.llm_min_p,
            "presence_penalty": settings.llm_presence_penalty,
            "repeat_penalty": settings.llm_repetition_penalty,
        }


def _build_request_body(
    system_prompt: str,
    user_prompt: str,
    enable_thinking: bool,
    stream: bool,
    max_tokens: int | None = None,
    temperature_override: float | None = None,
) -> dict:
    """
    Build the JSON request body for the /v1/chat/completions endpoint.
    This is shared between generate(), generate_stream(), and generate_enrichment().
    """
    sampling = _sampling_params(enable_thinking)
    if temperature_override is not None:
        sampling["temperature"] = temperature_override

    return {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        **sampling,
        "chat_template_kwargs": {"enable_thinking": enable_thinking},
        "max_tokens": max_tokens or settings.llm_max_tokens,
        "stream": stream,
    }


# =============================================================================
# LLM generation functions
# =============================================================================

async def generate(
    prompt: str,
    system_prompt: str | None = None,
    enable_thinking: bool = False,
) -> dict:
    """
    Generate a complete response (non-streaming).

    Returns:
        Dict with 'content' (the answer) and 'thinking' (reasoning, may be empty)
    """
    system = system_prompt or settings.llm_system_prompt
    body = _build_request_body(system, prompt, enable_thinking, stream=False)

    logger.info(f"generate: enable_thinking={enable_thinking}")

    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            response = await client.post(
                f"{settings.llm_base_url}/v1/chat/completions",
                json=body,
            )
            response.raise_for_status()
            data = response.json()
            choice = data["choices"][0]["message"]
            result = {
                "content": choice.get("content", ""),
                "thinking": choice.get("reasoning_content", ""),
            }

            log_llm_call(
                "FINAL RAG LLM",
                system_prompt=system, user_prompt=prompt,
                enable_thinking=enable_thinking,
                output=result["content"], thinking=result["thinking"] or None,
            )
            return result
    except Exception as e:
        log_llm_call(
            "FINAL RAG LLM",
            system_prompt=system, user_prompt=prompt,
            enable_thinking=enable_thinking, error=str(e),
        )
        raise


async def generate_stream(
    prompt: str,
    system_prompt: str | None = None,
    enable_thinking: bool = False,
) -> AsyncGenerator[dict, None]:
    """
    Generate a response as a stream of tokens.

    Yields dicts with:
      - {"type": "thinking", "text": "..."} for reasoning tokens
      - {"type": "content", "text": "..."} for answer tokens
    """
    system = system_prompt or settings.llm_system_prompt
    body = _build_request_body(system, prompt, enable_thinking, stream=True)

    logger.info(f"generate_stream: enable_thinking={enable_thinking}")
    log_llm_call(
        "FINAL RAG LLM",
        system_prompt=system, user_prompt=prompt,
        enable_thinking=enable_thinking, is_stream_start=True,
    )

    timeout = httpx.Timeout(connect=30.0, read=600.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            f"{settings.llm_base_url}/v1/chat/completions",
            json=body,
        ) as response:
            response.raise_for_status()

            # The LLM server sends lines like: "data: {json...}" or "data: [DONE]"
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                    delta = chunk["choices"][0].get("delta", {})
                    if delta.get("reasoning_content"):
                        yield {"type": "thinking", "text": delta["reasoning_content"]}
                    if delta.get("content"):
                        yield {"type": "content", "text": delta["content"]}
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue


async def generate_enrichment(prompt: str, enable_thinking: bool = False) -> str:
    """
    Generate an enriched query using the enrichment system prompt.
    Uses temperature=0 for deterministic output (we want consistent rephrasing).
    """
    system = settings.llm_enrichment_system_prompt or settings.llm_system_prompt
    body = _build_request_body(
        system, prompt, enable_thinking, stream=False,
        max_tokens=4096,
        temperature_override=None if enable_thinking else 0.0,
    )

    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout) as client:
            response = await client.post(
                f"{settings.llm_base_url}/v1/chat/completions",
                json=body,
            )
            response.raise_for_status()
            data = response.json()
            result = data["choices"][0]["message"].get("content", "").strip()

            log_llm_call("ENRICHMENT LLM", system_prompt=system, user_prompt=prompt, output=result)
            return result
    except Exception as e:
        log_llm_call("ENRICHMENT LLM", system_prompt=system, user_prompt=prompt, output="", error=str(e))
        raise


# =============================================================================
# Query enrichment
# =============================================================================

async def enrich_query(
    db: AsyncSession,
    query: str,
    collection_ids: list[int],
    enable_thinking: bool = False,
) -> str:
    """
    Enrich a search query with context information.

    Problem: Users ask questions using everyday language, but documents use
    specific technical terms. This function asks the LLM to rephrase the query
    using domain-specific terminology from global + per-collection context.

    If no context is available, returns the original query unchanged.
    """
    # 1. Load global context
    parts = []
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
    col_context_lines = [
        f"- {col.name}: {col.context_text}"
        for col in result.fetchall()
        if col.context_text
    ]
    if col_context_lines:
        parts.append("Collection context:\n" + "\n".join(col_context_lines))

    context = "\n\n".join(parts)

    if not context:
        logger.info("No context available - enriched_query = original_query")
        return query

    # 3. Ask the LLM to rephrase using domain terminology
    prompt = settings.enrichment_prompt_template.format(
        context=context,
        query=query,
    )

    try:
        enriched_query = await generate_enrichment(prompt, enable_thinking=enable_thinking)
        if enriched_query:
            logger.info(f"Query enriched: '{query}' -> '{enriched_query}'")
            return enriched_query
        else:
            logger.warning("LLM returned empty response for query enrichment")
            return query
    except Exception as e:
        logger.warning(f"Query enrichment failed, using original query: {e}")
        return query


# =============================================================================
# Prompt builders
# =============================================================================

def _format_contexts(contexts: list[dict], include_document_id: bool = False) -> str:
    """
    Format retrieval results as a text block for the LLM prompt.

    Each context becomes:
      [Source 1: document_name.pdf, page 5]
      The actual chunk content here...
    """
    parts = []
    for i, ctx in enumerate(contexts, 1):
        source_info = f"[Source {i}: {ctx['document_name']}"
        if ctx.get("page_number"):
            source_info += f", page {ctx['page_number']}"
        if include_document_id:
            source_info += f", document_id={ctx.get('document_id', 'unknown')}"
        source_info += "]"
        parts.append(f"{source_info}\n{ctx['content']}")
    return "\n\n---\n\n".join(parts)


def build_rag_prompt(
    original_question: str,
    enriched_question: str,
    contexts: list[dict],
) -> str:
    """Build the RAG prompt from original question, enriched question and contexts."""
    context_text = _format_contexts(contexts)

    if enriched_question != original_question:
        question_block = (
            f"ORIGINAL QUESTION (user terminology): {original_question}\n"
            f"ENRICHED QUESTION (search terms): {enriched_question}"
        )
        instruction = (
            "Based on the following document excerpts, answer the question.\n"
            "The ENRICHED QUESTION contains resolved technical terms - use them to "
            "find the relevant information in the documents.\n"
            "Formulate your answer using the terminology from the ORIGINAL QUESTION.\n"
            "Cite the sources in your answer with [Source X].\n"
            "If the information is insufficient, say so honestly."
        )
    else:
        question_block = f"QUESTION: {original_question}"
        instruction = (
            "Based on the following document excerpts, answer the question.\n"
            "Cite the sources in your answer with [Source X].\n"
            "If the information is insufficient, say so honestly."
        )

    return f"""{instruction}

DOCUMENTS:
{context_text}

{question_block}

ANSWER:"""


def build_document_delivery_prompt(
    original_question: str,
    enriched_question: str,
    contexts: list[dict],
) -> str:
    """Build a prompt for the document delivery agent ("gib mir" requests)."""
    context_text = _format_contexts(contexts, include_document_id=True)

    if enriched_question != original_question:
        question_block = (
            f"ORIGINAL REQUEST: {original_question}\n"
            f"ENRICHED QUERY: {enriched_question}"
        )
    else:
        question_block = f"REQUEST: {original_question}"

    return f"""The user wants you to find and deliver a specific document.
Based on the retrieved document excerpts below, determine which SINGLE document is the most relevant match.

You MUST respond with EXACTLY this format - a brief explanation followed by a tool call block:

1. A short sentence explaining why this document matches (in the user's language).
2. Then on a new line, the tool call:

<<<DELIVER_DOCUMENT>>>
{{"document_name": "exact_filename.pdf", "document_id": 123, "reason": "Brief reason"}}
<<<END_DELIVER_DOCUMENT>>>

IMPORTANT:
- Use the EXACT document_name and document_id from the sources.
- Pick only ONE document - the single best match.
- If multiple chunks come from the same document, that's a strong signal it's the right one.
- If you cannot find a relevant document, respond normally without the tool call block.

DOCUMENTS:
{context_text}

{question_block}

ANSWER:"""
