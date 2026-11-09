# 2. Cached results bound to the caller

Date: 2026-11-09

## Status

Proposed

## Context

API clients often return objects that are themselves `Cacheable` and keep a
reference to the client that created them, so their own cached methods use the
same cache and the same session:

```python
class Bitbucket(Cacheable):
    cache_id_attributes = ("url",)

    def __init__(self, url, session, return_cache=None):
        super().__init__(return_cache)
        self.url = url
        self.session = session  # requests.Session, credentials...

    @cached_method
    def repo(self, name):
        return Repo(self, name, self.session.get(...).json())


class Repo(Cacheable):
    def __init__(self, client, name, data):
        super().__init__(client.return_cache)
        self.client = client
        self.name = name

    @cached_method
    def commits(self):
        return self.client.session.get(...).json()
```

When `repo()` is read from the cache, the returned `Repo` must point to the
**live objects of the caller**: the `Bitbucket` instance whose method was
called, its `return_cache` and its session. Cartucho does nothing about it
today, and what happens depends on the backend (checked against the current
code):

| Backend                         | `bb.repo("x")` from the cache                                                                                                                                                                                                                                        |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `MemoryBackend`                 | The very object stored by the first call. It works in the simple case, but `repo.client` is the **first** `Bitbucket` instance, not the caller: another instance with the same cache id (e.g. another user's session) uses the first one's session and keeps it alive. |
| `RedisBackend`                  | `set` fails: `TypeError: cannot pickle '_thread.RLock' object`. Pickling the `Repo` pickles `client`, its session and `return_cache` (with the Redis client inside).                                                                                                  |
| `MemoryBackend.save()`/`load()` | Pickles, so the same failure with an unpicklable session. Otherwise, each `Repo` comes back with its **own stale copy** of the client and of the whole cache, not the loaded one.                                                                                     |

So a program tested with the default `MemoryBackend` breaks when moved to
Redis, the backend that is supposed to make the cache useful.

The general problem: a cached value is plain data, but these results also
reference **context** (the caller and the resources it holds) that is not data,
can't be serialized, and belongs to whoever reads the value, not to whoever
stored it.

Pickle has a mechanism for exactly this: `Pickler.persistent_id` replaces an
object with a placeholder while pickling, and `Unpickler.persistent_load`
resolves the placeholder while unpickling. A prototype replacing the caller
with a placeholder and resolving it against another instance gave a `Repo`
whose `client` and session were the new instance's, with internal references
(`commit.repo is repo`) preserved. The caller's session is never pickled,
because pickle doesn't traverse objects replaced by a placeholder.

## Decision

**Results are stored detached from the caller's context and bound to the
current caller on every hit, in the same way for every backend.**

### Context of a call

The context of a `cached_method` call is a mapping of names to live objects:

- `self`: the instance whose method was called.
- `return_cache`: its `return_cache`.
- `attr:<name>` for each attribute in the new class attribute
  `cache_context_attributes` (empty by default), for resources that results
  reference directly instead of through the instance, such as a session.

`Cacheable.cache_context()` returns it and can be overridden. The context of a
`cached_function` call only has `return_cache`, the decorator's cache.

### Storing

When a result is stored, it is pickled with a `persistent_id` that replaces
every object of the context (compared by identity) with its name.

- If no placeholder was used, the result doesn't depend on the caller and is
  stored as today: the object itself in `MemoryBackend`, pickled by
  `RedisBackend`.
- If some were used, the entry stores the pickled bytes wrapped in a marker
  type (`BoundResult`), so every backend keeps them as an opaque value. Pickling
  happens in `ReturnCache`, not in the backend, so third-party backends need no
  changes.
- Any other `ReturnCache` found in the result raises `TypeError`: it would
  belong to another context and can't be bound correctly.
- If the result can't be pickled, storing raises `TypeError` naming the
  unpicklable type and pointing to `cache_context_attributes`. This now also
  happens with `MemoryBackend`: **results of cached methods and functions must
  be picklable with every backend**, so problems show up in development, not
  when switching to Redis. Pickling happens once per miss, after the call that
  was expensive enough to be cached.

### Retrieving

On every hit of a `BoundResult`, the bytes are unpickled with a
`persistent_load` that resolves each name against the **current** caller's
context. The caller gets a new object graph pointing to its own instance, cache
and resources. A name that the current context doesn't have (e.g. an attribute
removed from `cache_context_attributes`) is treated as a miss.

On a miss, the caller gets the object it computed, untouched. With the async
decorator, callers that share a running computation but are not the one that
started it get the stored result bound to their own context, not the starter's
object.

### Cache id of nested Cacheables

A `Repo` needs its own scope per server and name, so it also needs the client's
cache id. `cache_id_attributes` may name an attribute holding a `Cacheable`;
its `cache_id()` is used instead of its `repr` (which today raises
`TypeError`):

```python
class Repo(Cacheable):
    cache_id_attributes = ("client", "name")  # client[url='https://...'],name='x'
```

## Alternatives considered

- **Keep the current behaviour.** Rejected: it fails with every serializing
  backend and leaks context between instances in memory.
- **Declare a parent attribute per class and rebind it by walking the result**
  (`cache_owner_attribute = "client"` plus a `cache_bind(owner)` hook). Rejected:
  every class at every level needs the declaration, the walk only reaches
  `Cacheable` objects inside builtin containers (not a `Page` dataclass holding
  repos), and it duplicates the graph traversal that pickle already does. It
  also still needs `__getstate__` to drop the parent before pickling.
- **Let identity-preserving backends skip binding** (a capability flag on
  `Backend`, so `MemoryBackend` keeps returning the stored object). Rejected:
  behaviour would differ between memory and Redis, which is the source of the
  problem, and in memory the result would stay bound to the first caller.
- **Bind the stored object in place.** Rejected: in memory, the object is
  shared, so another caller's binding would change it under the feet of whoever
  holds it, e.g. a request using another user's session.
- **Forbid context in results** (raise when a result references the caller).
  This is the minimal, safe version of this decision and is acceptable as a
  first step if the binding takes longer to implement: storing behaves as
  described above, but a used placeholder raises instead of producing a
  `BoundResult`.

## Consequences

- Clients returning `Cacheable` objects work the same with every backend, and
  across processes with Redis or `save()`/`load()`.
- **Identity is not preserved for results bound to the caller**: two hits
  return different, equal objects (`bb.repo("x") is not bb.repo("x")`), also in
  memory, where it was the same object until now. Mutating a returned object
  doesn't change the cache. Code needing a single shared instance must keep it
  itself, e.g. with `functools.cached_property` on the instance. Results not
  bound to the caller keep the current behaviour.
- A hit of a bound result costs one unpickling, also in memory.
- `MemoryBackend` now requires picklable results. This is a breaking change,
  acceptable while cartucho is in alpha.
- Only the caller, its cache and the declared attributes are context. Any other
  live object referenced by a result is pickled by value: unpicklable ones
  (another client, a global session, an open file) fail when storing, and
  picklable ones (a configuration object) are silently copied, so later changes
  to the original are not seen. Reach such objects through the caller, or
  declare them in `cache_context_attributes`.
- Results are bound to the **current** caller, not the one that computed them.
  They are only correct if both are equivalent, which is what the cache id
  promises (see [ADR 1](0001-cacheable-instance-scopes.md)). A forgotten
  attribute there now also hands one instance's objects, bound to it, to the
  other.
- Classes of results must be importable by every process sharing the cache, as
  for any value in Redis.
