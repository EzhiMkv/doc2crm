"""Узел extract: документ (фото/PDF-страница) -> Invoice.

Промпт вынесен в константу — он часть «контракта» с моделью: нулевая
температура, строгий JSON, уверенность по каждому полю, «не знаешь — null».
"""

from __future__ import annotations

from pathlib import Path

from agent.schemas import Invoice
from providers.llm import LLM

EXTRACTION_PROMPT = """Извлеки реквизиты счёта на оплату из изображения.
Верни СТРОГО JSON без пояснений по схеме:
{
  "seller_name": "название организации-поставщика или null",
  "seller_inn": "ИНН (только цифры) или null",
  "document_number": "номер счёта или null",
  "document_date": "дата счёта в формате YYYY-MM-DD или null",
  "items": [{"name": "...", "qty": число, "price": число, "total": число}],
  "total": "итоговая сумма числом или null",
  "currency": "код валюты (RUB если не указано)",
  "confidence": {"поле": 0.0-1.0, ...}  — уверенность по каждому полю
}
Правила: не выдумывай то, что не видно на изображении (null вместо догадки);
суммы — числа без пробелов и символа валюты; если позиций нет — пустой список."""


async def extract_invoice(llm: LLM, image_path: str | Path) -> Invoice:
    """Фото/PDF-страница счёта -> валидированный Invoice."""
    message = LLM.user_content_with_image(EXTRACTION_PROMPT, image_path)
    return await llm.chat_json(
        [{"role": "system", "content": "Ты точный извлекатель реквизитов из документов."},
         message],
        Invoice,
    )
