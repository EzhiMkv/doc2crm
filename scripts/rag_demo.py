"""Индексация каталога + демо гибридного поиска. Запуск: make rag-demo."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

from b24client import Bitrix24Client
from providers.embeddings import get_embedder
from rag.catalog import sync_catalog
from rag.db import create_pool
from rag.search import hybrid_items

DEMO_QUERIES = [
    "нужен насос для скважины 30 метров",
    "чем откачать грязную воду из подвала",
    "стабилизировать давление воды в доме",
]


async def main() -> None:
    embedder = get_embedder()
    pool = await create_pool()
    async with Bitrix24Client() as b24:
        n = await sync_catalog(b24, embedder, pool)
        print(f"Проиндексировано товаров: {n}")
    for query in DEMO_QUERIES:
        results = await hybrid_items(pool, embedder, query, k=3)
        print(f"\n«{query}»:")
        for r in results:
            print(f"  {r['score']:.4f}  {r['title'][:60]}  {r['price']} RUB")
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
