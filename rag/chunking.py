"""Чанкинг документов: параграфы склеиваются в чанки до max_len.

Счёт/акт — короткие документы; чанки нужны в основном для договоров
и многостраничных актов. Таблица позиций режется построчно, чтобы
поиск по одной позиции был точным.
"""

from __future__ import annotations

MAX_LEN = 800


def chunk_text(text: str, max_len: int = MAX_LEN) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(para) > max_len:
            # длинный параграф — по строкам (таблицы позиций)
            for line in para.splitlines():
                if len(current) + len(line) + 1 > max_len:
                    if current:
                        chunks.append(current)
                    current = line
                else:
                    current = f"{current}\n{line}".strip()
            continue
        if len(current) + len(para) + 2 > max_len:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}".strip()
    if current:
        chunks.append(current)
    return chunks
