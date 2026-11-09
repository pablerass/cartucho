"""The `Backend` interface every cache backend implements."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from ..entry import CacheEntry
from ..params import Params


class Backend(ABC):
    """Where a `ReturnCache` keeps its entries.

    Entries are grouped by ``scope`` (one per cached function or method) and
    identified inside it by their `Params`. Implementations only have to
    store and find `CacheEntry` objects; `ReturnCache` does the rest.

    Subclasses must implement every abstract method. ``__len__`` has a generic
    implementation based on `entries` that subclasses can override with a
    faster one.
    """

    @abstractmethod
    def get(self, scope: str, params: Params) -> CacheEntry | None:
        """Return the entry for ``params`` in ``scope``.

        Implementations should call `CacheEntry.touch` on the entry found.

        Args:
            scope: Scope of the entry.
            params: Parameters identifying the entry.

        Returns:
            The entry, or ``None`` if there is none.
        """

    @abstractmethod
    def set(self, scope: str, entry: CacheEntry) -> None:
        """Store ``entry`` in ``scope``, replacing any entry with the same params.

        Args:
            scope: Scope of the entry.
            entry: Entry to store. Its ``params`` identify it.
        """

    @abstractmethod
    def delete(self, scope: str, params: Params) -> CacheEntry | None:
        """Remove the entry for ``params`` in ``scope``.

        Args:
            scope: Scope of the entry.
            params: Parameters identifying the entry.

        Returns:
            The removed entry, or ``None`` if there was none.
        """

    def discard(self, scope: str, params: Params) -> None:
        """Remove the entry for ``params`` in ``scope`` without reading it.

        Unlike `delete`, it doesn't return the entry, so backends that
        serialize entries can skip loading it. The default implementation
        calls `delete`; override it when deleting without reading is cheaper.

        Args:
            scope: Scope of the entry.
            params: Parameters identifying the entry.
        """
        self.delete(scope, params)

    @abstractmethod
    def has(self, scope: str, params: Params) -> bool:
        """Return whether ``scope`` holds an entry for ``params``.

        Args:
            scope: Scope of the entry.
            params: Parameters identifying the entry.

        Returns:
            ``True`` if the entry exists.
        """

    @abstractmethod
    def entries(self, scope: str | None = None) -> Iterator[CacheEntry]:
        """Iterate over stored entries.

        Args:
            scope: Scope to list, or ``None`` for every scope.

        Yields:
            CacheEntry: Each entry, in no particular order.
        """

    @abstractmethod
    def clear(self, scope: str | None = None) -> None:
        """Remove entries.

        Args:
            scope: Scope to empty, or ``None`` to remove every entry.
        """

    def __len__(self) -> int:
        """Return the number of entries in every scope."""
        return sum(1 for _ in self.entries())


__all__ = ["Backend"]
