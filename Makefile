.PHONY: test lint clean-pyc clean-build clean-test clean-docs build docs version release-major release-minor release-patch

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

# Cut a release; see docs/releasing.md. DRY_RUN=1 previews, PUSH=1 publishes.
release-major:
	scripts/release.sh major

release-minor:
	scripts/release.sh minor

release-patch:
	scripts/release.sh patch

build:
	uv build

docs:
	uv run sphinx-build --nitpicky --fail-on-warning --keep-going --builder html docs docs/_build/html
	@echo "Open docs/_build/html/index.html"

lint:
	uv run ruff check

type-check:
	uv run ty check

test:
	uv run pytest

test-coverage:
	uv run coverage run --source cartucho -m pytest
	uv run coverage report -m

test-all: lint type-check test-coverage