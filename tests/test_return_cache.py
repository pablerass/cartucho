from cartucho.decorators import cached_method
from cartucho.params import Params
from cartucho.return_cache import ReturnCache, Cacheable


def test_return_cache_set_get_has_and_items():
    rc = ReturnCache()

    p1 = Params([("a", 1)])
    p2 = Params([("b", 2)])

    assert not rc.has(p1)

    # set in scope 'foo'
    rc.set(p1, "one", scope="foo")
    assert rc.has(p1)
    assert rc.has(p1, scope="foo")
    assert rc.get(p1, scope="foo") == "one"

    # items across all scopes yields the stored pair
    items = list(rc.items())
    assert (p1, "one") in items

    # set in default (empty) scope
    rc.set(p2, "two")
    assert rc.get(p2) == "two"
    # len sums across scopes
    assert len(rc) == 2


def test_return_cache_pop_clear_scope_and_entries():
    rc = ReturnCache()

    p1 = Params([("x", 10)])
    p2 = Params([("y", 20)])

    rc.set(p1, 100, scope="s1")
    rc.set(p2, 200, scope="s2")

    # pop removes and returns
    assert rc.pop(p1, scope="s1") == 100
    assert not rc.has(p1, scope="s1")

    # entries yields CacheEntry-like objects with results
    entries = list(rc.entries())
    # there should be one remaining entry (p2)
    assert any(e.result == 200 for e in entries)

    # clear a scope removes its entries
    rc.clear_scope("s2")
    assert not rc.has(p2, scope="s2")

    # clear wipes everything
    rc.set(p1, 1, scope="a")
    rc.clear()
    assert len(list(rc.entries())) == 0


def test_return_cache_scopes_and_contains():
    rc = ReturnCache()

    p = Params([("k", "v")])
    rc.set(p, "val", scope="mod.func")

    # scopes lists the available scopes (including empty default)
    s = rc.scopes()
    assert "mod.func" in s

    # __contains__ checks across all scopes
    assert p in rc


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
