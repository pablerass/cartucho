# Cartucho

A library to easily cache function and method return values.

## Usage

```python
from cartucho import ReturnCache, cached_function

cache = ReturnCache()

@cached_function(cache)
def get_game(game_id):
    return api.get(f"/games/{game_id}")

get_game(13)  # calls the API
get_game(13)  # returned from the cache
```

Methods of classes inheriting from `Cacheable` can use `@cached_method`
and the instance's `return_cache`. All instances of a class share cached
results unless the class lists the attributes that change them:

```python
class Bitbucket(Cacheable):
    cache_id_attributes = ("url",)  # one cache scope per installation

    def __init__(self, url, return_cache=None):
        super().__init__(return_cache)
        self.url = url

    @cached_method
    def repo(self, name):
        ...
```

See [ADR 1](docs/adr/0001-cacheable-instance-scopes.md) for the reasoning.

## Backends

`ReturnCache` keeps entries in a backend from `cartucho.backends`.
Changing the backend doesn't change anything else:

| Backend | Use it when | |
|---|---|---|
| `MemoryBackend` | one process (default) | `save(path)` / `MemoryBackend.load(path)` keep it between runs |
| `RedisBackend` | several processes or hosts share a cache | `pip install cartucho[redis]` |

```python
from cartucho.backends import RedisBackend

cache = ReturnCache(RedisBackend.from_url("redis://cache-host:6379/0", prefix="myapp", ttl=3600))
```

With `RedisBackend`, arguments and results must be picklable and every
process must be able to import the same code. `ttl` (seconds) is optional.

New backends subclass `cartucho.backends.Backend`.

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
