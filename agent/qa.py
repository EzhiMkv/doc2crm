"""Сценарий «Спроси по документам»: вопрос -> поиск -> ответ строго по цитатам.

Используется и CLI (scripts/ask_docs.py), и Telegram-ботом (текстовые сообщения).
"""

from __future__ import annotations

from typing import Any

import asyncpg

from providers.embeddings import Embedder
from rag.documents import search_chunks

ANSWER_PROMPT = """Ответь на вопрос пользователя, используя ТОЛЬКО цитаты ниже.
Если нужны вычисления (суммы) — посчитай по цифрам из цитат.
Если в цитатах нет ответа — так и скажи. В конце ответа перечисли номера
использованных цитат в квадратных скобках.

Цитаты:
{quotes}

Вопрос: {question}"""


async def answer_question(
    pool: asyncpg.Pool,
    embedder: Embedder,
    llm: Any,
    question: str,
    *,
    k: int = 8,
) -> tuple[str, list[dict[str, Any]]]:
    """Возвращает (ответ, цитаты-источники). llm — объект с .chat()."""
    hits = await search_chunks(pool, embedder, question, k=k)
    if not hits:
        return ("В хранилище документов пока нет ничего по этому запросу.", [])
    quotes = "\n\n".join(
        f"[{i}] (счёт №{h['doc_number'] or '—'} от {h['doc_date'] or '—'}, "
        f"{h['seller_name'] or '—'}): {h['content']}"
        for i, h in enumerate(hits, 1)
    )
    answer = await llm.chat(
        [{"role": "user", "content": ANSWER_PROMPT.format(quotes=quotes, question=question)}]
    )
    return answer, hits
