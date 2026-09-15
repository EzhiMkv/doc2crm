"""Генератор тестовых изображений счетов (фикстуры для eval-сета).

Не фото с телефона, но достаточно похоже: шрифт, таблица позиций, шум.
Запуск: python -m scripts.make_fixture
"""

from __future__ import annotations

import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from b24client import random_valid_inn

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def make_invoice_image(path: Path, seed: int = 1, *, break_inn: bool = False) -> dict:
    """Рисует счёт, возвращает « ground truth» — эталонные поля для eval-а."""
    rng = random.Random(seed)
    img = Image.new("RGB", (1000, 900), "white")
    draw = ImageDraw.Draw(img)
    f_h = ImageFont.truetype(FONT_BOLD, 30)
    f_b = ImageFont.truetype(FONT_BOLD, 20)
    f = ImageFont.truetype(FONT, 20)

    inn = random_valid_inn(rng)
    if break_inn:  # битый ИНН для теста валидатора
        inn = "9" + inn[1:]
    doc_no = f"{rng.randint(1000, 9999)}"
    doc_date = datetime.now(UTC).astimezone().date() - timedelta(days=rng.randint(1, 60))

    y = 40
    draw.text((300, y), f"СЧЁТ № {doc_no} от {doc_date.isoformat()}", font=f_h, fill="black")
    y += 70
    draw.text((60, y), f"Поставщик: ООО «ТестПоставщик-{seed}»", font=f_b, fill="black")
    y += 34
    draw.text((60, y), f"ИНН {inn}", font=f, fill="black")
    y += 60

    items = []
    for i in range(rng.randint(2, 4)):
        qty = rng.choice([1, 2, 3, 5])
        price = rng.randrange(500, 50_000)
        items.append((f"Позиция {i + 1}: оборудование А-{rng.randint(10, 99)}",
                      qty, price, qty * price))

    x_cols = [60, 560, 680, 790, 930]
    draw.text((x_cols[0], y), "Наименование", font=f_b, fill="black")
    draw.text((x_cols[2], y), "Кол-во", font=f_b, fill="black")
    draw.text((x_cols[3], y), "Цена", font=f_b, fill="black")
    draw.text((x_cols[4], y), "Сумма", font=f_b, fill="black")
    y += 34
    for name, qty, price, total in items:
        draw.text((x_cols[0], y), name, font=f, fill="black")
        draw.text((x_cols[2], y), str(qty), font=f, fill="black")
        draw.text((x_cols[3], y), f"{price:.2f}", font=f, fill="black")
        draw.text((x_cols[4], y), f"{total:.2f}", font=f, fill="black")
        y += 30
    y += 20
    grand_total = sum(t for *_, t in items)
    draw.line((60, y, 940, y), fill="black", width=2)
    y += 14
    draw.text((700, y), f"ИТОГО: {grand_total:.2f} RUB", font=f_h, fill="black")

    img.save(path)
    return {
        "seller_name": f"ООО «ТестПоставщик-{seed}»",
        "seller_inn": inn,
        "document_number": doc_no,
        "document_date": doc_date.isoformat(),
        "total": float(grand_total),
        "items_count": len(items),
    }


if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "evals" / "fixtures"
    out.mkdir(parents=True, exist_ok=True)
    for s in range(1, 4):
        gt = make_invoice_image(out / f"invoice_{s}.png", seed=s)
        print(s, gt)
