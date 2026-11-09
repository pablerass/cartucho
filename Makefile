.PHONY: test lint clean-pyc clean-build clean-test clean-docs build docs

clean: clean-pyc clean-build clean-test clean-docs

clean-pyc:
	find . -name '*.pyc' -exec rm --force {} +
	find . -name '*.pyo' -exec rm --force {} +
	find . -name '*~' -exec rm --force {} +
	find . -name '__pycache__' -exec rmdir {} +

clean-test:
	rm --force --recursive .coverage
	rm --force --recursive .pytest_cache

clean-docs:
	rm --force --recursive docs/_build/

clean-build:
	rm --force --recursive build/
	rm --force --recursive dist/
	rm --force --recursive *.egg-info

version:
	uv version

bump-major:
	uv run bumpver update --major

bump-minor:
	uv run bumpver update --minor

bump-patch:
	uv run bumpver update --patch

build:
	uv build

docs:
	uv run sphinx-build --nitpicky --fail-on-warning --keep-going --builder html docs docs/_build/html
	@echo "Open docs/_build/html/index.html"

lint:
	uv run flake8

type-check:
	uv run mypy .

test:
	uv run pytest

test-coverage:
	uv run coverage run --source cartucho -m pytest
	uv run coverage report -m

test-all: lint type-check test-coverage