.PHONY: sync format format-check lint test check clean

sync:
	uv sync --extra dev

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

lint:
	uv run ruff check .

test:
	uv run pytest

check: format-check lint test

clean:
	rm -rf .ruff_cache .pytest_cache build dist *.egg-info src/*.egg-info
