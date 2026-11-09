# 5. Evicting cached results made stale by changes

Date: 2026-11-09

## Status

Accepted

## Context

Cached functions and methods usually read data that other functions and
methods change: `Bitbucket.repo(name)` is cached, and `delete_repo(name)` or
`Repo.rename(new_name)` make its results stale. Until now the only ways to get
fresh data were waiting for a `ttl` or clearing whole scopes by hand, which
needs knowing the internal scope names.

The changes are often made by objects other than the one whose method is
cached: a `Repo` returned by `Bitbucket.repo` changes data cached in the
`Bitbucket` scope. The changing code usually has every value the cached key is
made of, as arguments or as attributes, but not the cached object itself.

## Decision

A decorator, `cached_evicts(target, **sources)`, marks functions and methods
that change data. Each call removes the entry of `target` that the call makes
stale.

### Name

**Selected: `cached_evicts`.**

Every decorator of cartucho is named `cached_<what>`: `cached_function`,
`cached_method` and `cached_evicts`. The shared prefix groups them (in the
docs, in autocompletion, in imports) and says they all belong to the cache.
"Evict" is the usual term for removing a cache entry. The rejected names are
listed under [Alternatives considered](#alternatives-considered).

### Keys are rebuilt, never read

The key of `target` is rebuilt from the call and removed with
`ReturnCache.discard`, a new operation that doesn't return the removed entry.
`Backend.discard` has a default implementation based on `Backend.delete`, so
existing backends keep working; `RedisBackend` overrides it with a single
`DEL`, so an eviction never downloads or unpickles anything, and it also drops
the backend's local copy.

The key is what `target` would use for its own call
([ADR 4](0004-choosing-key-parameters.md) keeps it to the key parameters):

- **Key parameters** are looked up by name in the `sources`, then in the call's
  arguments, then in the attributes of `self`, and finally in `target`'s
  default for the parameter.
- **For a cached method**, the scope also needs the cache id
  ([ADR 1](0001-cacheable-instance-scopes.md)) of its class. Those names are
  looked up in the attributes of `self` first, then in the arguments, because
  an argument with the same name usually carries a new value
  (`move(self, url)`), while the entries to evict are under the current one.
- **`sources`** maps a name to the argument or attribute holding its value
  (`name="new_name"`), or to a callable that receives the call's `Params`, for
  anything else.

The cache is the one of the decorated function (`cached_function`) or the
`return_cache` of `self` (`cached_method`), so an object evicting another class's
results must share its cache, as related objects already do
([ADR 2](0002-results-bound-to-the-caller.md)).

The class of a cached method is the class of `self` when it defines the
method, or is found through the method's qualified name otherwise. Its cache id
is rebuilt with the new `Cacheable.build_cache_id`, which `cache_id` now uses
too, so both always agree. A class that overrides `cache_id()` can only be
evicted from its own methods, where `self.cache_id()` is at hand: there is no
way to rebuild a custom id from values.

### When

- Values are read **before** the decorated call, so a method that changes the
  attributes the key comes from (a rename) evicts the entry of the old values.
  A value that can't be found raises `TypeError` before anything runs, so the
  change is not applied with a stale cache left behind.
- The entry is removed **after** the call, also when it raises: a failed
  change may have been applied partly.
- Several entries (the old and the new name) are evicted by stacking the
  decorator, one entry per decorator.

### Alternatives considered

- **Named `invalidate` or `invalidates`.** Rejected: nothing in the name
  refers to the cache, so it is unclear what is invalidated.
- **Named `evicts_cached`.** It reads as an English phrase ("evicts the cached
  `Bitbucket.repo`"). Rejected in favour of the `cached_<what>` structure
  shared by every decorator.
- **Reading the cache to find entries** (scanning a scope and matching
  values). Rejected: the key can be rebuilt exactly, and scanning is a `SCAN`
  in Redis.
- **Evicting the whole scope of the target.** Simple, but it throws away
  unrelated results and needs a `SCAN` too. Still possible by hand with
  `ReturnCache.clear(scope)`.
- **Several targets in one decorator.** Rejected: `sources` would have to say
  which target each mapping is for. Stacking is explicit and as short.
- **Arguments only, no attributes.** Rejected: methods of result objects
  (`Repo.rename`) get their key from `self`, and the cache id always does.
- **Evicting before the call.** Rejected: a read between the eviction and the
  change would store the old value again for the whole lifetime of the entry.

## Consequences

- Classes can keep cached reads fresh after their own changes with one line
  per affected method, also across processes with `RedisBackend`.
- **A key that doesn't match evicts nothing, silently.** Values are compared by
  value and type, so the evicting side must produce the same values the cached
  call received (`"1"` is not `1`). Missing names fail loudly, mismatching
  values can't be detected.
- Changes not made through decorated code (other programs, the web UI) are not
  evicted: `ttl` remains the bound on staleness.
- A read running at the same time as a change may store the old value again
  right after the eviction. Cartucho doesn't prevent it.
- Running async computations of the evicted key are not cancelled; their
  result, computed before the change, is stored when they finish.
- Cached methods of classes defined inside functions can only be evicted from
  methods of their own class, since their class can't be found by name.
- `Backend` gained `discard`, with a default implementation: third-party
  backends keep working and can override it.
