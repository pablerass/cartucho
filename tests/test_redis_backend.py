import pickle
import subprocess
import sys

import pytest

fakeredis = pytest.importorskip("fakeredis")

from cartucho import ReturnCache, cached_function
from cartucho.backends import RedisBackend
from cartucho.backends.redis import params_digest
from cartucho.entry import CacheEntry
from cartucho.params import Params


def test_prefix_isolates_storages():
    client = fakeredis.FakeRedis()
    a = RedisBackend(client, prefix="a")
    b = RedisBackend(client, prefix="b")
    p = Params([("k", 1)])
    a.set("", CacheEntry(p, 1))
    assert not b.has("", p)
    b.clear()
    entry = a.get("", p)
    assert entry is not None
    assert entry.result == 1


def test_ttl_sets_expiry_and_hits_keep_it():
    client = fakeredis.FakeRedis()
    backend = RedisBackend(client, prefix="ttl", ttl=100)
    p = Params([("k", 1)])
    backend.set("", CacheEntry(p, "v"))
    (key,) = client.scan_iter(match="ttl:*")
    assert 0 < client.ttl(key) <= 100
    backend.get("", p)
    assert 0 < client.ttl(key) <= 100

    with pytest.raises(ValueError):
        RedisBackend(client, ttl=0)


def test_cache_shared_between_processes():
    """Two caches on one server (like two processes) share results."""

    server = fakeredis.FakeServer()
    first = ReturnCache(RedisBackend(fakeredis.FakeRedis(server=server)))
    second = ReturnCache(RedisBackend(fakeredis.FakeRedis(server=server)))
    calls = []

    def get_game(game_id):
        calls.append(game_id)
        return {"id": game_id}

    assert cached_function(first)(get_game)(1) == {"id": 1}
    assert cached_function(second)(get_game)(1) == {"id": 1}
    assert calls == [1]


def test_params_digest_is_stable_across_processes():
    code = (
        "from cartucho.params import Params;"
        "from cartucho.backends.redis import params_digest;"
        "print(params_digest(Params([('s', 'abc'), ('kw', {'x': {'a', 'b', 'c'}})])))"
    )
    digests = {
        subprocess.run(
            [sys.executable, "-c", code],
            env={"PYTHONHASHSEED": seed},
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        for seed in ("1", "2", "3")
    }
    assert digests == {params_digest(Params([("s", "abc"), ("kw", {"x": {"c", "b", "a"}})]))}


def test_unpickled_params_rehash():
    p = Params([("a", "x"), ("kw", {"b": 1})])
    clone = pickle.loads(pickle.dumps(p))
    assert clone == p and hash(clone) == hash(p)


P = Params([("k", 1)])


def _hit(backend, scope="", params=P):
    entry = backend.get(scope, params)
    assert entry is not None
    return entry


def _pair(**kwargs):
    """Two backends on one server, like two processes."""
    server = fakeredis.FakeServer()
    return (
        RedisBackend(fakeredis.FakeRedis(server=server), local_cache_size=4, **kwargs),
        RedisBackend(fakeredis.FakeRedis(server=server), local_cache_size=4, **kwargs),
    )


def test_without_local_cache_hits_are_copies():
    backend = RedisBackend(fakeredis.FakeRedis())
    backend.set("", CacheEntry(P, {"a": 1}))
    assert _hit(backend).result is not _hit(backend).result


@pytest.mark.parametrize("track", [True, False])
def test_local_cache_returns_same_object(track):
    first, second = _pair(track_retrievals=track)
    stored = CacheEntry(P, {"a": 1})
    first.set("", stored)
    assert first.get("", P) is stored

    loaded = second.get("", P)
    assert loaded is not stored and loaded.result == {"a": 1}
    assert second.get("", P) is loaded
    # Touching from one process doesn't make the other's copy stale.
    assert first.get("", P) is stored


def test_local_cache_hit_skips_full_read(monkeypatch):
    backend = RedisBackend(fakeredis.FakeRedis(), local_cache_size=4, track_retrievals=False)
    backend.set("", CacheEntry(P, "v"))

    def fail(*args, **kwargs):
        raise AssertionError("full GET on a local hit")

    monkeypatch.setattr(backend._redis, "get", fail)
    assert _hit(backend).result == "v"


def test_local_cache_sees_overwrite_by_another_process():
    first, second = _pair()
    first.set("", CacheEntry(P, "old"))
    assert second.get("", P).result == "old"
    first.set("", CacheEntry(P, "new"))
    assert second.get("", P).result == "new"


def test_local_cache_sees_delete_and_clear_by_another_process():
    first, second = _pair()
    first.set("", CacheEntry(P, "v"))
    assert second.get("", P) is not None
    first.delete("", P)
    assert second.get("", P) is None

    first.set("s", CacheEntry(P, "v"))
    assert second.get("s", P) is not None
    first.clear("s")
    assert second.get("s", P) is None


def test_local_cache_sees_expiry():
    client = fakeredis.FakeRedis()
    backend = RedisBackend(client, local_cache_size=4)
    backend.set("", CacheEntry(P, "v"))
    client.flushall()  # same effect as the key expiring
    assert backend.get("", P) is None
    assert backend._local == {}


def test_local_cache_own_delete_and_clear_evict():
    backend = RedisBackend(fakeredis.FakeRedis(), local_cache_size=4)
    stored = CacheEntry(P, "v")
    backend.set("a", stored)
    backend.set("b", CacheEntry(P, "w"))
    assert backend.delete("a", P) is stored
    backend.clear("b")
    assert backend._local == {}


def test_local_cache_is_bounded_lru():
    backend = RedisBackend(fakeredis.FakeRedis(), local_cache_size=2, track_retrievals=False)
    entries = [CacheEntry(Params([("k", i)]), i) for i in range(3)]
    backend.set("", entries[0])
    backend.set("", entries[1])
    backend.get("", entries[0].params)  # 0 is now the most recent
    backend.set("", entries[2])  # evicts 1
    assert len(backend._local) == 2
    assert backend.get("", entries[0].params) is entries[0]
    assert backend.get("", entries[1].params) is not entries[1]


def test_entries_reuse_kept_objects():
    backend = RedisBackend(fakeredis.FakeRedis(), local_cache_size=4)
    stored = CacheEntry(P, "v")
    backend.set("", stored)
    assert list(backend.entries()) == [stored]
    assert next(backend.entries()) is stored


def test_reads_values_without_token():
    """Values written before tokens existed are still read, then upgraded."""
    client = fakeredis.FakeRedis()
    backend = RedisBackend(client, local_cache_size=4)
    key = backend._key("", P)
    client.set(key, pickle.dumps(CacheEntry(P, "legacy")))
    first = _hit(backend)
    assert first.result == "legacy"
    assert backend.get("", P) is first


def test_local_cache_size_must_not_be_negative():
    with pytest.raises(ValueError):
        RedisBackend(fakeredis.FakeRedis(), local_cache_size=-1)
