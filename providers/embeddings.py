"""Эмбеддинги: локальные (fastembed/ONNX, по умолчанию) и GigaChat.

Локальные — осознанный дефолт: тексты документов не покидают машину
(152-ФЗ), стоимость ноль, зависимость — 200 МБ ONNX-модели.
GigaChat-эмбеддинги остаются опцией (embeddings API платный на PERS-гранте,
проверено 14.09) — переключается одной переменной EMBED_PROVIDER.
"""

from __future__ import annotations

import os
from typing import Protocol

EMBED_MODEL_ENV = "EMBED_MODEL"
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class Embedder(Protocol):
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class LocalEmbedder:
    """fastembed (ONNX, CPU): предсказуемая латентность, без внешних вызовов."""

    def __init__(self, model_name: str | None = None) -> None:
        from fastembed import TextEmbedding  # тяжёлый импорт — лениво

        self._model = TextEmbedding(
            model_name or os.environ.get(EMBED_MODEL_ENV, DEFAULT_MODEL)
        )
        probe = list(self._model.embed(["probe"]))
        self.dim = len(probe[0])

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # CPU-инференс быстрый (мс на документ), отдельный поток не нужен
        return [v.tolist() for v in self._model.embed(texts)]


class _GigaEmbedAdapter:
    def __init__(self, giga: GigaChatLLM) -> None:
        self._giga = giga
        self.dim = 0  # узнаём при первом вызове

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vecs = await self._giga.embed(texts)
        self.dim = len(vecs[0])
        return vecs


def get_embedder() -> Embedder:
    """Фабрика по EMBED_PROVIDER: local (дефолт) | gigachat."""
    provider = os.environ.get("EMBED_PROVIDER", "local")
    if provider == "gigachat":
        from providers.gigachat import GigaChatLLM

        return _GigaEmbedAdapter(GigaChatLLM(os.environ["GIGACHAT_AUTH_KEY"]))
    return LocalEmbedder()
