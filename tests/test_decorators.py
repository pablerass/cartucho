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


def test_cached_function_tells_equal_values_of_different_types_apart():
    cache = ReturnCache()

    @cached_function(cache)
    def kind(x):
        return type(x).__name__

    assert [kind(1), kind(True), kind(1.0), kind(1)] == ["int", "bool", "float", "int"]
    assert len(cache) == 3


def test_concurrent_coroutine_calls_share_one_run():
    cache = ReturnCache()
    calls = []

    @cached_function(cache)
    async def slow(a):
        calls.append(a)
        await asyncio.sleep(0.01)
        return a * 2

    async def main():
        return await asyncio.gather(slow(1), slow(1), slow(a=1), slow(2))

    assert asyncio.run(main()) == [2, 2, 2, 4]
    assert calls == [1, 2]


def test_cancelling_one_caller_does_not_cancel_the_shared_run():
    cache = ReturnCache()
    calls = []

    @cached_function(cache)
    async def slow(a):
        calls.append(a)
        await asyncio.sleep(0.01)
        return a

    async def main():
        first = asyncio.ensure_future(slow(1))
        second = asyncio.ensure_future(slow(1))
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        return await second

    assert asyncio.run(main()) == 1
    assert calls == [1]


def test_concurrent_coroutine_calls_share_the_exception():
    cache = ReturnCache()
    calls = []

    @cached_function(cache)
    async def fail(a):
        calls.append(a)
        await asyncio.sleep(0.01)
        raise ValueError(a)

    async def main():
        return await asyncio.gather(fail(1), fail(1), return_exceptions=True)

    results = asyncio.run(main())
    assert [type(r) for r in results] == [ValueError, ValueError]
    assert calls == [1]
    assert len(cache) == 0
    # Nothing is left running: a later call runs the function again.
    asyncio.run(main())
    assert calls == [1, 1]


# --- choosing the key parameters -------------------------------------------


def _counting(cache, **options):
    calls = []

    @cached_function(cache, **options)
    def fetch(item, timeout=10, session=None):
        calls.append((item, timeout, session))
        return item

    return fetch, calls


@pytest.mark.parametrize("options", [{"key": ("item",)}, {"ignore": ("timeout", "session")}], ids=["key", "ignore"])
def test_parameters_left_out_of_the_key_share_an_entry(options):
    cache = ReturnCache()
    fetch, calls = _counting(cache, **options)
    assert fetch(1, timeout=5) == 1
    assert fetch(1, timeout=30, session=object()) == 1
    assert fetch(item=1) == 1
    assert fetch(2) == 2
    assert len(calls) == 2
    # The stored key only has the key parameters.
    scope = f"{__name__}._counting.<locals>.fetch"
    assert [dict(k) for k, _ in cache.items(scope)] == [{"item": 1}, {"item": 2}]


def test_key_keeps_signature_order_and_defaults():
    cache = ReturnCache()

    @cached_function(cache, key=("b", "a"))
    def f(a, b=2, c=3):
        return a + b

    assert f(1) == f(1, 2) == f(a=1, b=2, c=9) == 3
    ((key, _),) = cache.items(f"{__name__}.test_key_keeps_signature_order_and_defaults.<locals>.f")
    assert list(key) == ["a", "b"]


def test_empty_key_shares_one_entry():
    fetch, calls = _counting(ReturnCache(), key=())
    fetch(1)
    assert fetch(2) == 1
    assert len(calls) == 1


def test_var_args_are_selected_by_name():
    cache = ReturnCache()
    calls = []

    @cached_function(cache, ignore=("options",))
    def f(*items, **options):
        calls.append(items)
        return sum(items)

    assert f(1, 2, verbose=True) == f(1, 2) == 3
    assert f(1, 3) == 4
    assert len(calls) == 2


@pytest.mark.parametrize(
    "options, message",
    [
        ({"key": ("item",), "ignore": ("timeout",)}, "either key or ignore"),
        ({"key": ("missing",)}, "not a parameter"),
        ({"ignore": ("missing",)}, "not a parameter"),
        ({"key": "item"}, "not a string"),
        ({"ignore": (1,)}, "strings"),
    ],
)
def test_invalid_key_options_fail_when_decorating(options, message):
    with pytest.raises(TypeError, match=message):
        _counting(ReturnCache(), **options)


class _Client(Cacheable):
    def __init__(self, cache):
        super().__init__(cache)
        self.calls = []

    @cached_method(ignore=("page_size",))
    def commits(self, repo, page_size=100):
        self.calls.append((repo, page_size))
        return repo

    @cached_method(key=("repo",))
    async def tags(self, repo, timeout=5):
        self.calls.append(repo)
        return repo

    @cached_method
    def repos(self):
        self.calls.append("repos")
        return ["a"]


def test_cached_method_with_options():
    client = _Client(ReturnCache())
    assert client.commits("a", page_size=10) == client.commits("a") == "a"
    assert asyncio.run(client.tags("a", timeout=1)) == asyncio.run(client.tags("a")) == "a"
    assert client.repos() == client.repos() == ["a"]
    assert client.calls == [("a", 10), "a", "repos"]


@pytest.mark.parametrize("options", [{"key": ("self", "repo")}, {"ignore": ("self",)}])
def test_cached_method_options_cannot_name_self(options):
    with pytest.raises(TypeError, match="never part of the key"):

        @cached_method(**options)
        def commits(self, repo): ...
