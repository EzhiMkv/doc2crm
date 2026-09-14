"""Юнит-тесты чистой логики клиента (без сети)."""

from b24client import Bitrix24Client, inn_is_valid, random_valid_inn


def test_inn_checksum():
    # 7707083893 — Сбербанк, известный валидный ИНН
    assert inn_is_valid("7707083893")
    assert inn_is_valid("7830002293")  # Газпром
    assert not inn_is_valid("7707083894")  # неверная контрольная цифра
    assert not inn_is_valid("12345")  # не 10 цифр
    assert not inn_is_valid("abcdefghijkl")


def test_random_inn_always_valid():
    import random

    rng = random.Random(1)
    for _ in range(200):
        assert inn_is_valid(random_valid_inn(rng))


def test_encode_cmd_flat_params():
    cmd = Bitrix24Client._encode_cmd(
        "crm.deal.add", {"fields": {"TITLE": "Счёт №1", "OPPORTUNITY": 1500}}
    )
    assert cmd.startswith("crm.deal.add?")
    assert "fields%5BTITLE%5D=%D0%A1%D1%87%D1%91%D1%82+%E2%84%961" in cmd
    assert "fields%5BOPPORTUNITY%5D=1500" in cmd


def test_batch_limit_enforced():
    import pytest

    with pytest.raises(ValueError):
        # не делаем сетевых вызовов — валидация срабатывает до запроса
        import asyncio

        async def run():
            client = Bitrix24Client("https://example.test/rest/1/x/", rps=100)
            try:
                await client.batch({f"r{i}": ("crm.deal.add", {"fields": {}}) for i in range(51)})
            finally:
                await client.aclose()

        asyncio.run(run())
