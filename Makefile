.PHONY: test lint clean-pyc clean-build clean-test build

clean: clean-pyc clean-build clean-test

clean-pyc:
	find . -name '*.pyc' -exec rm --force {} +
	find . -name '*.pyo' -exec rm --force {} +
	find . -name '*~' -exec rm --force {} +
	find . -name '__pycache__' -exec rmdir {} +

clean-test:
	rm --force --recursive .coverage
	rm --force --recursive .pytest_cache

clean-build:
	rm --force --recursive build/
	rm --force --recursive dist/
	rm --force --recursive *.egg-info

build:
	poetry build

lint:
	poetry run flake8

test:
	poetry run pytest

test-coverage:
	poetry run coverage run --source cartucho -m pytest
	poetry run coverage report -m

test-all: lint test-coverage