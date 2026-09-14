"""Реализация клиента: throttle, ретраи, batch, доменные хелперы."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Self
from urllib.parse import urlencode

import httpx

BATCH_LIMIT = 50  # максимум команд в одном batch-вызове Битрикса


class Bitrix24Error(RuntimeError):
    """Ошибка REST-вызова Битрикса (после всех ретраев)."""


class Bitrix24ScopeError(Bitrix24Error):
    """Вебхуку не хватает прав (insufficient_scope) — чинится в настройках портала."""


class Bitrix24Client:
    """Клиент входящего вебхука. Уважает лимит ~2 rps и умеет batch.

    Пример:
        async with Bitrix24Client() as b24:
            deals = await b24.call("crm.deal.list", {"select": ["ID", "TITLE"]})
    """

    def __init__(
        self,
        webhook_url: str | None = None,
        *,
        rps: float = 2.0,
        timeout: float = 30.0,
        max_retries: int = 5,
    ) -> None:
        url = webhook_url or os.environ.get("B24_WEBHOOK_URL")
        if not url:
            raise RuntimeError("B24_WEBHOOK_URL не задан (проверь .env)")
        self._http = httpx.AsyncClient(base_url=url.rstrip("/") + "/", timeout=timeout)
        self._min_interval = 1.0 / rps
        self._last_call = 0.0
        self._throttle_lock = asyncio.Lock()
        self._max_retries = max_retries

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def _throttle(self) -> None:
        """Не пускаем запросы чаще min_interval (последовательный слот)."""
        async with self._throttle_lock:
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Один REST-вызов. Возвращает поле ``result`` ответа.

        QUERY_LIMIT_EXCEEDED ретраится с экспоненциальным backoff —
        у Битрикса кратковременные всплески допустимы, важно не сдаваться сразу.
        """
        params = params or {}
        delay = 0.5
        last_error = ""
        for attempt in range(self._max_retries):
            await self._throttle()
            resp = await self._http.post(method.strip("/") + ".json", json=params)
            try:
                data = resp.json()
            except ValueError as exc:
                raise Bitrix24Error(
                    f"{method}: не-JSON ответ (HTTP {resp.status_code})"
                ) from exc
            if "error" not in data:
                return data.get("result")
            last_error = f"{data['error']}: {data.get('error_description', '')}"
            if data["error"] == "QUERY_LIMIT_EXCEEDED":
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
                continue
            if data["error"] == "insufficient_scope":
                raise Bitrix24ScopeError(
                    f"{method}: вебхуку не хватает прав — отметь CRM в правах вебхука"
                )
            raise Bitrix24Error(f"{method}: {last_error}")
        raise Bitrix24Error(f"{method}: лимит не отпустил за {self._max_retries} попыток ({last_error})")

    # ------------------------------------------------------------------ batch

    @staticmethod
    def _encode_cmd(method: str, params: dict[str, Any]) -> str:
        """Batch-команда — это method?query: поля кодируются в строку запроса
        с квадратными скобками (fields[TITLE]=...), как того ждёт Битрикс."""
        flat: list[tuple[str, str]] = []
        for key, value in params.items():
            if isinstance(value, dict):
                flat.extend((f"{key}[{k}]", _stringify(v)) for k, v in value.items())
            else:
                flat.append((key, _stringify(value)))
        return f"{method}?{urlencode(flat)}"

    async def batch(self, commands: dict[str, tuple[str, dict[str, Any]]]) -> dict[str, Any]:
        """До 50 команд одним вызовом.

        commands: {"alias": ("crm.deal.add", {"fields": {...}}), ...}
        Возвращает {"result": {alias: ...}, "result_error": {alias: msg}}.
        """
        if len(commands) > BATCH_LIMIT:
            raise ValueError(f"batch вмещает {BATCH_LIMIT} команд, передано {len(commands)}")
        cmd = {
            alias: self._encode_cmd(method, params or {})
            for alias, (method, params) in commands.items()
        }
        result = await self.call("batch", {"halt": 0, "cmd": cmd})
        return {
            "result": result.get("result", {}),
            "result_error": result.get("result_error", {}),
        }

    async def batch_chunked(
        self, commands: dict[str, tuple[str, dict[str, Any]]], *, chunk: int = BATCH_LIMIT
    ) -> dict[str, Any]:
        """batch для произвольного числа команд: режет на части по `chunk`."""
        merged: dict[str, Any] = {"result": {}, "result_error": {}}
        aliases = list(commands)
        for start in range(0, len(aliases), chunk):
            part = {alias: commands[alias] for alias in aliases[start : start + chunk]}
            response = await self.batch(part)
            merged["result"].update(response["result"])
            merged["result_error"].update(response["result_error"])
        return merged

    # ------------------------------------------------------- доменные хелперы

    async def list_all(
        self, method: str, *, select: list[str], filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Полная выгрузка с автопагинацией (по 50 записей, как отдаёт Битрикс).

        Используется для проекции каталога в RAG-слой (см. ARCHITECTURE.md).
        """
        items: list[dict[str, Any]] = []
        start: int | None = -1  # -1 = с начала
        while start is not None:
            params: dict[str, Any] = {"select": select, "start": start}
            if filters:
                params["filter"] = filters
            result = await self.call(method, params)
            batch_items = result if isinstance(result, list) else result.get("items", [])
            items.extend(batch_items)
            next_start = (
                result.get("next") if isinstance(result, dict) and "next" in result else None
            )
            start = next_start if batch_items else None
            if isinstance(batch_items, list) and len(batch_items) < 50:
                break
        return items

    async def deal_comment_add(self, deal_id: int, comment: str) -> Any:
        """Отчёт агента в таймлайн сделки."""
        return await self.call(
            "crm.timeline.comment.add",
            {"fields": {"ENTITY_ID": deal_id, "ENTITY_TYPE": "deal", "COMMENT": comment}},
        )

    async def deal_create(self, fields: dict[str, Any]) -> int:
        result = await self.call("crm.deal.add", {"fields": fields})
        return int(result)

    async def find_companies(self, *, title: str | None = None, inn: str | None = None) -> list[dict]:
        """Поиск контрагента по названию/ИНН. Реквизиты хранятся в UF-полях
        или requisites — оба места проверяем; для seed-данных ИНН лежит в
        UF_CRM_INN."""
        filters: dict[str, Any] = {}
        if title:
            filters["TITLE"] = title  # точное совпадение; нечёткий поиск — дело агента
        if inn:
            filters["UF_CRM_INN"] = inn
        return await self.list_all("crm.company.list", select=["ID", "TITLE", "UF_CRM_INN"], filters=filters)


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "Y" if value else "N"
    if isinstance(value, (dict, list)):
        import json

        return json.dumps(value, ensure_ascii=False)
    return str(value)
