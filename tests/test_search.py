"""Тесты NL->фильтров и бюджетного парсера."""

from rag.search import parse_budget


def test_budget_k_suffix():
    assert parse_budget("насос для скважины 30 метров до 30к") == 30_000


def test_budget_tys():
    assert parse_budget("что-нибудь до 45 тысяч") == 45_000


def test_budget_plain_number():
    assert parse_budget("насос до 30000") == 30_000


def test_budget_short_number():
    assert parse_budget("до 30") == 30_000  # в контексте каталога = тысячи


def test_no_budget():
    assert parse_budget("насос для скважины 30 метров") is None
