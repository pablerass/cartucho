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
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Any

from ..entry import CacheEntry
from ..params import Params
from .base import Backend

if TYPE_CHECKING:  # pragma: no cover
    from redis import Redis


# Fixed protocol so every process (and Python version) builds the same keys.
_KEY_PICKLE_PROTOCOL = 4
_GLOB_SPECIAL = re.compile(r"([*?\[\]\\])")


def _canonical(value: Any) -> Any:
    """Return a deterministic, picklable form of ``value``.

    Mappings and sets are sorted so that equal values give the same key
    regardless of insertion order or hash seed.

    Args:
        value: The value to convert.

    Returns:
        Nested tuples tagged with the container kind, or ``value`` itself.
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
    """Return a hex digest identifying ``params``, stable across processes.

    Equal `Params` give the same digest in every process and Python version,
    unlike `hash`, which is randomized per process for strings.

    Args:
        params: Parameters to identify.

    Returns:
        A SHA-256 hex digest.
    """

    data = pickle.dumps(_canonical(params), protocol=_KEY_PICKLE_PROTOCOL)
    return hashlib.sha256(data).hexdigest()


def _unpickle(data: bytes | str) -> CacheEntry:
    """Load an entry stored by `RedisBackend`.

    Raises:
        TypeError: When ``data`` is a ``str``, which happens when the client
            uses ``decode_responses=True``.
    """
    if isinstance(data, str):
        raise TypeError("RedisBackend needs a Redis client without decode_responses=True")
    return pickle.loads(data)


def _scope_digest(scope: str) -> str:
    """Return a fixed-length hex digest of ``scope`` for use in keys."""
    # Fixed length and hex only: no scope can be a prefix of another one and
    # it is safe inside SCAN glob patterns.
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:32]


class RedisBackend(Backend):
    """Backend in a Redis server, which several processes or hosts can share.

    Warning:
        Entries are unpickled when read, which can run arbitrary code. Only
        use a Redis server that untrusted parties can't write to.

    Args:
        client: A ``redis.Redis`` client. It must **not** use
            ``decode_responses=True``, since values are binary pickles.
        prefix: Namespace for every key, so several caches or applications
            can share one Redis database.
        ttl: Time to live of each entry, in seconds. ``None`` (default) keeps
            entries until they are removed or evicted by Redis.
        track_retrievals: When ``True`` (default), every hit rewrites the
            entry to update `CacheEntry.last_retrieved`. Disable it to make
            hits a single read.

    Raises:
        ValueError: When ``ttl`` is not positive.

    Example:
        .. code-block:: python

            backend = RedisBackend.from_url("redis://cache-host:6379/0", prefix="myapp", ttl=3600)
            cache = ReturnCache(backend)
    """

    def __init__(
        self,
        client: Redis,
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
    def from_url(cls, url: str, **kwargs: Any) -> RedisBackend:
        """Create a backend connected to a Redis URL.

        Args:
            url: Redis URL, such as ``redis://host:6379/0``.
            **kwargs: Other arguments of `RedisBackend`.

        Returns:
            The new backend.

        Raises:
            ImportError: When the ``redis`` package is not installed.
        """

        try:
            from redis import Redis
        except ImportError as exc:  # pragma: no cover
            raise ImportError("RedisBackend requires the 'redis' package: pip install cartucho[redis]") from exc
        return cls(Redis.from_url(url), **kwargs)

    def _key(self, scope: str, params: Params) -> str:
        """Return the Redis key of the entry for ``params`` in ``scope``."""
        return f"{self._prefix}:{_scope_digest(scope)}:{params_digest(params)}"

    def _pattern(self, scope: str | None) -> str:
        """Return the ``SCAN`` glob matching ``scope``, or every scope if ``None``."""
        prefix = _GLOB_SPECIAL.sub(r"\\\1", self._prefix)
        return f"{prefix}:{'*' if scope is None else _scope_digest(scope)}:*"

    def _keys(self, scope: str | None) -> Iterator[bytes]:
        """Iterate over the keys of ``scope``, or of every scope if ``None``."""
        return self._redis.scan_iter(match=self._pattern(scope), count=500)

    def get(self, scope: str, params: Params) -> CacheEntry | None:
        """See `Backend.get`."""
        key = self._key(scope, params)
        data = self._redis.get(key)
        if data is None:
            return None
        entry = _unpickle(data)
        if self._track_retrievals:
            entry.touch()
            # xx: don't resurrect an entry deleted or expired meanwhile.
            # keepttl: reading must not extend the entry's lifetime.
            self._redis.set(key, pickle.dumps(entry, protocol=pickle.HIGHEST_PROTOCOL), xx=True, keepttl=True)
        return entry

    def set(self, scope: str, entry: CacheEntry) -> None:
        """See `Backend.set`."""
        data = pickle.dumps(entry, protocol=pickle.HIGHEST_PROTOCOL)
        self._redis.set(self._key(scope, entry.params), data, ex=self._ttl)

    def delete(self, scope: str, params: Params) -> CacheEntry | None:
        """See `Backend.delete`."""
        data = self._redis.getdel(self._key(scope, params))
        return None if data is None else _unpickle(data)

    def has(self, scope: str, params: Params) -> bool:
        """See `Backend.has`."""
        return bool(self._redis.exists(self._key(scope, params)))

    def entries(self, scope: str | None = None) -> Iterator[CacheEntry]:
        """See `Backend.entries`.

        Uses ``SCAN``, so it doesn't block the server, but entries added or
        removed meanwhile may or may not be listed.
        """
        for key in self._keys(scope):
            data = self._redis.get(key)
            if data is not None:  # it may have expired since the scan
                yield _unpickle(data)

    def clear(self, scope: str | None = None) -> None:
        """See `Backend.clear`.

        Only keys under this backend's ``prefix`` are removed.
        """
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
