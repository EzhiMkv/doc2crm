"""Headless-прогон графа: фаза 1 до interrupt, подтверждение, сделка.

Запуск: python -m scripts.smoke_graph evals/fixtures/invoice_1.png
Проверяет весь контур без Telegram: extract → validate → match → HITL → deal.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

from agent.graph import build_graph, resume_document_flow, start_document_flow


async def main() -> None:
    image = sys.argv[1] if len(sys.argv) > 1 else "evals/fixtures/invoice_1.png"
    graph = build_graph()
    thread = "smoke-test"

    print("── фаза 1: извлечение и матчинг ──")
    state = await start_document_flow(graph, image, thread)
    inv = state.get("invoice", {})
    print(json.dumps(inv, ensure_ascii=False, indent=2)[:600])
    print("проблемы валидации:", state.get("issues") or "нет")
    print(f"контрагент: company_id={state.get('company_id')} "
          f"(создан: {state.get('company_created')})")
    print("граф прерван на подтверждении:", "__interrupt__" in str(state.keys()) or "ожидание решения")

    print("\n── фаза 2: подтверждение человека ──")
    state = await resume_document_flow(graph, thread, "yes")
    print("сделка:", state.get("deal_id"), state.get("deal_url"))
    print("error:", state.get("error") or "нет")


if __name__ == "__main__":
    asyncio.run(main())
