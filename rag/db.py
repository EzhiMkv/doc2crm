"""Пул соединений к Postgres. DATABASE_URL из окружения (см. .env.example)."""

from __future__ import annotations

import os

import asyncpg


async def create_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(
        os.environ.get(
            "DATABASE_URL", "postgres://doc2crm:doc2crm@localhost:5432/doc2crm"
        ),
        min_size=1,
        max_size=5,
    )
