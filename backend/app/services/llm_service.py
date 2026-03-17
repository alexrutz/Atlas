"""
LLM Service - Kommunikation mit llama.cpp über die OpenAI-kompatible API.

Unterstützt Streaming, Thinking-Modus und verschiedene System-Prompts.
"""

import json
import logging
from collections.abc import AsyncGenerator

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    """Kommunikation mit llama.cpp über die OpenAI-kompatible API."""

    def __init__(self):
        self.config = settings.llm
        self.base_url = self.config.base_url

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        enable_thinking: bool = False,
    ) -> dict:
        """
        Generiert eine vollständige Antwort (nicht-streaming).

        Returns:
            Dict mit 'content' und optional 'thinking'
        """
        system = system_prompt or self.config.system_prompt
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

        body: dict = {
            "messages": messages,
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "max_tokens": self.config.max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
        }

        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json=body,
            )
            response.raise_for_status()
            data = response.json()
            choice = data["choices"][0]["message"]
            return {
                "content": choice.get("content", ""),
                "thinking": choice.get("reasoning_content", ""),
            }

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        enable_thinking: bool = False,
    ) -> AsyncGenerator[dict, None]:
        """
        Generiert eine Antwort als Stream.

        Yields:
            Dicts mit 'type' ('thinking' oder 'content') und 'text'
        """
        system = system_prompt or self.config.system_prompt
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

        body: dict = {
            "messages": messages,
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "max_tokens": self.config.max_tokens,
            "stream": True,
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
        }

        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
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

    async def generate_enrichment(self, prompt: str) -> str:
        """Generate enriched query using the enrichment system prompt."""
        system = self.config.enrichment_system_prompt or self.config.system_prompt
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

        body: dict = {
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": 256,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }

        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json=body,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"].get("content", "").strip()

    def build_rag_prompt(self, question: str, contexts: list[dict]) -> str:
        """Baut den RAG-Prompt aus Frage und Kontexten zusammen."""
        context_parts = []
        for i, ctx in enumerate(contexts, 1):
            source_info = f"[Quelle {i}: {ctx['document_name']}"
            if ctx.get("page_number"):
                source_info += f", Seite {ctx['page_number']}"
            source_info += "]"
            context_parts.append(f"{source_info}\n{ctx['content']}")

        context_text = "\n\n---\n\n".join(context_parts)

        return f"""Basierend auf den folgenden Dokumentenausschnitten, beantworte die Frage.
Zitiere die Quellen in deiner Antwort mit [Quelle X].
Wenn die Informationen nicht ausreichen, sage das ehrlich.

DOKUMENTE:
{context_text}

FRAGE: {question}

ANTWORT:"""
