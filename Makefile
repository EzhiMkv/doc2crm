.PHONY: install seed eval test lint

install:
	python3 -m venv .venv
	.venv/bin/pip install -e '.[dev]'

bot:              ## запустить Telegram-бота
	.venv/bin/python -m apps.bot.main

seed:            ## залить тестовые данные на портал Битрикса
	.venv/bin/python -m scripts.seed

eval:            ## прогнать eval-сет извлечения
	.venv/bin/python -m scripts.run_eval

test:
	.venv/bin/pytest

lint:
	.venv/bin/ruff check b24client scripts tests
