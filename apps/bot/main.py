"""Telegram-бот doc2crm: фото счёта → карточка с подтверждением → сделка в CRM.

Запуск: make bot (aiogram, long polling — вебхук для демо не нужен).
Состояние графа живёт в InMemorySaver: рестарт бота сбрасывает неотвеченные
подтверждения (v1.1: Postgres-чекпойнтер — переживает рестарты).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from agent.graph import build_graph, resume_document_flow, start_document_flow

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("TELEGRAM_BOT_TOKEN не задан (проверь .env)")

graph = build_graph()
dp = Dispatcher()

CONFIRM_CB = "doc2crm:confirm:{thread}"
CANCEL_CB = "doc2crm:cancel:{thread}"


def card_text(state: dict) -> str:
    inv = state.get("invoice", {})
    issues = state.get("issues") or []
    lines = [
        "📄 **Документ распознан**",
        f"Поставщик: {inv.get('seller_name') or '—'}",
        f"ИНН: {inv.get('seller_inn') or '—'}",
        f"Счёт №{inv.get('document_number') or '—'} от {inv.get('document_date') or '—'}",
        f"Позиций: {len(inv.get('items') or [])}",
        f"Сумма: {inv.get('total') or '—'} {inv.get('currency', 'RUB')}",
        f"Контрагент в CRM: {'найден' if not state.get('company_created') else 'создан новый'}",
    ]
    if issues:
        lines.append("⚠️ Проблемы: " + "; ".join(issues))
    lines.append("\nСоздаём сделку в Битрикс24?")
    return "\n".join(lines)


def confirm_keyboard(thread: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Создать сделку", callback_data=CONFIRM_CB.format(thread=thread)),
        InlineKeyboardButton(text="❌ Отмена", callback_data=CANCEL_CB.format(thread=thread)),
    ]])


@dp.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer(
        "Привет! Я doc2crm 📄→💼\n\n"
        "📸 Пришли **фото счёта** — я извлеку реквизиты, найду контрагента\n"
        "и после твоего подтверждения создам сделку в Битрикс24.\n\n"
        "🔍 А ещё можешь просто **спросить текстом** по загруженным документам:\n"
        "«На какую сумму были счета от Ромашки?»",
        parse_mode="Markdown",
    )


# ── режим Q&A: текстовый вопрос -> поиск по документам -> ответ с цитатами ──

_pool = None
_embedder = None


async def _qa_deps():
    global _pool, _embedder
    if _pool is None:
        from rag.db import create_pool

        _pool = await create_pool()
    if _embedder is None:
        from providers.embeddings import get_embedder

        _embedder = get_embedder()
    return _pool, _embedder


@dp.message(Command("find"))
async def on_find(message: Message, command: CommandObject) -> None:
    from rag.search import hybrid_items, parse_budget

    query = (command.args or "").strip()
    if not query:
        await message.answer("Использование: /find насос для скважины до 30к")
        return
    deal_id = last_deal.get(message.chat.id)
    notice = await message.answer("🔍 Семантический поиск по каталогу…")
    pool, embedder = await _qa_deps()
    max_price = parse_budget(query)
    items = await hybrid_items(pool, embedder, query, k=5, max_price=max_price)
    if not items:
        await notice.edit_text("Ничего не нашлось. Попробуй другую формулировку.")
        return
    budget_note = f" (бюджет до {max_price:.0f} ₽)" if max_price else ""
    lines = [f"🛒 **Подбор по каталогу**{budget_note}: «{query}»", ""]
    for item in items:
        price = f"{item['price']:.0f} ₽" if item["price"] else "цена не указана"
        lines.append(f"• {item['title']} — {price}")
    lines.append("")
    if deal_id:
        lines.append(f"Приложить товар к сделке #{deal_id} (создана в этом чате):")
    else:
        lines.append("Чтобы прикладывать товары к сделке — сначала создай сделку из счёта 📸")
    await notice.edit_text("\n".join(lines), parse_mode="Markdown")
    if deal_id:
        for item in items[:3]:
            await message.answer(
                f"🛒 {item['title']}",
                reply_markup=find_keyboard(deal_id, int(item["product_id"]), item["price"]),
            )


@dp.message(F.text, ~F.text.startswith("/"))
async def on_question(message: Message) -> None:
    from agent.qa import answer_question
    from providers.llm import LLM

    notice = await message.answer("🔍 Ищу по документам…")
    try:
        pool, embedder = await _qa_deps()
        llm = LLM()
        try:
            answer, sources = await answer_question(pool, embedder, llm, message.text)
        finally:
            await llm.aclose()
    except Exception as ex:  # noqa: BLE001 — пользователю уходим коротким сообщением
        await notice.edit_text(f"💥 Поиск не удался: {str(ex)[:150]}")
        return
    text = f"💬 {answer}"
    if sources:
        text += "\n\n── источники ──\n" + "\n".join(
            f"[{i}] счёт №{h['doc_number']} от {h['doc_date']} | "
            f"{h['seller_name']} | итог {h['total']}"
            for i, h in enumerate(sources, 1)
        )
    await notice.edit_text(text[:4000])


@dp.message(F.photo)
async def on_photo(message: Message, bot: Bot) -> None:
    thread = f"tg{message.chat.id}_{message.message_id}"
    dest = Path("/tmp") / f"doc2crm_{thread}.jpg"
    await bot.download(message.photo[-1], destination=dest)
    notice = await message.answer("👀 Принял. Извлекаю реквизиты и ищу контрагента…")
    try:
        state = await start_document_flow(graph, str(dest), thread)
    except Exception as ex:  # noqa: BLE001 — наружу идёт короткое человекочитаемое сообщение
        await notice.edit_text(f"💥 Не смог обработать документ: {str(ex)[:200]}")
        return
    await notice.edit_text(
        card_text(state), reply_markup=confirm_keyboard(thread),
        parse_mode="Markdown",
    )


@dp.callback_query(F.data.startswith("doc2crm:confirm:"), F.data.startswith("doc2crm:cancel:"))
async def on_decision(query: CallbackQuery, bot: Bot) -> None:
    _, action, thread = query.data.split(":", 2)
    decision = "yes" if action == "confirm" else "no"
    await query.message.edit_reply_markup(reply_markup=None)
    try:
        state = await resume_document_flow(graph, thread, decision)
    except Exception:  # noqa: BLE001 — сессия потеряна (рестарт бота, старая кнопка)
        await query.message.answer(
            "⚠️ Сессия устарела (бот перезапускался). Пришли документ заново 📸"
        )
        return
    if state.get("deal_id"):
        last_deal[query.message.chat.id] = state["deal_id"]
        await query.message.answer(
            f"💼 **Готово!** Сделка #{state['deal_id']} создана:\n{state['deal_url']}",
            parse_mode="Markdown",
        )
    else:
        await query.message.answer("🚫 Отменено. Документ не попал в CRM.")


# ── режим каталога: /find «насос для скважины до 30к» -> товары -> в сделку ──

last_deal: dict[int, int] = {}  # chat_id -> последняя сделка, созданная в чате


def find_keyboard(deal_id: int, product_id: int, price) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=f"➕ В сделку #{deal_id}" + (f" ({price:.0f} ₽)" if price else ""),
            callback_data=f"doc2crm:attach:{deal_id}:{product_id}",
        )
    ]])


@dp.callback_query(F.data.startswith("doc2crm:attach:"))
async def on_attach(query: CallbackQuery, bot: Bot) -> None:
    _, _, deal_id, product_id = query.data.split(":", 3)
    async with _b24_client() as b24:
        rows = await b24.call("crm.deal.productrows.get", {"ID": int(deal_id)}) or []
        price = None
        try:
            product = await b24.call("crm.product.get", {"id": product_id})
            price = product.get("PRICE")
        except Exception:  # noqa: BLE001 — цена не критична для прикрепления
            price = None
        row: dict = {"PRODUCT_ID": int(product_id), "QUANTITY": 1}
        if price:
            row["PRICE"] = price
        await b24.call(
            "crm.deal.productrows.set", {"ID": int(deal_id), "rows": rows + [row]}
        )
    await query.answer("✅ Товар приложен к сделке", show_alert=False)
    await query.message.edit_reply_markup(reply_markup=None)


def _b24_client():
    from b24client import Bitrix24Client

    return Bitrix24Client()


async def main() -> None:
    bot = Bot(BOT_TOKEN)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
