"""Cache backends for `ReturnCache`.

- `MemoryBackend`: in-process dict (default).
- `RedisBackend`: shared Redis server (``pip install cartucho[redis]``).

New backends subclass `Backend`.
"""
from .base import Backend
from .memory import MemoryBackend
from .redis import RedisBackend

__all__ = ["Backend", "MemoryBackend", "RedisBackend"]
