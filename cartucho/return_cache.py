"""`ReturnCache` stores return values in a pluggable `Backend`.

Entries are grouped by ``scope`` (the decorators use one per function or
method); the default scope is ``""``.

Example:
    .. code-block:: python

        cache = ReturnCache()                                      # in memory
        cache = ReturnCache(RedisBackend.from_url("redis://..."))  # shared
"""
from __future__ import annotations

from typing import Any, Iterator

from .backends import Backend, MemoryBackend
from .entry import CacheEntry
from .params import Params


class ReturnCache:
    """Maps ``(scope, Params)`` to a result, kept in a backend.

    Args:
        backend: Where the entries are kept. Defaults to a new
            `MemoryBackend`.

    Attributes:
        backend (Backend): The backend holding the entries.
    """

    def __init__(self, backend: Backend | None = None) -> None:
        self.backend = MemoryBackend() if backend is None else backend

    def get(self, params: Params, default: Any = None, scope: str = "") -> Any:
        """Return the cached result for ``params``.

        Args:
            params: Parameters identifying the entry.
            default: Value returned when there is no entry. Pass a sentinel
                to tell a missing entry apart from a cached ``None``.
            scope: Scope of the entry.

        Returns:
            The cached result, or ``default``.
        """
        entry = self.backend.get(scope, params)
        return default if entry is None else entry.result

    def set(self, params: Params, result: Any, scope: str = "") -> None:
        """Store ``result`` for ``params``, replacing any previous entry.

        Args:
            params: Parameters identifying the entry.
            result: Value to cache.
            scope: Scope of the entry.
        """
        self.backend.set(scope, CacheEntry(params=params, result=result))

    def pop(self, params: Params, default: Any = None, scope: str = "") -> Any:
        """Remove the entry for ``params`` and return its result.

        Args:
            params: Parameters identifying the entry.
            default: Value returned when there is no entry.
            scope: Scope of the entry.

        Returns:
            The removed result, or ``default``.
        """
        entry = self.backend.delete(scope, params)
        return default if entry is None else entry.result

    def has(self, params: Params, scope: str = "") -> bool:
        """Return whether there is an entry for ``params``.

        With shared backends the entry may expire right after this call, so
        prefer `get` with a sentinel ``default`` to read it.

        Args:
            params: Parameters identifying the entry.
            scope: Scope of the entry.

        Returns:
            ``True`` if the entry exists.
        """
        return self.backend.has(scope, params)

    def entries(self, scope: str | None = None) -> Iterator[CacheEntry]:
        """Iterate over the stored entries.

        Args:
            scope: Scope to list, or ``None`` for every scope.

        Yields:
            CacheEntry: Each entry, in no particular order.
        """
        return self.backend.entries(scope)

    def items(self, scope: str | None = None) -> Iterator[tuple[Params, Any]]:
        """Iterate over the stored ``(params, result)`` pairs.

        Args:
            scope: Scope to list, or ``None`` for every scope.

        Yields:
            tuple[Params, Any]: Each pair, in no particular order.
        """
        for entry in self.backend.entries(scope):
            yield (entry.params, entry.result)

    def clear(self, scope: str | None = None) -> None:
        """Remove entries.

        Args:
            scope: Scope to empty, or ``None`` to remove every entry.
        """
        self.backend.clear(scope)

    def __len__(self) -> int:
        return len(self.backend)

    def __repr__(self) -> str:
        return f"ReturnCache(backend={self.backend!r})"


class Cacheable:
    """Base class for objects whose `cached_method` methods use a cache.

    By default every instance of a class shares the same cache scope, so
    results outlive the instance and are reused by other instances and
    processes. When some attributes change what the methods return (e.g. the
    URL of the server a client talks to), list them in
    `cache_id_attributes` and instances with different values get separate
    scopes. Override `cache_id` for anything more complex.

    See ``docs/adr/0001-cacheable-instance-scopes.md`` for the reasoning.

    Args:
        return_cache: Cache used by the instance's cached methods. If
            ``None``, they are not cached.

    Attributes:
        cache_id_attributes (tuple[str, ...]): Class attribute naming the
            instance attributes that make up `cache_id`. Empty by default.
        return_cache (ReturnCache | None): Cache used by the instance's
            cached methods.

    Example:
        .. code-block:: python

            class Bitbucket(Cacheable):
                cache_id_attributes = ("url",)  # one cache scope per server

                def __init__(self, url, return_cache=None):
                    super().__init__(return_cache)
                    self.url = url

                @cached_method
                def repo(self, name):
                    ...
    """

    cache_id_attributes: tuple[str, ...] = ()

    def __init__(self, return_cache: ReturnCache | None = None) -> None:
        self.return_cache = return_cache

    def cache_id(self) -> str:
        """Return what tells this instance's cached results apart.

        It must be the same for equivalent instances in every process, so the
        values must have a stable `repr`.

        Returns:
            ``"name=value,..."`` built from `cache_id_attributes`, or an
            empty string when no attributes are declared.

        Raises:
            TypeError: When an attribute's value uses the default
                `object.__repr__`, which includes a memory address and would
                give each instance its own scope.
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
