"""`cached_evicts`: removing cached results made stale by a change."""
import asyncio

import pytest

from cartucho import Cacheable, ReturnCache, cached_evicts, cached_function, cached_method
from cartucho.backends import MemoryBackend, RedisBackend


def _memory():
    return ReturnCache(MemoryBackend())


def _redis():
    fakeredis = pytest.importorskip("fakeredis")
    return ReturnCache(RedisBackend(fakeredis.FakeRedis(), local_cache_size=8))


@pytest.fixture(params=[_memory, _redis], ids=["memory", "redis"])
def cache(request):
    return request.param()


class Bitbucket(Cacheable):
    """A client: one scope per server, results stored by repo name."""

    cache_id_attributes = ("url",)

    def __init__(self, url, cache, server):
        super().__init__(cache)
        self.url = url
        self.server = server  # name -> description, the "remote" data

    @cached_method(ignore=("timeout",))
    def repo(self, name, timeout=10):
        return self.server.get(name)

    @cached_evicts(repo)
    def describe(self, name, description):
        self.server[name] = description

    @cached_evicts(repo)
    async def describe_async(self, name, description):
        self.server[name] = description

    @cached_evicts(repo)
    def fail(self, name):
        self.server[name] = "partly changed"
        raise RuntimeError("failed")

    def project(self, name):
        return Repo(self, name)


class Repo(Cacheable):
    """A result that changes the client's data, holding the values of its key."""

    def __init__(self, client, name):
        super().__init__(client.return_cache)
        self.client = client
        self.url = client.url
        self.name = name

    @cached_evicts(Bitbucket.repo)
    @cached_evicts(Bitbucket.repo, name="new_name")
    def rename(self, new_name):
        server = self.client.server
        server[new_name] = server.pop(self.name)
        self.name = new_name

    @cached_evicts(Bitbucket.repo, name=lambda call: call["self"].name.upper())
    def shout(self):
        pass


def _client(cache, url="https://bitbucket.org"):
    return Bitbucket(url, cache, {"a": "first", "b": "second"})


def test_method_evicts_its_own_entry(cache):
    client = _client(cache)
    assert client.repo("a") == "first"
    assert client.repo("b") == "second"
    client.describe("a", "changed")
    assert client.repo("a", timeout=1) == "changed"
    assert client.repo("b") == "second"  # other entries stay


def test_coroutine_method_evicts(cache):
    client = _client(cache)
    assert client.repo("a") == "first"
    asyncio.run(client.describe_async("a", "changed"))
    assert client.repo("a") == "changed"


def test_evicts_when_the_change_fails(cache):
    client = _client(cache)
    client.repo("a")
    with pytest.raises(RuntimeError):
        client.fail("a")
    assert client.repo("a") == "partly changed"


def test_evicts_only_in_the_instance_scope(cache):
    cloud, onprem = _client(cache), _client(cache, url="https://git.local")
    assert onprem.repo("a") == "first"
    cloud.describe("a", "changed")
    onprem.server["a"] = "changed on the server"
    assert onprem.repo("a") == "first"  # still cached: another scope


def test_another_class_evicts_with_old_and_new_values(cache):
    client = _client(cache)
    assert client.repo("a") == "first"
    assert client.repo("c") is None
    client.project("a").rename("c")
    assert client.repo("a") is None
    assert client.repo("c") == "first"


def test_callable_source(cache):
    client = _client(cache)
    client.server["A"] = "upper"
    assert client.repo("A") == "upper"
    client.server["A"] = "changed"
    client.project("a").shout()
    assert client.repo("A") == "changed"


def test_function_eviction_and_disabled_cache():
    cache = ReturnCache()
    data = {"x": 1}

    @cached_function(cache)
    def read(name):
        return data[name]

    @cached_evicts(read)
    def write(name, value):
        data[name] = value

    assert read("x") == 1
    write("x", 2)
    assert read("x") == 2

    @cached_function(None)
    def uncached(name):
        return data[name]

    @cached_evicts(uncached)
    def write_uncached(name):
        return name

    assert write_uncached("x") == "x"  # nothing to evict, no error


def test_missing_value_fails_before_running():
    cache = ReturnCache()
    ran = []

    @cached_function(cache)
    def read(name):
        return name

    @cached_evicts(read)
    def write(other):
        ran.append(other)

    with pytest.raises(TypeError, match="can't find 'name'"):
        write("x")
    assert ran == []


def test_target_default_is_used():
    cache = ReturnCache()
    calls = []

    @cached_function(cache)
    def read(name, branch="main"):
        calls.append((name, branch))
        return name

    @cached_evicts(read)
    def write(name):
        pass

    read("x")
    write("x")
    read("x")
    assert calls == [("x", "main"), ("x", "main")]


def test_invalid_uses_fail_when_decorating():
    with pytest.raises(TypeError, match="cached_function or cached_method"):
        cached_evicts(lambda: None)

    @cached_function(ReturnCache())
    def read(name):
        return name

    with pytest.raises(TypeError, match="not part of the key"):
        cached_evicts(read, other="x")
    with pytest.raises(TypeError, match="name or a callable"):
        cached_evicts(read, name=1)  # ty: ignore[invalid-argument-type]


def test_unknown_source_of_a_method_fails_when_called(cache):
    class Writer(Cacheable):
        def __init__(self, cache):
            super().__init__(cache)

        @cached_evicts(Bitbucket.repo, other="x")
        def write(self):
            pass

    with pytest.raises(TypeError, match="not part of its key"):
        Writer(cache).write()


def test_custom_cache_id_is_only_used_on_its_own_class():
    class Custom(Cacheable):
        def cache_id(self):
            return "custom"

        @cached_method
        def read(self, name):
            return name

        @cached_evicts(read)
        def write(self, name):
            pass

    cache = ReturnCache()
    custom = Custom(cache)
    custom.read("x")
    custom.write("x")
    assert len(cache) == 0

    class Other(Cacheable):
        @cached_evicts(Custom.read)
        def write(self, name):
            pass

    # Defined in a function: the class of Custom.read can't be found by name.
    with pytest.raises(TypeError, match="can't find the class"):
        Other(cache).write("x")


def test_discard_does_not_read(monkeypatch):
    fakeredis = pytest.importorskip("fakeredis")
    backend = RedisBackend(fakeredis.FakeRedis())
    cache = ReturnCache(backend)
    client = _client(cache)
    client.repo("a")

    def fail(*args, **kwargs):
        raise AssertionError("eviction read the entry")

    monkeypatch.setattr(backend._redis, "get", fail)
    monkeypatch.setattr(backend._redis, "getdel", fail)
    client.describe("a", "changed")
    assert len(cache) == 0
