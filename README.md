# Cartucho

A library to easily cache function and method return values.

## Using Poetry

This project uses Poetry for dependency management and packaging. To get started:

```bash
# install poetry (if you don't already have it)
curl -sSL https://install.python-poetry.org | python3 -

# install dependencies and create virtual environment
poetry install

# run tests
poetry run pytest

# start a shell in the virtual environment
poetry shell
```

Tip: The project includes a `Makefile` with common targets like `make test` and
`make build` that call Poetry under the hood.
