"""`RedisBackend`: keeps entries in a Redis server shared by many processes.

Requires the optional dependency: ``pip install cartucho[redis]``.

Each entry is one key, ``<prefix>:<scope digest>:<params digest>``, holding
a short header with a random version token followed by the pickled
`CacheEntry`, so it can expire on its own when ``ttl`` is set. The token lets
a backend with ``local_cache_size`` check with a tiny ``GETRANGE`` whether an
object it already unpickled is still current.
Keys come from a canonical, process-independent form of the `Params`
(Python's builtin ``hash`` is randomized per process). Arguments and results
must be picklable, and every process sharing the cache must be able to
import the same code.
"""
from __future__ import annotations

import hashlib
import os
import pickle
import re
import threading
from collections import OrderedDict
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Any, Self

from ..entry import CacheEntry
from ..params import Params
from .base import Backend

if TYPE_CHECKING:  # pragma: no cover
    from redis import Redis


# Fixed protocol so every process (and Python version) builds the same keys.
_KEY_PICKLE_PROTOCOL = 4
_GLOB_SPECIAL = re.compile(r"([*?\[\]\\])")

# Stored values are ``_MAGIC + token + pickle``. Pickles of protocol 2 or
# higher start with ``\x80``, so values written by older versions (a bare
# pickle) are told apart and still read.
_MAGIC = b"\x00ct1"
_TOKEN_SIZE = 16
_HEADER_SIZE = len(_MAGIC) + _TOKEN_SIZE


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


def _check_bytes(data: bytes | str) -> bytes:
    """Return ``data``, refusing the ``str`` a ``decode_responses=True`` client gives.

    Raises:
        TypeError: When ``data`` is a ``str``.
    """
    if isinstance(data, str):
        raise TypeError("RedisBackend needs a Redis client without decode_responses=True")
    return data


def _token(data: bytes | str) -> bytes | None:
    """Return the version token at the start of a stored value.

    Args:
        data: The stored value, or just its first `_HEADER_SIZE` bytes.

    Returns:
        The token, or ``None`` for a value without one (written by an older
        version, or a missing key).
    """
    data = _check_bytes(data)
    if len(data) >= _HEADER_SIZE and data.startswith(_MAGIC):
        return data[len(_MAGIC):_HEADER_SIZE]
    return None


def _unpickle(data: bytes | str) -> CacheEntry:
    """Load an entry stored by `RedisBackend`, with or without a header.

    Raises:
        TypeError: When ``data`` is a ``str``, which happens when the client
            uses ``decode_responses=True``.
    """
    data = _check_bytes(data)
    if data.startswith(_MAGIC):
        data = data[_HEADER_SIZE:]
    return pickle.loads(data)


def _dump(token: bytes, entry: CacheEntry) -> bytes:
    """Return the value stored for ``entry`` with version ``token``."""
    return _MAGIC + token + pickle.dumps(entry, protocol=pickle.HIGHEST_PROTOCOL)


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
        local_cache_size: How many unpickled entries to keep in this process,
            least recently used first out. ``0`` (default) disables it, and
            every hit downloads and unpickles a new copy. When enabled, a hit
            on a kept entry only reads its version token from Redis and
            returns the **same object** as before, as `MemoryBackend` does,
            so changing a returned result changes what later hits in this
            process get (but not in other processes). A value overwritten,
            deleted or expired in Redis is noticed on the next read.

    Raises:
        ValueError: When ``ttl`` is not positive or ``local_cache_size`` is
            negative.

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
        local_cache_size: int = 0,
    ) -> None:
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be a positive number of seconds")
        if local_cache_size < 0:
            raise ValueError("local_cache_size must not be negative")
        self._redis = client
        self._prefix = prefix
        self._ttl = ttl
        self._track_retrievals = track_retrievals
        self._local_size = local_cache_size
        # Redis key -> (version token, entry), most recently used last.
        self._local: OrderedDict[str, tuple[bytes, CacheEntry]] = OrderedDict()
        self._local_lock = threading.Lock()

    @classmethod
    def from_url(cls, url: str, **kwargs: Any) -> Self:
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

    def _local_get(self, key: str, token: bytes | None) -> CacheEntry | None:
        """Return the kept entry of ``key`` if its version is ``token``.

        A kept entry with another version is dropped.
        """
        if not self._local_size:
            return None
        with self._local_lock:
            kept = self._local.get(key)
            if kept is None:
                return None
            if token is not None and kept[0] == token:
                self._local.move_to_end(key)
                return kept[1]
            del self._local[key]
            return None

    def _local_put(self, key: str, token: bytes | None, entry: CacheEntry) -> None:
        """Keep ``entry`` as version ``token`` of ``key``, if enabled."""
        if not self._local_size or token is None:
            return
        with self._local_lock:
            self._local[key] = (token, entry)
            self._local.move_to_end(key)
            while len(self._local) > self._local_size:
                self._local.popitem(last=False)

    def _local_drop(self, key: str) -> None:
        """Forget the kept entry of ``key``, if any."""
        if self._local_size:
            with self._local_lock:
                self._local.pop(key, None)

    def _load(self, key: str, data: bytes | str) -> tuple[bytes | None, CacheEntry]:
        """Return the token and entry in ``data``, reusing the kept object if current."""
        token = _token(data)
        entry = self._local_get(key, token)
        if entry is None:
            entry = _unpickle(data)
            self._local_put(key, token, entry)
        return token, entry

    def get(self, scope: str, params: Params) -> CacheEntry | None:
        """See `Backend.get`."""
        key = self._key(scope, params)
        entry: CacheEntry | None = None
        token: bytes | None = None
        if self._local_size:
            # Check the kept copy with a few bytes instead of the whole value.
            # A missing key gives b"", which drops the kept copy.
            token = _token(self._redis.getrange(key, 0, _HEADER_SIZE - 1))
            entry = self._local_get(key, token)
        if entry is None:
            data = self._redis.get(key)
            if data is None:
                self._local_drop(key)
                return None
            token, entry = self._load(key, data)
        if self._track_retrievals:
            entry.touch()
            # Same token: touching doesn't make other processes' copies stale.
            # xx: don't resurrect an entry deleted or expired meanwhile.
            # keepttl: reading must not extend the entry's lifetime.
            if token is None:  # value from an older version: give it a token
                token = os.urandom(_TOKEN_SIZE)
                self._local_put(key, token, entry)
            self._redis.set(key, _dump(token, entry), xx=True, keepttl=True)
        return entry

    def set(self, scope: str, entry: CacheEntry) -> None:
        """See `Backend.set`."""
        key = self._key(scope, entry.params)
        token = os.urandom(_TOKEN_SIZE)
        self._redis.set(key, _dump(token, entry), ex=self._ttl)
        self._local_put(key, token, entry)

    def delete(self, scope: str, params: Params) -> CacheEntry | None:
        """See `Backend.delete`."""
        key = self._key(scope, params)
        data = self._redis.getdel(key)
        if data is None:
            self._local_drop(key)
            return None
        _, entry = self._load(key, data)
        self._local_drop(key)
        return entry

    def discard(self, scope: str, params: Params) -> None:
        """See `Backend.discard`. A single ``DEL``: nothing is downloaded."""
        key = self._key(scope, params)
        self._redis.delete(key)
        self._local_drop(key)

    def has(self, scope: str, params: Params) -> bool:
        """See `Backend.has`."""
        return bool(self._redis.exists(self._key(scope, params)))

    def entries(self, scope: str | None = None) -> Iterator[CacheEntry]:
        """See `Backend.entries`.

        Uses ``SCAN``, so it doesn't block the server, but entries added or
        removed meanwhile may or may not be listed.
        """
        for raw_key in self._keys(scope):
            key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
            data = self._redis.get(key)
            if data is not None:  # it may have expired since the scan
                yield self._load(key, data)[1]

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
        if self._local_size:
            with self._local_lock:
                if scope is None:
                    self._local.clear()
                else:
                    start = f"{self._prefix}:{_scope_digest(scope)}:"
                    for key in [k for k in self._local if k.startswith(start)]:
                        del self._local[key]

    def __len__(self) -> int:
        return sum(1 for _ in self._keys(None))

    def __repr__(self) -> str:
        cls = f"{self.__class__.__module__}.{self.__class__.__qualname__}"
        return f"{cls}(prefix={self._prefix!r}, ttl={self._ttl!r}, local_cache_size={self._local_size!r})"


__all__ = ["RedisBackend", "params_digest"]
