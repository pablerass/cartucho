import asyncio
import inspect
import time

import pytest

from cartucho.decorators import cached_function, cached_method
from cartucho.params import params as params_decorator
from cartucho.return_cache import Cacheable, ReturnCache


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
    scope = f"{original.__module__}.{original.__qualname__}"
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


def test_cached_none_result_is_not_recomputed():
    cache = ReturnCache()
    calls = []

    @cached_function(cache)
    def nothing(a):
        calls.append(a)

    assert nothing(1) is None
    assert nothing(1) is None
    assert calls == [1]


def test_cached_function_none_cache_disables_caching():
    calls = []

    @cached_function(None)
    def f(a):
        calls.append(a)
        return a

    assert f(1) == f(1) == 1
    assert calls == [1, 1]


def test_cached_coroutine_function_caches_awaited_result():
    cache = ReturnCache()
    calls = []

    @cached_function(cache)
    async def add(a, b=2):
        calls.append((a, b))
        await asyncio.sleep(0)
        return a + b

    assert inspect.iscoroutinefunction(add)

    async def main():
        return [await add(1), await add(1), await add(a=1), await add(1, b=3)]

    assert asyncio.run(main()) == [3, 3, 3, 4]
    assert calls == [(1, 2), (1, 3)]
    # The stored value is the result, not a coroutine.
    assert sorted(result for _, result in cache.items()) == [3, 4]


def test_cached_coroutine_function_none_cache_disables_caching():
    calls = []

    @cached_function(None)
    async def f(a):
        calls.append(a)
        return a

    async def main():
        return [await f(1), await f(1)]

    assert asyncio.run(main()) == [1, 1]
    assert calls == [1, 1]


def test_cached_coroutine_function_exception_is_not_cached():
    cache = ReturnCache()
    calls = []

    @cached_function(cache)
    async def fail(a):
        calls.append(a)
        raise ValueError(a)

    async def main():
        for _ in range(2):
            with pytest.raises(ValueError):
                await fail(1)

    asyncio.run(main())
    assert calls == [1, 1]
    assert len(cache) == 0


def test_cached_coroutine_method_uses_return_cache():
    calls = []

    class Client(Cacheable):
        @cached_method
        async def get(self, x):
            calls.append(x)
            return x * 2

    cache = ReturnCache()
    client = Client(cache)
    uncached = Client(None)

    async def main():
        return [await client.get(2), await client.get(2), await uncached.get(2), await uncached.get(2)]

    assert inspect.iscoroutinefunction(Client.get)
    assert asyncio.run(main()) == [4, 4, 4, 4]
    assert calls == [2, 2, 2]
    assert len(cache) == 1
