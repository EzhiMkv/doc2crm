"""Асинхронный клиент входящего вебхука Битрикс24.

Ограничения облака, которые клиент учитывает:
- интенсивность ~2 запроса/сек на портал (механизм leaky bucket);
- batch до 50 команд в одном вызове;
- ответ ``QUERY_LIMIT_EXCEEDED`` при всплесках -> экспоненциальный backoff.

Всё, что специфично для Битрикса, заперто в этом пакете: агент и RAG-слой
о REST-деталях не знают (см. ARCHITECTURE.md, «проекция вместо реплики»).
"""

from b24client.client import Bitrix24Client, Bitrix24Error, Bitrix24ScopeError
from b24client.inn import inn_is_valid, random_valid_inn

__all__ = [
    "Bitrix24Client",
    "Bitrix24Error",
    "Bitrix24ScopeError",
    "inn_is_valid",
    "random_valid_inn",
]
