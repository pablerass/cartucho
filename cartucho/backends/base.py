"""The `Backend` interface every cache backend implements."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

from ..entry import CacheEntry
from ..params import Params


class Backend(ABC):
    """Where a `ReturnCache` keeps its entries.

    Entries are grouped by `scope` (one per cached function or method) and
    identified inside it by their `Params`. Implementations only have to
    store and find `CacheEntry` objects; `ReturnCache` does the rest.
    """

    @abstractmethod
    def get(self, scope: str, params: Params) -> CacheEntry | None:
        """Return the entry for `params` in `scope` (touching it) or None."""

    @abstractmethod
    def set(self, scope: str, entry: CacheEntry) -> None:
        """Store `entry` in `scope`, replacing any entry with the same params."""

    @abstractmethod
    def delete(self, scope: str, params: Params) -> CacheEntry | None:
        """Remove and return the entry for `params` in `scope`, if any."""

    @abstractmethod
    def has(self, scope: str, params: Params) -> bool:
        """Return True if `scope` holds an entry for `params`."""

    @abstractmethod
    def entries(self, scope: str | None = None) -> Iterator[CacheEntry]:
        """Iterate over the entries of `scope`, or of every scope if None."""

    @abstractmethod
    def clear(self, scope: str | None = None) -> None:
        """Remove the entries of `scope`, or every entry if None."""

    def __len__(self) -> int:
        return sum(1 for _ in self.entries())


__all__ = ["Backend"]
