# Cartucho

A library to easily cache function and method return values.

## Requirements

- Python >= 3.10
- [uv](https://docs.astral.sh/uv/)

## Installation

Clone the repository and install the project with its dependencies:

```sh
uv sync
```

This creates a virtual environment in `.venv` with the package and the `dev`
and `test` dependency groups installed. To install only the runtime
dependencies, use `uv sync --no-default-groups`.

## Development

```sh
make lint           # ruff
make type-check     # ty
make test           # pytest
make test-coverage  # pytest with coverage report
make test-all       # all of the above
make build          # build sdist and wheel into dist/
```
