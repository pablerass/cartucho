import time

from cartucho.return_cache import ReturnCache
from cartucho.decorators import cached_function
from cartucho.params import params as params_decorator


def test_cached_stores_result_and_retrieves_from_cache():
    cache = ReturnCache()

    calls = {"n": 0}

    @cached_function(cache)
    def add(a, b=2):
        calls["n"] += 1
        return a + b

    # miss -> compute and store
    assert add(1) == 3
    assert calls["n"] == 1

    # inspect cache using Params built from original function
    original = add.__wrapped__
    params_maker = params_decorator(original)
    key = params_maker(1)
    # scope is composed of module and function name for functions
    scope = f"{original.__module__}.{original.__name__}"
    assert cache.get(key, scope=scope) == 3
    assert len(cache) == 1


def test_cached_hit_prevents_recompute():
    cache = ReturnCache()

    calls = {"n": 0}

    @cached_function(cache)
    def mul(a, b=3):
        calls["n"] += 1
        return a * b

    assert mul(2) == 6
    assert mul(2) == 6
    # function should have been executed only once
    assert calls["n"] == 1


def test_last_retrieved_timestamp_updated_on_hit():
    cache = ReturnCache()

    @cached_function(cache)
    def f(x):
        return x * 2

    # create entry
    assert f(5) == 10

    # find the CacheEntry via cache.entries()
    entries = list(cache.entries())
    assert len(entries) == 1
    entry = entries[0]
    # after creation, last_retrieved is still None (set at creation only)
    assert entry.creation_time is not None
    assert entry.last_retrieved is None

    # wait to ensure timestamp difference, then trigger a cache hit
    time.sleep(0.001)
    assert f(5) == 10

    # last_retrieved should now be set and greater or equal to creation_time
    entries = list(cache.entries())
    entry = entries[0]
    assert entry.last_retrieved is not None
    assert entry.last_retrieved >= entry.creation_time


def test_different_params_produce_separate_cache_entries():
    cache = ReturnCache()

    @cached_function(cache)
    def combine(a, b=0):
        return (a, b)

    assert combine(1) == (1, 0)
    assert combine(2) == (2, 0)

    # two distinct keys stored
    assert len(cache) == 2
