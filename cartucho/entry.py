"""`CacheEntry`: a cached result together with its key and timestamps."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .params import Params


@dataclass
class CacheEntry:
    """A cached result and the parameters it was computed for.

    Attributes:
        params: Parameters of the call that produced ``result``.
        result: Value returned by the call.
        creation_time: Unix timestamp of when the entry was created. Set
            automatically.
        last_retrieved: Unix timestamp of the last read, or ``None`` if the
            entry has never been read. Backends update it through `touch`.
    """

    params: Params
    result: Any
    creation_time: float = field(default_factory=time.time)
    last_retrieved: float | None = None

    def touch(self) -> None:
        """Set `last_retrieved` to the current time."""

        self.last_retrieved = time.time()


__all__ = ["CacheEntry"]
