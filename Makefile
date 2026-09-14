.PHONY: install seed eval test lint

install:
	python3 -m venv .venv
	.venv/bin/pip install -e '.[dev]'

seed:            ## залить тестовые данные на портал Битрикса
	.venv/bin/python -m scripts.seed

test:
	.venv/bin/pytest

lint:
	.venv/bin/ruff check b24client scripts tests
