import time

from cartucho.cache import Cache, CacheEntry
from cartucho.params import Params


def test_cache_set_get_pop_has_entries_and_len():
    c = Cache()

    p1 = Params([("a", 1)])
    p2 = Params([("a", 2)])

    assert not c.has(p1)
    assert p1 not in c

    c.set(p1, "one")
    c.set(p2, "two")

    assert c.get(p1) == "one"
    assert c.get(p2) == "two"
    assert c.has(p1)
    assert p1 in c

    assert len(c) == 2

    # Inspect entries and timestamps
    entries = list(c.entries())
    assert len(entries) == 2
    for e in entries:
        assert isinstance(e, CacheEntry)
        assert e.creation_time is not None
        # last_retrieved may have been set for the ones we've fetched
        assert e.result in {"one", "two"}

    # pop removes an entry and returns its result
    assert c.pop(p1) == "one"
    assert c.get(p1) is None
    assert len(c) == 1


def test_items_and_clear_and_timestamps(tmp_path):
    c = Cache()
    p = Params([("x", 10)])
    c.set(p, 100)

    entries = list(c.entries())
    assert entries and entries[0].last_retrieved is None

    # trigger retrieval to update last_retrieved
    time.sleep(0.001)
    assert c.get(p) == 100
    entries = list(c.entries())
    assert entries[0].last_retrieved is not None
    assert entries[0].last_retrieved >= entries[0].creation_time

    # items yields (Params, result)
    items = list(c.items())
    assert items == [(p, 100)]

    # save/load roundtrip
    path = tmp_path / "cache.pkl"
    c.save(path)
    loaded = Cache.load(path)
    assert loaded.get(p) == 100

    # clear removes everything
    loaded.clear()
    assert len(list(loaded.entries())) == 0
