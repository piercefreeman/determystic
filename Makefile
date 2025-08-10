.PHONY: lint

lint:
	uv run ruff check --fix .
	uv run ty check .

lint-validate:
	uv run ruff check .
	uv run ty check .

test:
	uv run pytest -vvv
