# 1. Cache scopes of Cacheable instances

Date: 2026-11-09

## Status

Accepted

## Context

`ReturnCache` separates entries in **scopes**. `cached_function` uses one scope
per function (`module.qualname`) and `cached_method` one per method. The cache
key inside a scope is the `Params` of the call, with `self` removed.

`self` can't be part of the key: an instance usually holds a session, a
connection or credentials, which can't be compared or pickled, and is a
different object in every run. But it can't simply be ignored either, because
some instances return different results for the same call. For example, a
`Bitbucket` client may be used against several Bitbucket installations
(`https://bitbucket.org` and an on-premises server): `repo("cartucho")` asks
each server for a different repository.

Until now the method scope ended with `id(self)`, the memory address of the
instance. That separated the two `Bitbucket` clients, but:

- **Results were never reused** by another instance, not even an identical one,
  nor by another process. With persistent or shared backends
  (`MemoryBackend.save()`, `RedisBackend`), cached method results were useless
  after the instance was gone.
- **Results could be wrong.** Python reuses memory addresses. In a later run, or
  after the original instance is garbage collected, a new instance can get the
  same `id` and read results cached for another instance, e.g. another
  installation's data.

Most classes don't need any separation at all. A `BoardGameGeek` client always
talks to the same public API, so every instance should share results. It would
only need separating if, for example, a development API were accessed with
different parameters.

## Decision

The instance part of a method scope is an explicit, stable **cache id**
declared by the class, instead of the object's memory address.

- `Cacheable` has a `cache_id()` method. The method scope is
  `module.qualname` when it returns an empty string, and
  `module.qualname[<cache id>]` otherwise.
- By default `cache_id()` is built from the class attribute
  `cache_id_attributes`, a tuple of attribute names, as `name=repr(value)`
  joined by commas. It is empty by default, so **all instances of a class share
  the same scope** unless the class says otherwise:

  ```python
  class BoardGameGeek(Cacheable):  # shared by every instance
      ...

  class Bitbucket(Cacheable):      # one scope per installation
      cache_id_attributes = ("url",)
  ```

- Classes whose identity can't be expressed as a list of attributes override
  `cache_id()` and return any string that is stable across processes.
- `cache_id()` raises `TypeError` for attributes whose type uses the default
  `object.__repr__`, because that repr contains the memory address and would
  silently bring back the problems of `id(self)`.
- The id is computed on every call, so changing a declared attribute of an
  instance moves it to the corresponding scope.

### Alternatives considered

- **Keep `id(self)`.** Rejected for the reasons in the context.
- **Include the whole instance in the key** (pickling it or its `__dict__`).
  Rejected: instances hold unpicklable or irrelevant state (sessions, tokens,
  counters), and any change to it would invalidate the cache.
- **Use `hash(self)` or `__eq__`.** Rejected: the default ones are based on
  `id`, and `hash` of strings is randomized per process, so it can't be used
  with shared or persistent backends.
- **A separate `ReturnCache` per instance or installation.** It works and
  remains possible, but makes every user wire it by hand for the common case.
  The declarative attribute keeps it to one line in the class.

## Consequences

- Cached method results are reused across instances, runs and processes, which
  is the point of `RedisBackend` and `MemoryBackend.save()`.
- **The class author is now responsible** for declaring what changes results.
  Forgetting an attribute makes different instances share results, e.g. two
  `Bitbucket` installations returning each other's data. This must be
  considered whenever a `Cacheable` gets a constructor argument that changes
  what its methods return.
- Credentials must not be listed in `cache_id_attributes`: the id ends up in
  scope names, which are visible in the in-memory backend and, hashed, in Redis
  keys. Identify the target (URL, account, environment) instead. If two
  credentials see different data on the same server, override `cache_id()` to
  return a non-secret identifier, such as the user name.
- Values used in the id need a stable `repr` (`str`, `int`, tuples of them…).
- Values are used as they are, with no normalization and no warning: cartucho
  can't know that `https://x.org` and `https://x.org/` mean the same server,
  and detecting it would need value-specific heuristics and a scan of every
  scope. Equivalent but different values only cause cache misses (extra calls),
  never wrong results. Classes that care normalize the attribute in `__init__`
  or override `cache_id()`.
- Scope names of cached methods changed (no more `.<id>` suffix), so entries
  saved by previous versions are not found. They were not reusable anyway.
