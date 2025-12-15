"""ReturnCache: per-function-scope cache manager.

This small utility provides a container that maps a scope
identifier to a `Cache` instance for that function. It acts as a
convenience for storing and retrieving cached results separated by
function or instance scope.
"""
from __future__ import annotations

from typing import Any

from .cache import Cache
from .params import Params


class ReturnCache:
    """A container of per-function caches.

    ReturnCache manages a mapping from scope strings to `Cache`
    instances. This lets each function or method have an isolated cache
    while reusing the `Cache` data structure.
    """

    def __init__(self) -> None:
        self._scopes: dict[str, Cache] = {"": Cache()}

    def get(self, params: Params, default: Any = None, scope: str | None = None) -> Any:
        ns = "" if scope is None else str(scope)
        c = self._scopes.get(ns)
        if not c:
            return default
        return c.get(params, default)

    def set(self, params: Params, result: Any, scope: str | None = None) -> None:
        ns = "" if scope is None else str(scope)
        c = self._scopes.setdefault(ns, Cache())
        c.set(params, result)

    def pop(self, params: Params, default: Any = None, scope: str | None = None) -> Any:
        ns = "" if scope is None else str(scope)
        c = self._scopes.get(ns)
        if not c:
            return default
        return c.pop(params, default)

    def items(self, scope: str | None = None):
        if scope is None:
            for ns, c in self._scopes.items():
                for p, r in c.items():
                    yield (p, r)
        else:
            ns = "" if scope is None else str(scope)
            c = self._scopes.get(ns, Cache())
            for p, r in c.items():
                yield (p, r)

    def entries(self, scope: str | None = None):
        if scope is None:
            for c in self._scopes.values():
                for e in c.entries():
                    yield e
        else:
            ns = "" if scope is None else str(scope)
            c = self._scopes.get(ns, Cache())
            for e in c.entries():
                yield e

    def clear(self) -> None:
        self._scopes.clear()
        self._scopes[""] = Cache()

    def clear_scope(self, scope: str | None) -> None:
        ns = "" if scope is None else str(scope)
        self._scopes.pop(ns, None)

    def __len__(self) -> int:
        return sum(len(c) for c in self._scopes.values())

    def __contains__(self, params: Params) -> bool:
        return any(params in c for c in self._scopes.values())

    def scopes(self):
        return list(self._scopes.keys())

    def has(self, params: Params, scope: str | None = None) -> bool:
        """Return True if the specified scope contains `params`.

        If `scope` is None, checks across all scopes.
        """
        if scope is None:
            return any(params in c for c in self._scopes.values())
        ns = "" if scope is None else str(scope)
        c = self._scopes.get(ns)
        if not c:
            return False
        return params in c


class Cacheable:
    def __init__(self, return_cache: ReturnCache | None = None) -> None:
        self.return_cache = return_cache
