"""`RedisBackend`: keeps entries in a Redis server shared by many processes.

Requires the optional dependency: ``pip install cartucho[redis]``.

Each entry is one key, ``<prefix>:<scope digest>:<params digest>``, holding
the pickled `CacheEntry`, so it can expire on its own when ``ttl`` is set.
Keys come from a canonical, process-independent form of the `Params`
(Python's builtin ``hash`` is randomized per process). Arguments and results
must be picklable, and every process sharing the cache must be able to
import the same code.
"""
from __future__ import annotations

import hashlib
import pickle
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Iterator

from ..entry import CacheEntry
from ..params import Params
from .base import Backend

if TYPE_CHECKING:  # pragma: no cover
    from redis import Redis


# Fixed protocol so every process (and Python version) builds the same keys.
_KEY_PICKLE_PROTOCOL = 4
_GLOB_SPECIAL = re.compile(r"([*?\[\]\\])")


def _canonical(value: Any) -> Any:
    """Return a deterministic, picklable form of `value`.

    Mappings and sets are sorted so that equal values give the same key
    regardless of insertion order or hash seed.
    """

    if isinstance(value, Mapping):
        items = [(_canonical(k), _canonical(v)) for k, v in value.items()]
        return ("map", tuple(sorted(items, key=repr)))
    if isinstance(value, (list, tuple)):
        return ("seq", tuple(_canonical(v) for v in value))
    if isinstance(value, (set, frozenset)):
        return ("set", tuple(sorted((_canonical(v) for v in value), key=repr)))
    return value


def params_digest(params: Params) -> str:
    """Return a hex digest identifying `params`, stable across processes."""

    data = pickle.dumps(_canonical(params), protocol=_KEY_PICKLE_PROTOCOL)
    return hashlib.sha256(data).hexdigest()


def _scope_digest(scope: str) -> str:
    # Fixed length and hex only: no scope can be a prefix of another one and
    # it is safe inside SCAN glob patterns.
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:32]


class RedisBackend(Backend):
    """Backend in a (shared) Redis server.

    :param client: a ``redis.Redis`` client. Must **not** use
        ``decode_responses=True`` since values are binary pickles.
    :param prefix: namespace for every key, so several caches or apps can
        share one Redis database.
    :param ttl: optional time to live of each entry, in seconds.
    :param track_retrievals: when True (default) every hit rewrites the entry
        to update ``CacheEntry.last_retrieved``. Disable it to make hits a
        single read.
    """

    def __init__(
        self,
        client: "Redis",
        prefix: str = "cartucho",
        ttl: int | None = None,
        track_retrievals: bool = True,
    ) -> None:
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be a positive number of seconds")
        self._redis = client
        self._prefix = prefix
        self._ttl = ttl
        self._track_retrievals = track_retrievals

    @classmethod
    def from_url(cls, url: str, **kwargs: Any) -> "RedisBackend":
        """Build a backend from a Redis URL such as ``redis://host:6379/0``."""

        try:
            from redis import Redis
        except ImportError as exc:  # pragma: no cover
            raise ImportError("RedisBackend requires the 'redis' package: pip install cartucho[redis]") from exc
        return cls(Redis.from_url(url), **kwargs)

    def _key(self, scope: str, params: Params) -> str:
        return f"{self._prefix}:{_scope_digest(scope)}:{params_digest(params)}"

    def _pattern(self, scope: str | None) -> str:
        prefix = _GLOB_SPECIAL.sub(r"\\\1", self._prefix)
        return f"{prefix}:{'*' if scope is None else _scope_digest(scope)}:*"

    def _keys(self, scope: str | None) -> Iterator[bytes]:
        return self._redis.scan_iter(match=self._pattern(scope), count=500)

    def get(self, scope: str, params: Params) -> CacheEntry | None:
        key = self._key(scope, params)
        data = self._redis.get(key)
        if data is None:
            return None
        entry: CacheEntry = pickle.loads(data)
        if self._track_retrievals:
            entry.touch()
            # xx: don't resurrect an entry deleted or expired meanwhile.
            # keepttl: reading must not extend the entry's lifetime.
            self._redis.set(key, pickle.dumps(entry, protocol=pickle.HIGHEST_PROTOCOL), xx=True, keepttl=True)
        return entry

    def set(self, scope: str, entry: CacheEntry) -> None:
        data = pickle.dumps(entry, protocol=pickle.HIGHEST_PROTOCOL)
        self._redis.set(self._key(scope, entry.params), data, ex=self._ttl)

    def delete(self, scope: str, params: Params) -> CacheEntry | None:
        data = self._redis.getdel(self._key(scope, params))
        return None if data is None else pickle.loads(data)

    def has(self, scope: str, params: Params) -> bool:
        return bool(self._redis.exists(self._key(scope, params)))

    def entries(self, scope: str | None = None) -> Iterator[CacheEntry]:
        for key in self._keys(scope):
            data = self._redis.get(key)
            if data is not None:  # it may have expired since the scan
                yield pickle.loads(data)

    def clear(self, scope: str | None = None) -> None:
        batch: list[bytes] = []
        for key in self._keys(scope):
            batch.append(key)
            if len(batch) >= 500:
                self._redis.delete(*batch)
                batch.clear()
        if batch:
            self._redis.delete(*batch)

    def __len__(self) -> int:
        return sum(1 for _ in self._keys(None))

    def __repr__(self) -> str:
        cls = f"{self.__class__.__module__}.{self.__class__.__qualname__}"
        return f"{cls}(prefix={self._prefix!r}, ttl={self._ttl!r})"


__all__ = ["RedisBackend", "params_digest"]
