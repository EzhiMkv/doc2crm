"""Поиск по проекции: гибрид вектора и полнотекста, слияние через RRF.

Reciprocal Rank Fusion устойчив к разным шкалам скоростей вектора и
ts_rank: берём ранги, а не числа. Отсутствие FTS-совпадений не валит
запрос — вектор вытягивает семантику («помпа для колодца» -> «насос»).
"""

from __future__ import annotations

from typing import Any

import asyncpg

RRF_K = 60  # стандартная константа RRF


async def hybrid_items(
    pool: asyncpg.Pool,
    embedder,
    query: str,
    *,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Гибридный поиск по каталогу. Возвращает title/price/score."""
    (qvec,) = await embedder.embed([query])
    vec_literal = "[" + ",".join(f"{x:.6f}" for x in qvec) + "]"
    rows = await pool.fetch(
        """
        WITH v AS (
            SELECT product_id, row_number() OVER (ORDER BY embedding <=> $1::vector) AS r
            FROM catalog_items WHERE active AND embedding IS NOT NULL
        ),
        f AS (
            SELECT product_id,
                   row_number() OVER (ORDER BY ts_rank(tsv, q) DESC) AS r
            FROM catalog_items,
                 websearch_to_tsquery('russian', $2) q
            WHERE active AND tsv @@ q
        )
        SELECT c.product_id, c.title, c.price,
               coalesce(1.0 / ($3 + v.r), 0) + coalesce(1.0 / ($3 + f.r), 0) AS score
        FROM catalog_items c
        LEFT JOIN v USING (product_id)
        LEFT JOIN f USING (product_id)
        WHERE v.r IS NOT NULL OR f.r IS NOT NULL
        ORDER BY score DESC
        LIMIT $4
        """,
        vec_literal,
        query,
        RRF_K,
        k,
    )
    return [dict(r) for r in rows]
