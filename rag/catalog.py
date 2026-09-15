"""Индексация проекции каталога Битрикса в pgvector.

Тянет товары через b24client (batch, троттлинг), строит embed_text
(название + описание — атрибуты в тексте, цена только фильтром),
векторизует локально, upsert-ит в Postgres. Повторный запуск —
обновление существующих и добавление новых.
"""

from __future__ import annotations

import asyncpg

from b24client import Bitrix24Client, Bitrix24Error
from providers.embeddings import Embedder


async def _fetch_prices(b24: Bitrix24Client) -> dict[str, float]:
    """Цены из торгового каталога (catalog.price.list). В облаке цены живут
    отдельно от crm.product (поле PRICE там всегда None — проверено 15.09),
    тип цен должен существовать на портале (catalog.priceType.add)."""
    prices: dict[str, float] = {}
    start: int | None = 0
    while start is not None:
        data = await b24._call_full(
            "catalog.price.list",
            {"select": ["productId", "price"], "start": start},
        )
        for row in data.get("result", {}).get("prices", []):
            prices[str(row["productId"])] = float(row["price"])
        start = data.get("next")
    return prices


async def sync_catalog(b24: Bitrix24Client, embedder: Embedder, pool: asyncpg.Pool) -> int:
    rows = await b24.list_all(
        "crm.product.list",
        select=["ID", "NAME", "DESCRIPTION", "ACTIVE"],
    )
    if not rows:
        return 0
    try:
        prices = await _fetch_prices(b24)
    except Bitrix24Error:
        prices = {}  # нет скоупа catalog — работаем без цен
    texts = [
        f"{r.get('NAME', '')}. {r.get('DESCRIPTION') or ''}".strip() for r in rows
    ]
    vectors = await embedder.embed(texts)
    data = [
        (
            str(r["ID"]),
            r.get("NAME", ""),
            text,
            prices.get(str(r["ID"])),
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
