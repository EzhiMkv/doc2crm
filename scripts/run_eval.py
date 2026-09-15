"""Прогон eval-сета: извлечение всех фикстур, сверка с ground truth.

Результат: evals/results.json + сводка в stdout. Учитывает 429 free-тира
(экспоненциальный backoff). Запуск: make eval
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

from agent.extraction import extract_invoice
from agent.schemas import Invoice
from providers.llm import LLM

FIXTURES = Path(__file__).resolve().parents[1] / "evals" / "fixtures"
FIELDS = ["seller_name", "seller_inn", "document_number", "document_date", "total"]


def norm(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


async def eval_one(llm: LLM, png: Path, gt: dict) -> dict:
    t0 = time.time()
    delay = 10.0
    for _ in range(5):
        try:
            inv: Invoice = await extract_invoice(llm, str(png))
            break
        except Exception as ex:
            if "429" not in str(ex):
                raise
            print(f"  429 на {png.name}, пауза {delay:.0f}с")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 120.0)
    else:
        raise RuntimeError(f"{png.name}: ретраи исчерпаны")

    d = inv.model_dump()
    per_field = {k: norm(d.get(k)) == norm(gt.get(k)) for k in FIELDS}
    return {
        "file": png.name,
        "seconds": round(time.time() - t0, 1),
        "issues": inv.issues(),
        "per_field": per_field,
        "accuracy": round(sum(per_field.values()) / len(FIELDS), 3),
        "extracted": {k: d.get(k) for k in FIELDS},
    }


async def main() -> None:
    pairs = []
    for png in sorted(FIXTURES.glob("invoice_*.png"), key=lambda p: int(p.stem.split("_")[1])):
        gt_file = png.with_suffix("").with_suffix(".gt.json").with_suffix(".json")
        gt_file = png.parent / f"{png.stem}.gt.json"
        if not gt_file.exists():
            continue
        pairs.append((png, json.loads(gt_file.read_text(encoding="utf-8"))))
    print(f"фикстур: {len(pairs)}")

    llm = LLM()
    results = []
    out = FIXTURES.parent / "results.json"

    def save() -> None:
        accs = [r["accuracy"] for r in results if "accuracy" in r]
        summary = {
            "model": llm.model,
            "documents": len(results),
            "field_accuracy": round(sum(accs) / len(accs), 3) if accs else 0,
            "seconds_per_doc": round(
                sum(r.get("seconds", 0) for r in results) / max(len(accs), 1), 1
            ),
        }
        out.write_text(
            json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    for png, gt in pairs:
        try:
            r = await eval_one(llm, png, gt)
            results.append(r)
            missed = [k for k, ok in r["per_field"].items() if not ok]
            print(f"{png.name}: {r['accuracy']:.0%} за {r['seconds']}s"
                  + (f" | промахи: {missed}" if missed else ""), flush=True)
        except Exception as ex:  # noqa: BLE001
            results.append({"file": png.name, "error": str(ex)[:200]})
            print(f"{png.name}: ОШИБКА {str(ex)[:100]}", flush=True)
        save()  # после каждого документа — прогресс не теряется
    await llm.aclose()

    accs = [r["accuracy"] for r in results if "accuracy" in r]
    summary = {
        "model": llm.model,
        "documents": len(results),
        "field_accuracy": round(sum(accs) / len(accs), 3) if accs else 0,
        "seconds_per_doc": round(
            sum(r.get("seconds", 0) for r in results) / max(len(accs), 1), 1
        ),
    }
    print(f"\nИТОГО: точность по полям {summary['field_accuracy']:.1%}, "
          f"{summary['seconds_per_doc']}s/док → {out}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
