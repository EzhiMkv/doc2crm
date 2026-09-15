"""RAG по документам: ингест распознанных счетов и поиск по чанкам.

Текстовое представление счёта строится из извлечённых полей: заголовок
(реквизиты + итог) и по чанку на позицию. Каждый чанк несёт ссылку на
документ — цитаты источников в ответе приходят отсюда.
"""

from __future__ import annotations

import uuid
from typing import Any

import asyncpg

from agent.schemas import Invoice
from providers.embeddings import Embedder


def _chunks_of(doc_id: str, inv: Invoice) -> list[str]:
    header = (
        f"Счёт №{inv.document_number or '—'} от {inv.document_date or '—'}. "
        f"Поставщик: {inv.seller_name or '—'}, ИНН {inv.seller_inn or '—'}. "
        f"Позиций: {len(inv.items)}. Итого: {inv.total or '—'} {inv.currency}."
    )
    items = [
        f"Позиция счёта №{inv.document_number or '—'} ({inv.seller_name}): "
        f"{item.name} — кол-во {item.qty}, цена {item.price}, "
        f"сумма {item.total} {inv.currency}."
        for item in inv.items
    ]
    return [header] + items


async def ingest_invoice(
    pool: asyncpg.Pool,
    embedder: Embedder,
    inv: Invoice,
    *,
    source: str = "telegram",
    file_path: str | None = None,
) -> str:
    """Счёт -> documents + doc_chunks (с векторами). Возвращает doc_id."""
    doc_id = str(uuid.uuid4())
    doc_date = inv.document_date
    if isinstance(doc_date, str):  # asyncpg ждёт date, не ISO-строку
        from datetime import date as _date

        doc_date = _date.fromisoformat(doc_date)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO documents (doc_id, source, seller_name, seller_inn,
                                   doc_number, doc_date, total, file_path)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            doc_id, source, inv.seller_name, inv.seller_inn,
            inv.document_number, doc_date, inv.total, file_path,
        )
        chunks = _chunks_of(doc_id, inv)
        vectors = await embedder.embed(chunks)
        await conn.executemany(
            """
            INSERT INTO doc_chunks (chunk_id, doc_id, content, embedding)
            VALUES ($1, $2, $3, $4::vector)
            """,
            [
                (str(uuid.uuid4()), doc_id, content,
                 "[" + ",".join(f"{x:.6f}" for x in vec) + "]")
                for content, vec in zip(chunks, vectors)
            ],
        )
    return doc_id


async def search_chunks(
    pool: asyncpg.Pool,
    embedder: Embedder,
    query: str,
    *,
    k: int = 6,
) -> list[dict[str, Any]]:
    """Гибридный поиск по чанкам документов (вектор + FTS через RRF).

    Каждый результат — цитата с реквизитами документа-источника.
    """
    (qvec,) = await embedder.embed([query])
    vec_literal = "[" + ",".join(f"{x:.6f}" for x in qvec) + "]"
    rows = await pool.fetch(
        """
        WITH v AS (
            SELECT chunk_id, row_number() OVER (ORDER BY embedding <=> $1::vector) AS r
            FROM doc_chunks WHERE embedding IS NOT NULL
        ),
        f AS (
            SELECT chunk_id, row_number() OVER (ORDER BY ts_rank(tsv, q) DESC) AS r
            FROM doc_chunks, websearch_to_tsquery('russian', $2) q
            WHERE tsv @@ q
        )
        SELECT c.chunk_id, c.content, d.doc_id, d.seller_name, d.seller_inn,
               d.doc_number, d.doc_date, d.total,
               coalesce(1.0 / ($3 + v.r), 0) + coalesce(1.0 / ($3 + f.r), 0) AS score
        FROM doc_chunks c
        JOIN documents d USING (doc_id)
        LEFT JOIN v USING (chunk_id)
        LEFT JOIN f USING (chunk_id)
        WHERE v.r IS NOT NULL OR f.r IS NOT NULL
        ORDER BY score DESC
        LIMIT $4
        """,
        vec_literal, query, 60, k,
    )
    return [dict(r) for r in rows]
