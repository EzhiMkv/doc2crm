"""Разовый ингест фикстур в RAG-хранилище документов.

Запуск: python -m scripts.ingest_fixtures
В продакшене документы попадают в хранилище через узел ingest графа
(фото из Telegram), здесь — из ground truth фикстур для демо/теста.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

from agent.schemas import Invoice
from providers.embeddings import get_embedder
from rag.db import create_pool
from rag.documents import ingest_invoice

FIXTURES = Path(__file__).resolve().parents[1] / "evals" / "fixtures"


async def main() -> None:
    embedder = get_embedder()
    pool = await create_pool()
    count = 0
    for gt_file in sorted(FIXTURES.glob("invoice_*.gt.json")):
        gt = json.loads(gt_file.read_text(encoding="utf-8"))
        inv = Invoice(
            seller_name=gt["seller_name"],
            seller_inn=gt["seller_inn"],
            document_number=gt["document_number"],
            document_date=gt["document_date"],
            total=gt["total"],
            currency="RUB",
            items=[
                # позиции в gt свёрнуты в items_count — для поиска достаточно заголовка
            ],
        )
        await ingest_invoice(pool, embedder, inv, source="fixtures")
        count += 1
    n = await pool.fetchval("SELECT count(*) FROM doc_chunks")
    print(f"Документов залито: {count}, чанков в хранилище: {n}")
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
