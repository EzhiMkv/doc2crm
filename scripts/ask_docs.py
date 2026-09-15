"""Проверка сценария «Спроси по документам».

Запуск:
    python -m scripts.ingest_fixtures        # один раз: залить фикстуры в RAG
    python -m scripts.ask_docs "На какую сумму были счета от ТестПоставщик-3?"

Конвейер: гибридный поиск по чанкам -> LLM отвечает строго по цитатам ->
вывод: ответ + список источников с реквизитами.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

from providers.embeddings import get_embedder
from providers.llm import LLM
from rag.db import create_pool
from rag.documents import search_chunks

ANSWER_PROMPT = """Ответь на вопрос пользователя, используя ТОЛЬКО цитаты ниже.
Если нужны вычисления (суммы) — посчитай по цифрам из цитат.
Если в цитатах нет ответа — так и скажи. В конце ответа перечисли номера
использованных цитат в квадратных скобках.

Цитаты:
{quotes}

Вопрос: {question}"""


async def main() -> None:
    question = sys.argv[1] if len(sys.argv) > 1 else "На какую сумму были счета от ТестПоставщик-3?"
    embedder = get_embedder()
    pool = await create_pool()

    hits = await search_chunks(pool, embedder, question, k=8)
    if not hits:
        print("В хранилище документов нет ничего по этому запросу.")
        return
    quotes = "\n\n".join(
        f"[{i}] (счёт №{h['doc_number'] or '—'} от {h['doc_date'] or '—'}, "
        f"{h['seller_name'] or '—'}): {h['content']}"
        for i, h in enumerate(hits, 1)
    )
    llm = LLM()
    try:
        answer = await llm.chat(
            [{"role": "user", "content": ANSWER_PROMPT.format(quotes=quotes, question=question)}]
        )
    finally:
        await llm.aclose()

    print(f"Вопрос: {question}\n")
    print(answer)
    print("\n── источники ──")
    for i, h in enumerate(hits, 1):
        print(f"[{i}] счёт №{h['doc_number']} от {h['doc_date']} | "
              f"{h['seller_name']} | итог {h['total']} | score {h['score']:.4f}")
        print(f"    {h['content'][:120]}…")
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
