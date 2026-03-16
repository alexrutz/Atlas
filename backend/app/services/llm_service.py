"""LLM Service - Kommunikation mit dem lokalen LLM.

Unterstützt aktuell Ollama und den nativen llama.cpp Server.
"""

import json
import logging
from collections.abc import AsyncGenerator

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    """Kommunikation mit dem lokalen LLM über Ollama oder llama.cpp."""

    def __init__(self):
        self.config = settings.llm
        self.base_url = self.config.base_url
        self.last_thought_process = ""

    def _build_messages(self, prompt: str, system_prompt: str | None = None) -> list[dict[str, str]]:
        """Erstellt OpenAI-kompatible Message-Struktur für llama.cpp."""
        messages = []
        system = system_prompt or self.config.system_prompt
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _build_llama_cpp_payload(self, prompt: str, system_prompt: str | None = None, *, stream: bool = False) -> dict:
        """Erstellt den Request-Body für llama.cpp inklusive Thinking-Flag."""
        return {
            "model": self.config.model,
            "messages": self._build_messages(prompt, system_prompt),
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "max_tokens": self.config.max_tokens,
            "stream": stream,
            "chat_template_kwargs": {"enable_thinking": self.config.enable_thinking},
        }

    async def _generate_ollama(self, prompt: str, system_prompt: str | None = None) -> str:
        """Generiert Antwort über die Ollama /api/generate API."""
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

    async def _generate_llama_cpp(self, prompt: str, system_prompt: str | None = None) -> str:
        """Generiert Antwort über llama.cpp OpenAI-kompatible API."""
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json=self._build_llama_cpp_payload(prompt, system_prompt),
            )
            response.raise_for_status()
            data = response.json()
            message = data["choices"][0]["message"]
            self.last_thought_process = message.get("reasoning_content") or message.get("reasoning") or ""
            return message.get("content", "")

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        """
        Generiert eine vollständige Antwort (nicht-streaming).

        Args:
            prompt: Der Benutzer-Prompt mit Kontext
            system_prompt: Optionaler System-Prompt (Standard aus config)

        Returns:
            Die generierte Antwort als String
        """
        self.last_thought_process = ""
        if self.config.provider == "ollama":
            return await self._generate_ollama(prompt, system_prompt)
        return await self._generate_llama_cpp(prompt, system_prompt)

    async def _generate_stream_ollama(self, prompt: str, system_prompt: str | None = None) -> AsyncGenerator[str, None]:
        """Streaming-Antwort über Ollama API."""
        self.last_thought_process = ""
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

    async def _generate_stream_llama_cpp(self, prompt: str, system_prompt: str | None = None) -> AsyncGenerator[str, None]:
        """Streaming-Antwort über llama.cpp OpenAI-kompatible API."""
        self.last_thought_process = ""
        thought_parts: list[str] = []
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                json=self._build_llama_cpp_payload(prompt, system_prompt, stream=True),
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue

                    payload = line.removeprefix("data: ").strip()
                    if payload == "[DONE]":
                        break

                    data = json.loads(payload)
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
                    if reasoning:
                        thought_parts.append(reasoning)
                        self.last_thought_process = "".join(thought_parts)

                    content = delta.get("content", "")
                    if content:
                        yield content

    async def generate_stream(self, prompt: str, system_prompt: str | None = None) -> AsyncGenerator[str, None]:
        """
        Generiert eine Antwort als Stream (für Server-Sent Events).

        Args:
            prompt: Der Benutzer-Prompt mit Kontext
            system_prompt: Optionaler System-Prompt

        Yields:
            Teile der Antwort als Strings
        """
        if self.config.provider == "ollama":
            async for chunk in self._generate_stream_ollama(prompt, system_prompt):
                yield chunk
            return

        async for chunk in self._generate_stream_llama_cpp(prompt, system_prompt):
            yield chunk

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
