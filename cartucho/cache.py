"""Simple cache utilities that store `Params` -> function result pairs.

This module provides two small helpers:

- ``CacheEntry``: a tiny container that holds a `Params` instance and the
  corresponding function result. The entry is read-only and hashes/equality
  by the contained `Params` so it can be used in sets if needed.

- ``Cache``: a minimal mapping from `Params` to results with convenience
  methods `get`, `set`, `pop`, `clear`, and iteration over items.

The cache itself does not implement eviction; it's a simple in-memory store.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import time
import pickle
from pathlib import Path

from .params import Params


@dataclass
class CacheEntry:
    """Container holding a `Params`, its result and timestamps.

    - `creation_time` is set when the entry is created and can be used for
      eviction based on age.
    - `last_retrieved` is updated by the `Cache` when the entry is returned
      from `get()`.

    Equality and hashing are based on `params` only.
    """

    params: Params
    result: Any
    creation_time: float = field(default_factory=time.time)
    last_retrieved: Optional[float] = None

    def touch(self) -> None:
        """Update the `last_retrieved` timestamp to now."""

        self.last_retrieved = time.time()

    def __hash__(self) -> int:
        return hash(self.params)

    def __eq__(self, other) -> bool:
        if isinstance(other, CacheEntry):
            return self.params == other.params
        return NotImplemented

    def __repr__(self) -> str:
        cls = f"{self.__class__.__module__}.{self.__class__.__qualname__}"
        return (
            f"{cls}(params={self.params!r}, result={self.result!r}, "
            f"creation_time={self.creation_time!r}, last_retrieved={self.last_retrieved!r})"
        )


class Cache:
    """Simple in-memory cache mapping `Params` -> result.

    Example:
        cache = Cache()
        p = Params([('a', 1), ('b', 2)])
        cache.set(p, compute(p))
        value = cache.get(p)
    """

    def __init__(self) -> None:
        # Map Params -> CacheEntry
        # A simple in-memory cache keyed by Params. This class doesn't handle
        # function scope separation — that's provided by ReturnCache.
        self._store: dict[Params, CacheEntry] = {}

    def get(self, params: Params, default: Any = None) -> Any:
        """Return the cached result for `params` or `default` if missing.

        If an entry is found its `last_retrieved` timestamp is updated.
        """

        entry = self._store.get(params)
        if entry is None:
            return default
        entry.touch()
        return entry.result

    def set(self, params: Params, result: Any) -> None:
        """Store `result` under `params`.

        This will overwrite any previous value for the same `Params` and
        set the creation timestamp to now.
        """

        self._store[params] = CacheEntry(params=params, result=result)

    def pop(self, params: Params, default: Any = None) -> Any:
        """Remove and return value for `params` or `default` if not present.

        Returns the stored `result` (not the CacheEntry).
        """

        entry = self._store.pop(params, None)
        if entry is None:
            return default
        return entry.result

    def items(self):
        """Return an iterator of `(Params, result)` pairs.

        If `scope` is None yield across all scope entries.
        """

        for p, entry in self._store.items():
            yield (p, entry.result)

    def entries(self):
        """Return an iterator of `CacheEntry` objects for stored items.

        If `scope` is None yield across all scope entries.
        """

        for entry in self._store.values():
            yield entry

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, params: Params) -> bool:
        return params in self._store

    def has(self, params: Params) -> bool:
        """Return True if the cache contains a value for `params`."""
        return params in self._store

    def clear(self) -> None:
        """Clear all cached entries."""

        self._store.clear()

    # Note: Cache is intentionally simple and doesn't expose scopes.

    def __repr__(self) -> str:
        cls = f"{self.__class__.__module__}.{self.__class__.__qualname__}"
        return f"{cls}(size={len(self)})"

    def __str__(self) -> str:
        return f"Cache(size={len(self)})"

    def save(self, path: str | Path) -> None:
        """Persist the cache to `path` using pickle.

        The entire internal store (mapping `Params -> CacheEntry`) is
        pickled. This is the simplest approach and preserves our
        custom types (Params, FrozenDict, CacheEntry). The caller is
        responsible for ensuring the environment loading the file has
        the same code available (same module and class names).
        """

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("wb") as f:
            pickle.dump(self._store, f, protocol=pickle.HIGHEST_PROTOCOL)

    @classmethod
    def load(cls, path: str | Path) -> "Cache":
        """Load a cache from `path` previously written with `save`.

        Returns a new `Cache` instance whose internal store is populated
        from the file. If the file does not exist `FileNotFoundError` is
        raised.
        """

        p = Path(path)
        with p.open("rb") as f:
            store = pickle.load(f)

        c = cls()
        c._store = store
        return c
