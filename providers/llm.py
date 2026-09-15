"""Тонкий асинхронный LLM-клиент поверх OpenAI-совместимого протокола.

Провайдер выбирается конфигом, код не меняется:
  DeepSeek    -> LLM_BASE_URL=https://api.deepseek.com/v1
  GigaChat    -> OpenAI-совместимый эндпоинт Гиги
  self-hosted -> vLLM (http://localhost:8000/v1), 152-ФЗ закрыт
  OpenCode Zen-> https://opencode.ai/zen/v1 (разработка)

Никаких абстракций ради абстракций: один метод chat + chat_json.
"""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.base_url = (
            base_url or os.environ.get("LLM_BASE_URL") or "https://api.deepseek.com/v1"
        ).rstrip("/")
        self.model = model or os.environ.get("LLM_MODEL", "")
        if not (self.api_key and self.model):
            raise RuntimeError("LLM_API_KEY / LLM_MODEL не заданы (проверь .env)")
        self._http = httpx.AsyncClient(timeout=120.0)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def chat(
        self, messages: list[dict[str, Any]], *, temperature: float = 0.0
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        delay = 1.0
        last_err = ""
        for _ in range(4):
            resp = await self._http.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            if resp.status_code in (429, 500, 502, 503, 529):
                last_err = f"HTTP {resp.status_code}"
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
                continue
            data = resp.json()
            if "error" in data:
                raise LLMError(f"{data['error']}")
            return data["choices"][0]["message"]["content"]
        raise LLMError(f"LLM не ответил после ретраев ({last_err})")

    async def chat_json(self, messages: list[dict[str, Any]], schema: type[BaseModel]) -> BaseModel:
        """chat + устойчивый разбор JSON (модели любят ```json-заборы)."""
        raw = await self.chat(messages)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise LLMError(f"в ответе нет JSON: {raw[:200]}")
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise LLMError(f"JSON не распарсился: {exc}: {raw[:200]}") from exc
        return schema.model_validate(obj)

    @staticmethod
    def user_content_with_image(text: str, image_path: str | Path) -> dict[str, Any]:
        """User-сообщение с картинкой (data URL, стандарт OpenAI vision)."""
        path = Path(image_path)
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        b64 = base64.b64encode(path.read_bytes()).decode()
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                },
            ],
        }
