# 4. Choosing the parameters of the cache key

Date: 2026-11-09

## Status

Accepted

## Context

The cache key of a call is its `Params`: every parameter of the signature,
with defaults applied. `cached_method` only removes `self`.

Many functions take parameters that don't change the result: a timeout, a
retry count, a page size, a session, a logger. Putting them in the key:

- **Duplicates entries.** `repo("x", timeout=5)` and `repo("x", timeout=30)`
  are computed and stored twice.
- **Breaks some backends.** `RedisBackend` pickles the key to digest it, so an
  unpicklable argument (a session, a logger) fails every call.
- **Complicates invalidation.** A future decorator that invalidates entries
  when a method changes data must rebuild the exact key. Every parameter in the
  key is one more value it has to know, even if it never changes the result.

## Decision

`cached_function` and `cached_method` accept two keyword-only options to choose
the key parameters:

- `key`: the names of the parameters that make up the key.
- `ignore`: the names of the parameters left out of the key.

```python
@cached_function(cache, ignore=("timeout", "session"))
def get_game(game_id, timeout=10, session=None): ...

class Bitbucket(Cacheable):
    @cached_method(key=("name",))
    def repo(self, name, retries=3): ...

    @cached_method              # bare form unchanged: every parameter is in the key
    def repos(self): ...
```

Rules:

- **`key` and `ignore` can't be combined.** Passing both raises `TypeError`.
  This keeps one meaning per declaration and no precedence rules.
- **Both are resolved once, when decorating, to the same thing:** a fixed tuple
  of key parameter names in signature order. Everything after that (building
  keys, and later invalidation) only deals with that tuple, so having two
  options adds no logic at call time.
- **Names are checked when decorating.** A name that is not a parameter of the
  function, or a bare string (`key="name"`, which would be read as letters),
  raises `TypeError`. A typo is found at import, not as wrong cache hits.
- **`self` can't be named.** It is never part of the key of a method
  (see [ADR 1](0001-cacheable-instance-scopes.md)); the instance's part of the
  scope is its `cache_id`.
- **Defaults still apply.** The call is bound to the full signature first and
  then filtered, so `repo("x")` and `repo(name="x")` are the same key.
- **`*args` and `**kwargs`** are included or left out as a whole, by their
  name.
- `key=()` is valid: every call shares one entry.

### Which one to use

`ignore` is the recommended one in general. Its default is safe: a parameter
added to the function later is part of the key unless someone decides
otherwise, so it can only cause extra misses. With `key`, a new parameter that
changes the result is silently left out, and calls with different values get
each other's results.

`key` fits functions where only one or two of many parameters identify the
result.

### Alternatives considered

- **Only `key`.** Simple and explicit, but the unsafe default described above.
- **Only `ignore`.** Safe, but long and noisy for functions with many options.
- **Both, combinable** (`key` then minus `ignore`, or the opposite). Rejected:
  it needs precedence rules and adds nothing that one of them can't say.
- **Marking parameters in the signature** (e.g. `Annotated[int, NotKey]`).
  Rejected for now: it couples the function's types to the cache and doesn't
  work on functions you don't own.

## Consequences

- Calls that differ only in parameters left out of the key share one entry,
  also concurrent coroutine calls, which share a single run. **The author is
  responsible** for leaving out only parameters that don't change the result,
  like the attributes of the cache id in ADR 1.
- Changing `key` or `ignore` changes the stored keys, so existing entries are
  no longer found. They are only missed, never wrong.
- Parameters left out of the key don't need to be picklable or comparable.
- `cached_evicts` rebuilds keys from the key parameters only (see
  [ADR 5](0005-evicting-cached-results.md)).
