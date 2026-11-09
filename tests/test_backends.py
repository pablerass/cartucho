"""Behaviour every `Backend` must have. Add new backends to the fixture."""
import time

import pytest

from cartucho.entry import CacheEntry
from cartucho.params import Params
from cartucho.backends import MemoryBackend, RedisBackend


def _memory():
    return MemoryBackend()


def _redis():
    fakeredis = pytest.importorskip("fakeredis")
    return RedisBackend(fakeredis.FakeRedis(), prefix="test")


@pytest.fixture(params=[_memory, _redis], ids=["memory", "redis"])
def backend(request):
    return request.param()


P1 = Params([("a", 1)])
P2 = Params([("a", 2)])


def test_set_get_has_delete(backend):
    assert backend.get("s", P1) is None
    assert not backend.has("s", P1)

    backend.set("s", CacheEntry(P1, "one"))
    backend.set("s", CacheEntry(P2, None))

    assert backend.get("s", P1).result == "one"
    assert backend.get("s", P2).result is None
    assert backend.has("s", P1)
    assert not backend.has("other", P1)
    assert len(backend) == 2

    assert backend.delete("s", P1).result == "one"
    assert backend.delete("s", P1) is None
    assert len(backend) == 1


def test_set_replaces(backend):
    backend.set("s", CacheEntry(P1, "old"))
    backend.set("s", CacheEntry(P1, "new"))
    assert backend.get("s", P1).result == "new"
    assert len(backend) == 1


def test_entries_and_clear_by_scope(backend):
    backend.set("mod.f", CacheEntry(P1, 1))
    backend.set("mod.f2", CacheEntry(P1, 2))  # scope names sharing a prefix
    backend.set("", CacheEntry(P2, 3))

    assert [e.result for e in backend.entries("mod.f")] == [1]
    assert sorted(e.result for e in backend.entries()) == [1, 2, 3]

    backend.clear("mod.f")
    assert not backend.has("mod.f", P1)
    assert backend.has("mod.f2", P1)

    backend.clear()
    assert len(backend) == 0
    assert list(backend.entries()) == []


def test_get_updates_last_retrieved(backend):
    backend.set("s", CacheEntry(P1, "v"))
    (entry,) = backend.entries()
    assert entry.last_retrieved is None

    time.sleep(0.001)
    backend.get("s", P1)
    (entry,) = backend.entries()
    assert entry.last_retrieved is not None
    assert entry.last_retrieved >= entry.creation_time


def test_equal_params_find_the_same_entry(backend):
    backend.set("s", CacheEntry(Params([("a", [1, 2]), ("kw", {"x": 1, "y": {2, 3}})]), "v"))
    assert backend.get("s", Params([("a", [1, 2]), ("kw", {"y": {3, 2}, "x": 1})])).result == "v"


def test_memory_save_load(tmp_path):
    backend = MemoryBackend()
    backend.set("s", CacheEntry(P1, 100))
    path = tmp_path / "cache.pkl"
    backend.save(path)
    assert MemoryBackend.load(path).get("s", P1).result == 100
