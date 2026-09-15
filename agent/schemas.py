"""Pydantic-схемы документов и валидация «против галлюцинаций».

Узел validate графа использует методы ``issues()``: расхождение суммы
позиций с итогом и ИНН с битой контрольной суммой — верные признаки того,
что модель что-то выдумала или не разобрала скан.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from b24client.inn import inn_is_valid


class InvoiceItem(BaseModel):
    name: str
    qty: float = 1
    price: float
    total: float


class Invoice(BaseModel):
    """Счёт на оплату — извлечённые поля с уверенностью модели."""

    seller_name: str | None = None
    seller_inn: str | None = None
    document_number: str | None = None
    document_date: str | None = None  # ISO YYYY-MM-DD
    items: list[InvoiceItem] = Field(default_factory=list)
    total: float | None = None
    currency: str = "RUB"
    confidence: dict[str, float] = Field(default_factory=dict)

    @field_validator("seller_inn")
    @classmethod
    def _clean_inn(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.replace(" ", "").replace("\u00a0", "")

    @field_validator("confidence", mode="before")
    @classmethod
    def _numeric_confidence(cls, v):
        """Модели любят писать в confidence строки («высокая») — мусор в мусор."""
        if not isinstance(v, dict):
            return {}
        clean = {}
        for key, value in v.items():
            try:
                clean[key] = float(value)
            except (TypeError, ValueError):
                continue
        return clean

    def issues(self) -> list[str]:
        """Список проблем, найденных кросс-валидацией полей."""
        problems: list[str] = []
        if self.seller_inn and not inn_is_valid(self.seller_inn):
            problems.append(
                f"ИНН {self.seller_inn}: не проходит контрольную сумму — "
                f"вероятна галлюцинация или ошибка распознавания"
            )
        if self.total is not None and self.items:
            items_sum = round(sum(i.total for i in self.items), 2)
            if abs(items_sum - self.total) > 0.01:
                problems.append(
                    f"итог {self.total} != сумма позиций {items_sum}"
                )
        low_conf = [
            f"{k} ({v:.0%})" for k, v in self.confidence.items() if v < 0.7
        ]
        if low_conf:
            problems.append("низкая уверенность модели: " + ", ".join(low_conf))
        return problems

    def needs_human_review(self) -> bool:
        """Порог для human-in-the-loop: споры о деньгах дороже автопилота."""
        return bool(self.issues())
