"""
LLM Service - Communication with llama-server via the OpenAI-compatible API.

Supports streaming, thinking mode (reasoning), and different system prompts.

Functions:
    generate(prompt, system_prompt, enable_thinking)       - Non-streaming response
    generate_stream(prompt, system_prompt, enable_thinking) - Streaming response
    generate_enrichment(prompt, enable_thinking)            - Enrichment call
    build_rag_prompt(original_q, enriched_q, contexts)     - Build RAG prompt
    build_document_delivery_prompt(original_q, enriched_q, contexts) - Build delivery prompt
"""

import json
import logging
from collections.abc import AsyncGenerator

import httpx

from app.core.config import settings
from app.services.llm_diagnostic import (
    log_enrichment_call,
    log_rag_call,
    log_rag_stream_complete,
)

logger = logging.getLogger(__name__)


def _sampling_params(enable_thinking: bool) -> dict:
    """Return sampling parameters based on thinking mode."""
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


async def generate(
    prompt: str,
    system_prompt: str | None = None,
    enable_thinking: bool = False,
) -> dict:
    """
    Generate a complete response (non-streaming).

    Returns:
        Dict with 'content' and optional 'thinking'
    """
    system = system_prompt or settings.llm_system_prompt
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    body: dict = {
        "model": settings.llm_model,
        "messages": messages,
        **_sampling_params(enable_thinking),
        "chat_template_kwargs": {"enable_thinking": enable_thinking},
        "max_tokens": settings.llm_max_tokens,
        "stream": False,
    }
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

            log_rag_call(
                system_prompt=system,
                user_prompt=prompt,
                enable_thinking=enable_thinking,
                output=result["content"],
                thinking=result["thinking"] or None,
            )

            return result
    except Exception as e:
        log_rag_call(
            system_prompt=system,
            user_prompt=prompt,
            enable_thinking=enable_thinking,
            error=str(e),
        )
        raise


async def generate_stream(
    prompt: str,
    system_prompt: str | None = None,
    enable_thinking: bool = False,
) -> AsyncGenerator[dict, None]:
    """
    Generate a response as a stream.

    Yields:
        Dicts with 'type' ('thinking' or 'content') and 'text'
    """
    system = system_prompt or settings.llm_system_prompt
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    body: dict = {
        "model": settings.llm_model,
        "messages": messages,
        **_sampling_params(enable_thinking),
        "chat_template_kwargs": {"enable_thinking": enable_thinking},
        "max_tokens": settings.llm_max_tokens,
        "stream": True,
    }
    logger.info(f"generate_stream: enable_thinking={enable_thinking}")

    log_rag_call(
        system_prompt=system,
        user_prompt=prompt,
        enable_thinking=enable_thinking,
        is_stream_start=True,
    )

    timeout = httpx.Timeout(connect=30.0, read=600.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            f"{settings.llm_base_url}/v1/chat/completions",
            json=body,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                    delta = chunk["choices"][0].get("delta", {})
                    # Thinking content (reasoning)
                    if delta.get("reasoning_content"):
                        yield {"type": "thinking", "text": delta["reasoning_content"]}
                    # Regular content
                    if delta.get("content"):
                        yield {"type": "content", "text": delta["content"]}
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue


async def generate_enrichment(prompt: str, enable_thinking: bool = False) -> str:
    """Generate enriched query using the enrichment system prompt."""
    system = settings.llm_enrichment_system_prompt or settings.llm_system_prompt
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    sampling = _sampling_params(enable_thinking)
    sampling["temperature"] = 0.0

    body: dict = {
        "model": settings.llm_model,
        "messages": messages,
        **sampling,
        "max_tokens": 256,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout) as client:
            response = await client.post(
                f"{settings.llm_base_url}/v1/chat/completions",
                json=body,
            )
            response.raise_for_status()
            data = response.json()
            result = data["choices"][0]["message"].get("content", "").strip()

            log_enrichment_call(
                system_prompt=system,
                user_prompt=prompt,
                output=result,
            )

            return result
    except Exception as e:
        log_enrichment_call(
            system_prompt=system,
            user_prompt=prompt,
            output="",
            error=str(e),
        )
        raise


def build_document_delivery_prompt(
    original_question: str,
    enriched_question: str,
    contexts: list[dict],
) -> str:
    """Build a prompt for the document delivery agent."""
    context_parts = []
    for i, ctx in enumerate(contexts, 1):
        source_info = f"[Source {i}: {ctx['document_name']}"
        if ctx.get("page_number"):
            source_info += f", page {ctx['page_number']}"
        source_info += f", document_id={ctx.get('document_id', 'unknown')}"
        source_info += "]"
        context_parts.append(f"{source_info}\n{ctx['content']}")

    context_text = "\n\n---\n\n".join(context_parts)

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


def build_rag_prompt(
    original_question: str,
    enriched_question: str,
    contexts: list[dict],
) -> str:
    """Build the RAG prompt from original question, enriched question and contexts."""
    context_parts = []
    for i, ctx in enumerate(contexts, 1):
        source_info = f"[Source {i}: {ctx['document_name']}"
        if ctx.get("page_number"):
            source_info += f", page {ctx['page_number']}"
        source_info += "]"
        context_parts.append(f"{source_info}\n{ctx['content']}")

    context_text = "\n\n---\n\n".join(context_parts)

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
