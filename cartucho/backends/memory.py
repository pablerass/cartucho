"""`MemoryBackend`: keeps entries in a dict inside the current process."""
from __future__ import annotations

import pickle
from collections.abc import Iterator
from pathlib import Path
from typing import Self

from ..entry import CacheEntry
from ..params import Params
from .base import Backend


class MemoryBackend(Backend):
    """In-process backend, and the default of `ReturnCache`.

    It is the fastest option, but entries are neither shared with other
    processes nor kept after the process exits, unless you `save` them and
    `load` them later. Arguments and results only need to be picklable if
    you `save`.
    """

    def __init__(self) -> None:
        self._scopes: dict[str, dict[Params, CacheEntry]] = {}

    def get(self, scope: str, params: Params) -> CacheEntry | None:
        """See `Backend.get`."""
        entry = self._scopes.get(scope, {}).get(params)
        if entry is not None:
            entry.touch()
        return entry

    def set(self, scope: str, entry: CacheEntry) -> None:
        """See `Backend.set`."""
        self._scopes.setdefault(scope, {})[entry.params] = entry

    def delete(self, scope: str, params: Params) -> CacheEntry | None:
        """See `Backend.delete`."""
        return self._scopes.get(scope, {}).pop(params, None)

    def has(self, scope: str, params: Params) -> bool:
        """See `Backend.has`."""
        return params in self._scopes.get(scope, {})

    def entries(self, scope: str | None = None) -> Iterator[CacheEntry]:
        """See `Backend.entries`."""
        stores = self._scopes.values() if scope is None else [self._scopes.get(scope, {})]
        for store in stores:
            yield from store.values()

    def clear(self, scope: str | None = None) -> None:
        """See `Backend.clear`."""
        if scope is None:
            self._scopes.clear()
        else:
            self._scopes.pop(scope, None)

    def __len__(self) -> int:
        return sum(len(store) for store in self._scopes.values())

    def save(self, path: str | Path) -> None:
        """Pickle every entry to a file.

        Missing parent directories are created and an existing file is
        overwritten.

        Args:
            path: File to write.

        Raises:
            pickle.PicklingError: When an argument or result can't be pickled.
        """

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("wb") as f:
            pickle.dump(self._scopes, f, protocol=pickle.HIGHEST_PROTOCOL)

    @classmethod
    def load(cls, path: str | Path) -> Self:
        """Create a backend with the entries written by `save`.

        Warning:
            Loading unpickles the file, which can run arbitrary code. Only
            load files you trust.

        Args:
            path: File previously written by `save`.

        Returns:
            A new backend holding the saved entries.

        Raises:
            FileNotFoundError: When ``path`` doesn't exist.
        """

        backend = cls()
        with Path(path).open("rb") as f:
            backend._scopes = pickle.load(f)
        return backend


__all__ = ["MemoryBackend"]
