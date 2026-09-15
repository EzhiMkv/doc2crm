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
from aiogram.filters import CommandStart
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
        "Привет! Я doc2crm 📄→💼\n"
        "Пришли фото счёта — я извлеку реквизиты, найду контрагента\n"
        "и после твоего подтверждения создам сделку в Битрикс24."
    )


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


@dp.callback_query(F.data.startswith("doc2crm:"))
async def on_decision(query: CallbackQuery, bot: Bot) -> None:
    _, action, thread = query.data.split(":", 2)
    decision = "yes" if action == "confirm" else "no"
    await query.message.edit_reply_markup(reply_markup=None)
    state = await resume_document_flow(graph, thread, decision)
    if state.get("deal_id"):
        await query.message.answer(
            f"💼 **Готово!** Сделка #{state['deal_id']} создана:\n{state['deal_url']}",
            parse_mode="Markdown",
        )
    else:
        await query.message.answer("🚫 Отменено. Документ не попал в CRM.")


async def main() -> None:
    bot = Bot(BOT_TOKEN)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
