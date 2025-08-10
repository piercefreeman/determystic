.PHONY: lint

lint:
	uv run ruff check --fix .
	uv run ty check .
