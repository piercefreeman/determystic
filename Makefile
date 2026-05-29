.PHONY: lint lint-validate test

lint:
	uv run ruff check --fix .
	uv run ty check .
	uv run determystic validate .

lint-validate:
	uv run ruff check .
	uv run ty check .
	uv run determystic validate .

test:
	uv run pytest -vvv
