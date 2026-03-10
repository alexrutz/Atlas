"""
LLM Service - Kommunikation mit dem lokalen LLM (Ollama).

Unterstützt Streaming und Nicht-Streaming Antworten.
"""

import json
import logging
from collections.abc import AsyncGenerator

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    """Kommunikation mit dem lokalen LLM über die Ollama API."""

    def __init__(self):
        self.config = settings.llm
        self.base_url = self.config.base_url

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        """
        Generiert eine vollständige Antwort (nicht-streaming).

        Args:
            prompt: Der Benutzer-Prompt mit Kontext
            system_prompt: Optionaler System-Prompt (Standard aus config)

        Returns:
            Die generierte Antwort als String
        """
        system = system_prompt or self.config.system_prompt

        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.config.model,
                    "system": system,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": self.config.temperature,
                        "top_p": self.config.top_p,
                        "top_k": self.config.top_k,
                        "num_predict": self.config.max_tokens,
                        "repeat_penalty": self.config.repeat_penalty,
                    },
                },
            )
            response.raise_for_status()
            return response.json()["response"]

    async def generate_stream(self, prompt: str, system_prompt: str | None = None) -> AsyncGenerator[str, None]:
        """
        Generiert eine Antwort als Stream (für Server-Sent Events).

        Args:
            prompt: Der Benutzer-Prompt mit Kontext
            system_prompt: Optionaler System-Prompt

        Yields:
            Teile der Antwort als Strings
        """
        system = system_prompt or self.config.system_prompt

        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/generate",
                json={
                    "model": self.config.model,
                    "system": system,
                    "prompt": prompt,
                    "stream": True,
                    "options": {
                        "temperature": self.config.temperature,
                        "top_p": self.config.top_p,
                        "top_k": self.config.top_k,
                        "num_predict": self.config.max_tokens,
                        "repeat_penalty": self.config.repeat_penalty,
                    },
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        data = json.loads(line)
                        if not data.get("done", False):
                            yield data.get("response", "")

    def build_rag_prompt(self, question: str, contexts: list[dict]) -> str:
        """
        Baut den RAG-Prompt aus Frage und Kontexten zusammen.

        Args:
            question: Die Benutzerfrage
            contexts: Liste von Dicts mit 'content', 'document_name', 'page_number'

        Returns:
            Der zusammengebaute Prompt
        """
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
