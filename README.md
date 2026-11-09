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

By default every parameter (except `self`) is part of the cache key. To
leave out parameters that don't change the result, such as a timeout, a
session or a logger, pass **either** `ignore` or `key`, never both:

```python
@cached_function(cache, ignore=("timeout", "session"))  # every parameter but these
def get_game(game_id, timeout=10, session=None): ...

class Bitbucket(Cacheable):
    @cached_method(key=("name",))                       # only these parameters
    def repo(self, name, retries=3): ...
```

Calls that differ only in parameters left out share one entry. Prefer
`ignore`: a parameter added later is then part of the key unless you say
otherwise. See [ADR 4](docs/adr/0004-choosing-key-parameters.md).

Both decorators also work on coroutine functions (`async def`): the wrapper
is a coroutine function as well and caches the awaited result.

### Evicting stale results

When a function or method changes the data a cached one returns, decorate it
with `cached_evicts`. Each call removes the matching cached entry, without
reading it. The key is rebuilt by name from the call's arguments, then from
the attributes of `self`; keyword arguments map names that differ:

```python
class Bitbucket(Cacheable):
    cache_id_attributes = ("url",)

    @cached_method
    def repo(self, name): ...

    @cached_evicts(repo)                            # name from the arguments
    def delete_repo(self, name): ...


class Repo(Cacheable):
    def __init__(self, client, name):
        super().__init__(client.return_cache)       # same cache as the client
        self.url = client.url                       # client's cache id
        self.name = name

    @cached_evicts(Bitbucket.repo)                  # old name, from self
    @cached_evicts(Bitbucket.repo, name="new_name") # new name, from the argument
    def rename(self, new_name): ...
```

Values are read before the call and the entry is removed after it, even if it
raises. See [ADR 5](docs/adr/0005-evicting-cached-results.md).

### Good to know

- **Arguments are compared by value and type.** `f(1)`, `f(True)` and
  `f(1.0)` are three entries, even though the values are equal in Python.
  Lists and tuples with the same items are the same argument, and so are
  dicts with the same items in any order.
- **Don't change cached results.** `MemoryBackend` returns the stored object
  itself, so changing it changes what later calls get. `RedisBackend` returns
  a new copy on every call, unless `local_cache_size` is set (see below).
- **Concurrent misses.** Concurrent calls to a coroutine with the same
  arguments share a single run. Calls from several threads, or processes
  sharing a `RedisBackend`, that miss at the same time each run the function,
  and the last one stored wins.
- **Evictions only cover decorated changes.** Changes made elsewhere (another
  program, the web UI) are not seen: use `ttl` in `RedisBackend` to bound how
  long results can be stale. A read running at the same time as an eviction
  may store the old value again.
- **The cache itself is synchronous.** In coroutines, reading and writing a
  `RedisBackend` blocks the event loop for the duration of the request.

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

By default every hit downloads and unpickles a new copy. With
`local_cache_size=N`, the backend keeps up to `N` unpickled entries in the
process. A hit then reads only a small version token from Redis and, if the
entry hasn't been overwritten, deleted or expired, returns the same object as
before, as `MemoryBackend` does:

```python
backend = RedisBackend.from_url("redis://cache-host:6379/0", local_cache_size=1024)
```

New backends subclass `cartucho.backends.Backend`.

## Development

This project uses [uv](https://docs.astral.sh/uv/) for dependency management and packaging:

```bash
# install uv (if you don't already have it)
curl -LsSf https://astral.sh/uv/install.sh | sh

# create the virtual environment with every dependency group
uv sync

# run the tests
uv run pytest
```

The `Makefile` wraps the common tasks: `make test`, `make lint`,
`make type-check`, `make docs` (HTML in `docs/_build/html`) and `make build`.

Releases are cut with `make release-minor`, `make release-major` (from
`main`) and `make release-patch` (from a `release/X.Y` branch); see
[Releasing](docs/releasing.md).
