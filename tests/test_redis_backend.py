import pickle
import subprocess
import sys

import pytest

fakeredis = pytest.importorskip("fakeredis")

from cartucho import ReturnCache, cached_function  # noqa: E402
from cartucho.entry import CacheEntry  # noqa: E402
from cartucho.params import Params  # noqa: E402
from cartucho.backends import RedisBackend  # noqa: E402
from cartucho.backends.redis import params_digest  # noqa: E402


def test_prefix_isolates_storages():
    client = fakeredis.FakeRedis()
    a = RedisBackend(client, prefix="a")
    b = RedisBackend(client, prefix="b")
    p = Params([("k", 1)])
    a.set("", CacheEntry(p, 1))
    assert not b.has("", p)
    b.clear()
    assert a.get("", p).result == 1


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
