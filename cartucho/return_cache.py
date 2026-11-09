"""ReturnCache: caches return values in a pluggable `Backend`.

    cache = ReturnCache()                                    # in memory
    cache = ReturnCache(RedisBackend.from_url("redis://..."))  # shared

Entries are separated by `scope` (the decorators use one per function or
method); the default scope is ``""``.
"""
from __future__ import annotations

from typing import Any, Iterator

from .backends import Backend, MemoryBackend
from .entry import CacheEntry
from .params import Params


class ReturnCache:
    """Maps `(scope, Params)` to a result, kept in `backend`."""

    def __init__(self, backend: Backend | None = None) -> None:
        self.backend = MemoryBackend() if backend is None else backend

    def get(self, params: Params, default: Any = None, scope: str = "") -> Any:
        entry = self.backend.get(scope, params)
        return default if entry is None else entry.result

    def set(self, params: Params, result: Any, scope: str = "") -> None:
        self.backend.set(scope, CacheEntry(params=params, result=result))

    def pop(self, params: Params, default: Any = None, scope: str = "") -> Any:
        entry = self.backend.delete(scope, params)
        return default if entry is None else entry.result

    def has(self, params: Params, scope: str = "") -> bool:
        return self.backend.has(scope, params)

    def entries(self, scope: str | None = None) -> Iterator[CacheEntry]:
        """Entries of `scope`, or of every scope if None."""
        return self.backend.entries(scope)

    def items(self, scope: str | None = None) -> Iterator[tuple[Params, Any]]:
        """`(params, result)` pairs of `scope`, or of every scope if None."""
        for entry in self.backend.entries(scope):
            yield (entry.params, entry.result)

    def clear(self, scope: str | None = None) -> None:
        """Remove the entries of `scope`, or every entry if None."""
        self.backend.clear(scope)

    def __len__(self) -> int:
        return len(self.backend)

    def __repr__(self) -> str:
        return f"ReturnCache(backend={self.backend!r})"


class Cacheable:
    """Base class for objects whose `cached_method`s use `return_cache`.

    By default every instance of a class shares the same cache scope, so
    results survive the instance and are reused by other instances and
    processes. When some attributes change what the methods return (e.g. the
    URL of the server a client talks to), list them in `cache_id_attributes`
    and instances with different values get separate scopes:

        class Bitbucket(Cacheable):
            cache_id_attributes = ("url",)

    Override `cache_id()` for anything more complex.
    See docs/adr/0001-cacheable-instance-scopes.md.
    """

    cache_id_attributes: tuple[str, ...] = ()

    def __init__(self, return_cache: ReturnCache | None = None) -> None:
        self.return_cache = return_cache

    def cache_id(self) -> str:
        """Return what tells this instance's cached results apart.

        Built from `cache_id_attributes` as ``"name=value,..."``; empty when
        no attributes are declared. It must be the same for equivalent
        instances in every process, so values must have a stable `repr`.
        """

        parts = []
        for name in self.cache_id_attributes:
            value = getattr(self, name)
            if type(value).__repr__ is object.__repr__:
                # The default repr contains the memory address: it would make
                # the id differ per instance and process, silently breaking reuse.
                raise TypeError(
                    f"{type(self).__name__}.{name} ({type(value).__name__}) has no stable repr; "
                    "use a value such as str or int in cache_id_attributes or override cache_id()"
                )
            parts.append(f"{name}={value!r}")
        return ",".join(parts)


__all__ = ["ReturnCache", "Cacheable"]
