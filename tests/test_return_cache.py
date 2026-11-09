import pytest

from cartucho.backends import MemoryBackend
from cartucho.decorators import cached_method
from cartucho.params import Params
from cartucho.return_cache import Cacheable, ReturnCache


def test_return_cache_set_get_has_and_items():
    rc = ReturnCache()

    p1 = Params([("a", 1)])
    p2 = Params([("b", 2)])

    assert not rc.has(p1, scope="foo")
    assert rc.get(p1, "missing", scope="foo") == "missing"

    rc.set(p1, "one", scope="foo")
    assert rc.has(p1, scope="foo")
    assert not rc.has(p1)  # default scope is separate
    assert rc.get(p1, scope="foo") == "one"

    rc.set(p2, "two")
    assert rc.get(p2) == "two"

    # items/len cover every scope unless one is given
    assert set(rc.items()) == {(p1, "one"), (p2, "two")}
    assert list(rc.items(scope="foo")) == [(p1, "one")]
    assert len(rc) == 2


def test_return_cache_pop_clear_and_entries():
    rc = ReturnCache()

    p1 = Params([("x", 10)])
    p2 = Params([("y", 20)])

    rc.set(p1, 100, scope="s1")
    rc.set(p2, 200, scope="s2")

    assert rc.pop(p1, scope="s1") == 100
    assert rc.pop(p1, "gone", scope="s1") == "gone"
    assert [e.result for e in rc.entries()] == [200]

    rc.clear("s2")
    assert not rc.has(p2, scope="s2")

    rc.set(p1, 1, scope="a")
    rc.clear()
    assert len(rc) == 0


def test_return_cache_uses_given_backend():
    backend = MemoryBackend()
    rc = ReturnCache(backend)
    rc.set(Params([("k", "v")]), "val", scope="mod.func")
    assert rc.backend is backend
    assert len(backend) == 1


def test_cached_method_uses_return_cache():
    rc = ReturnCache()

    class C(Cacheable):
        def __init__(self, return_cache):
            super().__init__(return_cache=return_cache)
            self.calls = 0

        @cached_method
        def mul(self, a, b=3):
            self.calls += 1
            return a * b

    c = C(rc)
    assert c.mul(2) == 6
    assert c.mul(2) == 6
    # method should have been executed only once
    assert c.calls == 1


def test_cached_method_ignored_when_return_cache_none():
    rc = None

    class C(Cacheable):
        def __init__(self, return_cache):
            super().__init__(return_cache=return_cache)
            self.calls = 0

        @cached_method
        def mul(self, a, b=3):
            self.calls += 1
            return a * b

    c = C(rc)
    assert c.mul(2) == 6
    assert c.mul(2) == 6
    # function should have been executed twice because return_cache is None
    assert c.calls == 2


class Bitbucket(Cacheable):
    cache_id_attributes = ("url",)

    def __init__(self, url, return_cache):
        super().__init__(return_cache=return_cache)
        self.url = url
        self.calls = 0

    @cached_method
    def repo(self, name):
        self.calls += 1
        return f"{self.url}/{name}"


class BoardGameGeek(Cacheable):
    def __init__(self, return_cache):
        super().__init__(return_cache=return_cache)
        self.calls = 0

    @cached_method
    def game(self, game_id):
        self.calls += 1
        return {"id": game_id}


def test_cached_method_shared_by_instances_without_cache_id():
    rc = ReturnCache()
    first, second = BoardGameGeek(rc), BoardGameGeek(rc)
    assert first.game(13) == second.game(13) == {"id": 13}
    assert (first.calls, second.calls) == (1, 0)
    # the scope doesn't depend on the instance, so it can be reused later
    assert list(rc.backend.entries(f"{__name__}.BoardGameGeek.game"))


def test_cached_method_separated_by_cache_id_attributes():
    rc = ReturnCache()
    cloud = Bitbucket("https://bitbucket.org", rc)
    onprem = Bitbucket("https://git.example.com", rc)
    onprem_again = Bitbucket("https://git.example.com", rc)

    assert cloud.repo("r") == "https://bitbucket.org/r"
    assert onprem.repo("r") == "https://git.example.com/r"
    assert onprem_again.repo("r") == "https://git.example.com/r"
    assert (cloud.calls, onprem.calls, onprem_again.calls) == (1, 1, 0)
    assert onprem.cache_id() == "url='https://git.example.com'"


def test_cache_id_override():
    rc = ReturnCache()

    class Api(BoardGameGeek):
        def __init__(self, env, return_cache):
            super().__init__(return_cache)
            self.env = env

        def cache_id(self):
            return self.env.upper()

    dev, prod = Api("dev", rc), Api("prod", rc)
    dev.game(1)
    prod.game(1)
    assert (dev.calls, prod.calls) == (1, 1)


def test_cache_id_rejects_values_without_stable_repr():
    class Client(Cacheable):
        cache_id_attributes = ("session",)

        def __init__(self):
            super().__init__(ReturnCache())
            self.session = object()

    with pytest.raises(TypeError, match="stable repr"):
        Client().cache_id()
