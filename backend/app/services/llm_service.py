"""
LLM Service - Communication with llama.cpp via the OpenAI-compatible API.

Supports streaming, thinking mode, and different system prompts.
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


class LLMService:
    """Communication with llama.cpp via the OpenAI-compatible API."""

    def __init__(self):
        self.config = settings.llm
        self.base_url = self.config.base_url

    def _sampling_params(self, enable_thinking: bool) -> dict:
        """Return sampling parameters based on thinking mode."""
        s = self.config.thinking_sampling if enable_thinking else self.config.sampling
        return {
            "temperature": s.temperature,
            "top_p": s.top_p,
            "top_k": s.top_k,
            "min_p": s.min_p,
            "presence_penalty": s.presence_penalty,
            "repetition_penalty": s.repetition_penalty,
        }

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        enable_thinking: bool = False,
    ) -> dict:
        """
        Generate a complete response (non-streaming).

        Returns:
            Dict with 'content' and optional 'thinking'
        """
        system = system_prompt or self.config.system_prompt
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

        body: dict = {
            "messages": messages,
            **self._sampling_params(enable_thinking),
            "max_tokens": self.config.max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": bool(enable_thinking)},
        }
        logger.info(f"generate: enable_thinking={enable_thinking}")

        # Diagnostic: log input
        log_rag_call(
            system_prompt=system,
            user_prompt=prompt,
            enable_thinking=enable_thinking,
        )

        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=body,
                )
                response.raise_for_status()
                data = response.json()
                choice = data["choices"][0]["message"]
                result = {
                    "content": choice.get("content", ""),
                    "thinking": choice.get("reasoning_content", ""),
                }

                # Diagnostic: log output
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
        self,
        prompt: str,
        system_prompt: str | None = None,
        enable_thinking: bool = False,
    ) -> AsyncGenerator[dict, None]:
        """
        Generate a response as a stream.

        Yields:
            Dicts with 'type' ('thinking' or 'content') and 'text'
        """
        system = system_prompt or self.config.system_prompt
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

        body: dict = {
            "messages": messages,
            **self._sampling_params(enable_thinking),
            "max_tokens": self.config.max_tokens,
            "stream": True,
            "chat_template_kwargs": {"enable_thinking": bool(enable_thinking)},
        }
        logger.info(f"generate_stream: enable_thinking={enable_thinking}")

        # Diagnostic: log stream start
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
                f"{self.base_url}/v1/chat/completions",
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
                        # Thinking content
                        if delta.get("reasoning_content"):
                            yield {"type": "thinking", "text": delta["reasoning_content"]}
                        # Regular content
                        if delta.get("content"):
                            yield {"type": "content", "text": delta["content"]}
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    async def generate_enrichment(self, prompt: str, enable_thinking: bool = False) -> str:
        """Generate enriched query using the enrichment system prompt."""
        system = self.config.enrichment_system_prompt or self.config.system_prompt
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

        sampling = self._sampling_params(enable_thinking)
        # Override temperature to 0.0 for enrichment (deterministic)
        sampling["temperature"] = 0.0

        body: dict = {
            "messages": messages,
            **sampling,
            "max_tokens": 256,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": bool(enable_thinking)},
        }

        # Diagnostic: log enrichment input
        log_enrichment_call(
            system_prompt=system,
            user_prompt=prompt,
            output="(calling...)",
        )

        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=body,
                )
                response.raise_for_status()
                data = response.json()
                result = data["choices"][0]["message"].get("content", "").strip()

                # Diagnostic: log enrichment output
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

    def build_rag_prompt(
        self,
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

        # If enriched differs from original, include both so the LLM can
        # find the information via the enriched terms but answer using the
        # user's original terminology.
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
