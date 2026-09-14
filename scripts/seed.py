"""Генератор тестовых данных для портала Битрикс24.

Заливает: компании с валидными ИНН, каталог промоборудования (будет
подопытным для RAG по каталогу) и сделки, привязанные к компаниям.

Запуск: ``make seed`` (или ``python -m scripts.seed``). Скрипт НЕ идемпотентен:
повторный запуск создаст дубли.
"""

from __future__ import annotations

import asyncio
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from b24client import Bitrix24Client, Bitrix24Error, random_valid_inn

TODAY = datetime.now(UTC).astimezone().date()

N_COMPANIES = 50
N_PRODUCTS = 60
N_DEALS = 150

COMPANY_FORMS = ["ООО", "АО", "ИП"]
COMPANY_STEMS = [
    "Ромашка", "ТехноПром", "ГидроМаш", "СтройСнаб", "АкваСервис", "ПромЛогистик",
    "ЭнергоМонтаж", "ВодоканалСервис", "АгроТех", "МеталлБаза", "СеверСтрой",
    "УралМаш", "СибЭнерго", "ВолгаПром", "НефтеСнаб", "АгроСоюз", "ТеплоСервис",
    "ГидроСистемы", "ПромРесурс", "ИнжСтрой",
]
COMPANY_CITIES = [
    "Екатеринбург", "Челябинск", "Пермь", "Тюмень", "Новосибирск", "Казань",
    "Самара", "Уфа", "Омск", "Красноярск",
]

PRODUCT_TYPES = [
    ("Насос скважинный", "скважинный насос для водоснабжения из глубоких скважин"),
    ("Насос дренажный", "дренажный насос для откачки грязной воды и затопленных подвалов"),
    ("Насос циркуляционный", "циркуляционный насос для систем отопления и ГВС"),
    ("Насос центробежный", "центробежный насос общего промышленного назначения"),
    ("Мотопомпа", "бензиновая мотопомпа для перекачки чистой и загрязнённой воды"),
    ("Насосная станция", "автоматическая насосная станция с гидроаккумулятором"),
    ("Гидроаккумулятор", "напорный бак для стабилизации давления в системе водоснабжения"),
    ("Компрессор поршневой", "поршневой воздушный компрессор для гаража и производства"),
]
PRODUCT_BRANDS = ["Джилекс", "Вихрь", "Грундфос", "Калибр", "Патриот", "Зубр", "Водолей"]
DEAL_SUBJECTS = [
    "поставка насосного оборудования", "сервисное обслуживание систем",
    "монтаж насосной станции", "комплектация объекта", "замена оборудования",
    "дооснащение котельной", "пусконаладочные работы",
]

COMPANY_FIELDS_FOR_ADD = {"fields": {"TITLE": None, "UF_CRM_INN": None, "COMMENTS": None}}


def make_companies(rng: random.Random) -> list[dict]:
    used: set[str] = set()
    companies = []
    for _ in range(N_COMPANIES):
        while True:
            title = (
                f"{rng.choice(COMPANY_FORMS)} «{rng.choice(COMPANY_STEMS)}-"
                f"{rng.choice(COMPANY_CITIES)}»"
            )
            if title not in used:
                used.add(title)
                break
        companies.append(
            {
                "TITLE": title,
                "UF_CRM_INN": random_valid_inn(rng),
                "COMMENTS": f"Тестовый контрагент (seed {TODAY})",
            }
        )
    return companies


def make_products(rng: random.Random) -> list[dict]:
    products = []
    for i in range(N_PRODUCTS):
        type_name, type_desc = rng.choice(PRODUCT_TYPES)
        brand = rng.choice(PRODUCT_BRANDS)
        power = rng.choice([0.37, 0.55, 0.75, 1.1, 1.5, 2.2, 3.0])
        head = rng.choice([25, 35, 45, 55, 65, 80, 100])
        products.append(
            {
                "NAME": f"{type_name} {brand} {power} кВт / {head} м",
                "PRICE": rng.randrange(3200, 148_000, 100),
                "CURRENCY_ID": "RUB",
                # описание несёт атрибуты — на нём строится эмбеддинг каталога
                "DESCRIPTION": (
                    f"{type_name.capitalize()} {brand} мощностью {power} кВт, "
                    f"напор до {head} метров. {type_desc.capitalize()}. "
                    f"Гарантия {rng.choice([12, 18, 24])} мес."
                ),
            }
        )
    return products


def make_deals(rng: random.Random, company_ids: list[str]) -> list[dict]:
    today = TODAY
    deals = []
    for i in range(N_DEALS):
        day_offset = rng.randint(0, 180)
        deals.append(
            {
                "TITLE": f"Счёт №{1000 + i} — {rng.choice(DEAL_SUBJECTS)}",
                "COMPANY_ID": rng.choice(company_ids),
                "OPPORTUNITY": rng.randrange(15_000, 900_000, 500),
                "CURRENCY_ID": "RUB",
                "COMMENTS": (
                    f"Тестовая сделка (seed), дата документа "
                    f"{(today - timedelta(days=day_offset)).isoformat()}"
                ),
            }
        )
    return deals


async def add_in_chunks(b24: Bitrix24Client, method: str, rows: list[dict]) -> list[str]:
    """Создаёт сущности пачками через batch, возвращает список ID."""
    commands = {
        f"r{i}": (method, {"fields": row}) for i, row in enumerate(rows)
    }
    response = await b24.batch_chunked(commands)
    if response["result_error"]:
        raise Bitrix24Error(f"batch {method}: {response['result_error']}")
    ids = []
    for alias in commands:
        value = response["result"][alias]
        ids.append(str(value["ID"]) if isinstance(value, dict) else str(value))
    return ids


async def main() -> None:
    load_dotenv()
    rng = random.Random(42)  # детерминированный сид — воспроизводимые данные
    async with Bitrix24Client() as b24:
        # UF-поле под ИНН: имя нужно передавать с префиксом UF_CRM_,
        # иначе Битрикс допишет его сам (CRM_INN -> UF_CRM_CRM_INN)
        try:
            await b24.call(
                "crm.company.userfield.add",
                {"fields": {"FIELD_NAME": "UF_CRM_INN", "USER_TYPE_ID": "string", "MULTIPLE": "N"}},
            )
        except Bitrix24Error as exc:
            print(f"UF-поле ИНН: пропускаю ({exc})")

        companies = make_companies(rng)
        company_ids = await add_in_chunks(b24, "crm.company.add", companies)
        print(f"Компаний: {len(company_ids)}")

        products = make_products(rng)
        product_ids = await add_in_chunks(b24, "crm.product.add", products)
        print(f"Товаров: {len(product_ids)}")

        deals = make_deals(rng, company_ids)
        deal_ids = await add_in_chunks(b24, "crm.deal.add", deals)
        print(f"Сделок: {len(deal_ids)}")

        print("Готово. Портал наполнен тестовыми данными (seed=42).")


if __name__ == "__main__":
    asyncio.run(main())
