"""Офлайн-тесты валидации схем (без сети и LLM)."""

from agent.schemas import Invoice, InvoiceItem


def _inv(**kw) -> Invoice:
    base = {
        "seller_name": "ООО «Ромашка»",
        "seller_inn": "7707083893",
        "document_number": "1234",
        "document_date": "2026-09-14",
        "items": [InvoiceItem(name="Позиция 1", qty=2, price=100.0, total=200.0)],
        "total": 200.0,
    }
    base.update(kw)
    return Invoice(**base)


def test_valid_invoice_has_no_issues():
    assert _inv().issues() == []
    assert not _inv().needs_human_review()


def test_bad_inn_checksum_flagged():
    inv = _inv(seller_inn="7707083894")
    assert any("ИНН" in p for p in inv.issues())
    assert inv.needs_human_review()


def test_total_mismatch_flagged():
    inv = _inv(total=999.0)
    assert any("итог" in p for p in inv.issues())


def test_low_confidence_flagged():
    inv = _inv(confidence={"seller_inn": 0.4, "total": 0.95})
    problems = inv.issues()
    assert any("уверенность" in p for p in problems)


def test_inn_whitespace_cleaned():
    inv = _inv(seller_inn="7707 0838 93")
    assert inv.seller_inn == "7707083893"
    assert inv.issues() == []
