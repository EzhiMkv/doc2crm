"""Провайдер GigaChat (Сбер): OAuth-токены, chat, embeddings.

Особенности, из-за которых нельзя просто взять OpenAI-SDK:
- OAuth: Basic-ключ -> access_token на ngw.devices.sberbank.ru (живёт 30 мин);
- российский TLS: сертификат НУЦ Минцифры отсутствует в системных сторах,
  поэтому verify=False + комментарий (в проде — бандл НУЦ-сертификата);
- файлы/видео-модальности на PERS-гранте недоступны (проверено 14.09),
  поэтому GigaChat в проекте используется для embeddings (EmbeddingsGigaR)
  и текстовых задач; vision-извлечение идёт через другой провайдер.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from typing import Any

import httpx
from pydantic import BaseModel

from agent.schemas import Invoice

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
API_BASE = "https://gigachat.devices.sberbank.ru/api/v1"


class GigaChatLLM:
    """Duck-typed к providers.llm.LLM по chat/chat_json + embed()."""

    def __init__(
        self,
        auth_key: str,
        *,
        scope: str = "GIGACHAT_API_PERS",
        model: str = "GigaChat-2-Max",
        embed_model: str = "EmbeddingsGigaR",
    ) -> None:
        self.auth_key = auth_key
        self.scope = scope
        self.model = model
        self.embed_model = embed_model
        self._token: str | None = None
        self._token_exp = 0.0
        self._lock = asyncio.Lock()
        # в проде: подменить на бандл сертификата НУЦ Минцифры
        self._http = httpx.AsyncClient(timeout=120.0, verify=False)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get_token(self) -> str:
        async with self._lock:
            if self._token and time.time() < self._token_exp - 60:
                return self._token
            resp = await self._http.post(
                OAUTH_URL,
                headers={
                    "Authorization": f"Basic {self.auth_key}",
                    "RqUID": str(uuid.uuid4()),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                content=f"scope={self.scope}",
            )
            resp.raise_for_status()
            data = resp.json()
            self._token = data["access_token"]
            self._token_exp = data.get("expires_at", 0) / 1000
            return self._token

    async def chat(
        self, messages: list[dict[str, Any]], *, temperature: float = 0.0
    ) -> str:
        token = await self._get_token()
        resp = await self._http.post(
            f"{API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={"model": self.model, "messages": messages, "temperature": temperature},
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def chat_json(
        self, messages: list[dict[str, Any]], schema: type[BaseModel]
    ) -> BaseModel:
        raw = await self.chat(messages)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError(f"в ответе нет JSON: {raw[:200]}")
        return schema.model_validate(json.loads(match.group(0)))

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Векторы EmbeddingsGigaR для RAG-проекции (pgvector)."""
        token = await self._get_token()
        resp = await self._http.post(
            f"{API_BASE}/embeddings",
            headers={"Authorization": f"Bearer {token}"},
            json={"model": self.embed_model, "input": texts},
        )
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        return [item["embedding"] for item in data]


async def extract_invoice_text(llm: GigaChatLLM, invoice_text: str) -> Invoice:
    """Текстовое извлечение (PDF-счёт после парсера текста, без vision)."""
    prompt = (
        "Извлеки из текста счёта реквизиты и верни СТРОГО JSON: "
        "seller_name, seller_inn, document_number, document_date (YYYY-MM-DD), "
        "total (число), currency. Не выдумывай: нет данных — null.\n\nТекст:\n"
        + invoice_text[:6000]
    )
    return await llm.chat_json([{"role": "user", "content": prompt}], Invoice)
