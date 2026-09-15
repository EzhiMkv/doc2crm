"""Поиск по проекции: гибрид вектора и полнотекста, слияние через RRF.

Reciprocal Rank Fusion устойчив к разным шкалам скоростей вектора и
ts_rank: берём ранги, а не числа. Отсутствие FTS-совпадений не валит
запрос — вектор вытягивает семантику («помпа для колодца» -> «насос»).
"""

from __future__ import annotations

import re
from typing import Any

import asyncpg

RRF_K = 60  # стандартная константа RRF


async def hybrid_items(
    pool: asyncpg.Pool,
    embedder,
    query: str,
    *,
    k: int = 5,
    max_price: float | None = None,
) -> list[dict[str, Any]]:
    """Гибридный поиск по каталогу. max_price — фильтр «до N рублей»:
    строгий числовой фильтр по цене из каталога, а не семантика."""
    (qvec,) = await embedder.embed([query])
    vec_literal = "[" + ",".join(f"{x:.6f}" for x in qvec) + "]"
    rows = await pool.fetch(
        """
        WITH v AS (
            SELECT product_id, row_number() OVER (ORDER BY embedding <=> $1::vector) AS r
            FROM catalog_items
            WHERE active AND embedding IS NOT NULL
              AND ($4::numeric IS NULL OR price <= $4::numeric)
        ),
        f AS (
            SELECT product_id,
                   row_number() OVER (ORDER BY ts_rank(tsv, q) DESC) AS r
            FROM catalog_items,
                 websearch_to_tsquery('russian', $2) q
            WHERE active AND tsv @@ q
              AND ($4::numeric IS NULL OR price <= $4::numeric)
        )
        SELECT c.product_id, c.title, c.price,
               coalesce(1.0 / ($3 + v.r), 0) + coalesce(1.0 / ($3 + f.r), 0) AS score
        FROM catalog_items c
        LEFT JOIN v USING (product_id)
        LEFT JOIN f USING (product_id)
        WHERE v.r IS NOT NULL OR f.r IS NOT NULL
        ORDER BY score DESC
        LIMIT $5
        """,
        vec_literal,
        query,
        RRF_K,
        max_price,
        k,
    )
    return [dict(r) for r in rows]


_BUDGET_RE = re.compile(r"до\s+(\d+(?:[.,]\d+)?)\s*(к\b|тыс\w*|k\b)?", re.IGNORECASE)


def parse_budget(query: str) -> float | None:
    """«...до 30к» / «до 30 тыс» / «до 30000» -> 30000.0. Без бюджета — None.

    NL -> фильтры осознанно регэкспом, а не LLM: детерминированность
    и ноль стоимости там, где шаблон покрывает 90% формулировок.
    """
    match = _BUDGET_RE.search(query)
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    if match.group(2) or value < 1000:  # «к»/«тыс» — тысячи
        value *= 1000
    return value
