"""Индексация проекции каталога Битрикса в pgvector.

Тянет товары через b24client (batch, троттлинг), строит embed_text
(название + описание — атрибуты в тексте, цена только фильтром),
векторизует локально, upsert-ит в Postgres. Повторный запуск —
обновление существующих и добавление новых.
"""

from __future__ import annotations

import asyncpg

from b24client import Bitrix24Client
from providers.embeddings import Embedder


async def sync_catalog(b24: Bitrix24Client, embedder: Embedder, pool: asyncpg.Pool) -> int:
    rows = await b24.list_all(
        "crm.product.list",
        select=["ID", "NAME", "DESCRIPTION", "PRICE", "ACTIVE"],
    )
    if not rows:
        return 0
    texts = [
        f"{r.get('NAME', '')}. {r.get('DESCRIPTION') or ''}".strip() for r in rows
    ]
    vectors = await embedder.embed(texts)
    data = [
        (
            str(r["ID"]),
            r.get("NAME", ""),
            text,
            r.get("PRICE"),
            r.get("ACTIVE", "Y") == "Y",
            "[" + ",".join(f"{x:.6f}" for x in vec) + "]",
        )
        for r, text, vec in zip(rows, texts, vectors)
    ]
    await pool.executemany(
        """
        INSERT INTO catalog_items (product_id, title, embed_text, price, active, embedding)
        VALUES ($1, $2, $3, $4, $5, $6::vector)
        ON CONFLICT (product_id) DO UPDATE SET
            title = EXCLUDED.title,
            embed_text = EXCLUDED.embed_text,
            price = EXCLUDED.price,
            active = EXCLUDED.active,
            embedding = EXCLUDED.embedding,
            updated_at = now()
        """,
        data,
    )
    return len(data)
