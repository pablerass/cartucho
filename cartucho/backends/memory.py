"""`MemoryBackend`: keeps entries in a dict inside the current process."""
from __future__ import annotations

import pickle
from pathlib import Path
from typing import Iterator

from ..entry import CacheEntry
from ..params import Params
from .base import Backend


class MemoryBackend(Backend):
    """In-process backend. Fastest option, but nothing is shared or kept
    after the process exits unless you `save()` it and `load()` it later.
    Arguments and results don't need to be picklable unless you `save()`.
    """

    def __init__(self) -> None:
        self._scopes: dict[str, dict[Params, CacheEntry]] = {}

    def get(self, scope: str, params: Params) -> CacheEntry | None:
        entry = self._scopes.get(scope, {}).get(params)
        if entry is not None:
            entry.touch()
        return entry

    def set(self, scope: str, entry: CacheEntry) -> None:
        self._scopes.setdefault(scope, {})[entry.params] = entry

    def delete(self, scope: str, params: Params) -> CacheEntry | None:
        return self._scopes.get(scope, {}).pop(params, None)

    def has(self, scope: str, params: Params) -> bool:
        return params in self._scopes.get(scope, {})

    def entries(self, scope: str | None = None) -> Iterator[CacheEntry]:
        stores = self._scopes.values() if scope is None else [self._scopes.get(scope, {})]
        for store in stores:
            yield from store.values()

    def clear(self, scope: str | None = None) -> None:
        if scope is None:
            self._scopes.clear()
        else:
            self._scopes.pop(scope, None)

    def __len__(self) -> int:
        return sum(len(store) for store in self._scopes.values())

    def save(self, path: str | Path) -> None:
        """Pickle every entry to `path`."""

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("wb") as f:
            pickle.dump(self._scopes, f, protocol=pickle.HIGHEST_PROTOCOL)

    @classmethod
    def load(cls, path: str | Path) -> "MemoryBackend":
        """Return a backend with the entries previously written by `save()`."""

        backend = cls()
        with Path(path).open("rb") as f:
            backend._scopes = pickle.load(f)
        return backend


__all__ = ["MemoryBackend"]
