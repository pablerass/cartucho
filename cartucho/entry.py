"""`CacheEntry`: a cached result together with its key and timestamps."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .params import Params


@dataclass
class CacheEntry:
    """A cached `result` for `params`.

    - `creation_time` is set when the entry is created.
    - `last_retrieved` is updated by the backend every time the entry is read.
    """

    params: Params
    result: Any
    creation_time: float = field(default_factory=time.time)
    last_retrieved: Optional[float] = None

    def touch(self) -> None:
        """Update the `last_retrieved` timestamp to now."""

        self.last_retrieved = time.time()


__all__ = ["CacheEntry"]
