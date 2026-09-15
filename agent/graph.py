"""Граф агента «пришёл документ — появилась сделка» (LangGraph).

Пайплайн:
    extract → validate → ingest(RAG) → match → confirm(HITL) → execute → report

Ключевая точка — узел confirm: граф ПРЕРЫВАЕТСЯ через interrupt() и ждёт
решения человека сколько угодно долго (состояние в чекпойнтере). После
подтверждения выполнение возобновляется с того же места — это и есть
human-in-the-loop на checkpointing-е, а не «спросили и забыли».

Headless-прогон обеих фаз: scripts/smoke_graph.py.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from agent.extraction import extract_invoice
from providers.llm import LLM


class AgentState(TypedDict, total=False):
    image_path: str
    invoice: dict[str, Any]
    issues: list[str]
    needs_review: bool
    confirmed: bool
    company_id: int
    company_created: bool
    deal_id: int
    deal_url: str
    error: str


def _b24():
    from b24client import Bitrix24Client

    return Bitrix24Client()


def _portal_base() -> str:
    import os

    url = os.environ["B24_WEBHOOK_URL"]
    return url.split("/rest/")[0]


# ── узлы ──────────────────────────────────────────────────────────────────

async def extract_node(state: AgentState) -> dict[str, Any]:
    llm = LLM()
    try:
        invoice = await extract_invoice(llm, state["image_path"])
        return {"invoice": invoice.model_dump()}
    finally:
        await llm.aclose()


def validate_node(state: AgentState) -> dict[str, Any]:
    from agent.schemas import Invoice

    invoice = Invoice.model_validate(state["invoice"])
    return {"issues": invoice.issues(), "needs_review": invoice.needs_human_review()}


async def ingest_node(state: AgentState) -> dict[str, Any]:
    """Документ попадает в RAG-хранилище сразу после валидации —
    независимо от решения по сделке. Сбой RAG не валит пайплайн."""
    try:
        from agent.schemas import Invoice
        from providers.embeddings import get_embedder
        from rag.db import create_pool
        from rag.documents import ingest_invoice

        inv = Invoice.model_validate(state["invoice"])
        pool = await create_pool()
        try:
            await ingest_invoice(
                pool, get_embedder(), inv,
                source="telegram", file_path=state.get("image_path"),
            )
        finally:
            await pool.close()
    except Exception as ex:  # noqa: BLE001 — RAG некритичен для сделки,
        print(f"ingest skipped: {ex!r}"[:120])  # но сбой фиксируем
    return {}


async def match_node(state: AgentState) -> dict[str, Any]:
    """Находим контрагента по ИНН/названию; нет — создаём (точечные live-запросы)."""
    inv = state["invoice"]
    inn = inv.get("seller_inn")
    name = inv.get("seller_name") or f"Контрагент (ИНН {inn})"
    async with _b24() as b24:
        found = await b24.find_companies(inn=inn) if inn else []
        if found:
            return {"company_id": int(found[0]["ID"]), "company_created": False}
        created = await b24.call(
            "crm.company.add",
            {"fields": {"TITLE": name, "UF_CRM_INN": inn or "", "COMMENTS": "Создан агентом doc2crm"}},
        )
        return {"company_id": int(created), "company_created": True}


async def confirm_node(state: AgentState) -> dict[str, Any]:
    """HITL: граф прерывается здесь. Время ожидания не ограничено."""
    decision = interrupt(
        {"invoice": state["invoice"], "issues": state.get("issues", [])}
    )
    return {"confirmed": decision == "yes"}


async def execute_node(state: AgentState) -> dict[str, Any]:
    inv = state["invoice"]
    title = f"Счёт №{inv.get('document_number') or '—'} — {inv.get('seller_name') or 'без поставщика'}"
    fields: dict[str, Any] = {
        "TITLE": title,
        "COMPANY_ID": state["company_id"],
        "COMMENTS": "Сделка создана агентом doc2crm из документа",
    }
    if inv.get("total") is not None:
        fields["OPPORTUNITY"] = inv["total"]
        fields["CURRENCY_ID"] = inv.get("currency", "RUB")
    async with _b24() as b24:
        deal_id = await b24.deal_create(fields)
        doc_date = inv.get("document_date")
        await b24.deal_comment_add(
            deal_id,
            "🤖 doc2crm: сделка создана из документа\n"
            f"• Поставщик: {inv.get('seller_name') or '—'} (ИНН {inv.get('seller_inn') or '—'})\n"
            f"• Счёт №{inv.get('document_number') or '—'} от {doc_date or '—'}\n"
            f"• Позиций: {len(inv.get('items') or [])}, сумма: {inv.get('total') or '—'} {inv.get('currency', 'RUB')}\n"
            f"• Проблемы валидации: {'; '.join(state.get('issues') or []) or 'нет'}",
        )
    deal_url = f"{_portal_base()}/crm/deal/details/{deal_id}/"
    return {"deal_id": deal_id, "deal_url": deal_url}


def route_after_confirm(state: AgentState) -> str:
    return "execute" if state.get("confirmed") else END


# ── сборка ────────────────────────────────────────────────────────────────

def build_graph():
    g = StateGraph(AgentState)
    g.add_node("extract", extract_node)
    g.add_node("validate", validate_node)
    g.add_node("ingest", ingest_node)
    g.add_node("match", match_node)
    g.add_node("confirm", confirm_node)
    g.add_node("execute", execute_node)
    g.add_edge(START, "extract")
    g.add_edge("extract", "validate")
    g.add_edge("validate", "ingest")
    g.add_edge("ingest", "match")
    g.add_edge("match", "confirm")
    g.add_conditional_edges("confirm", route_after_confirm, {"execute": "execute", END: END})
    g.add_edge("execute", END)
    return g.compile(checkpointer=InMemorySaver())


async def start_document_flow(graph, image_path: str, thread_id: str) -> dict[str, Any]:
    """Фаза 1: прогон до прерывания на подтверждении."""
    result = await graph.ainvoke(
        {"image_path": image_path},
        config={"configurable": {"thread_id": thread_id}},
    )
    return result


async def resume_document_flow(graph, thread_id: str, decision: str) -> dict[str, Any]:
    """Фаза 2: продолжение после решения человека."""
    return await graph.ainvoke(
        Command(resume=decision),
        config={"configurable": {"thread_id": thread_id}},
    )
