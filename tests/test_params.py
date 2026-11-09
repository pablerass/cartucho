import pytest

from cartucho.params import FrozenDict, Params, params


def test_params_dict_positional_and_defaults():
    @params
    def f(a, b=2, c=3):
        pass

    out = f(1)
    assert isinstance(out, Params)
    assert list(out.keys()) == ["a", "b", "c"]
    assert dict(out.items()) == {"a": 1, "b": 2, "c": 3}
    # hashable
    assert isinstance(hash(out), int)


def test_params_dict_args_and_kwargs():
    @params
    def g(a, *args, **kwargs):
        pass

    out = g(1, 2, 3, x=4)
    assert isinstance(out, Params)
    assert list(out.keys()) == ["a", "args", "kwargs"]
    assert out["a"] == 1
    assert out["args"] == (2, 3)
    # kwargs value is a FrozenDict
    assert isinstance(out["kwargs"], FrozenDict)
    assert dict(out["kwargs"]) == {"x": 4}
    # mapping is immutable
    with pytest.raises(TypeError):
        out["new"] = 1


def test_params_dict_missing_required_raises():
    @params
    def h(a, b):
        pass

    with pytest.raises(TypeError):
        h(1)  # missing required 'b'


def test_params_dict_keyword_only_and_defaults():
    @params
    def k(a, *, b=5, c=10):
        pass

    out = k(1, c=7)
    assert isinstance(out, Params)
    assert list(out.keys()) == ["a", "b", "c"]
    assert dict(out.items()) == {"a": 1, "b": 5, "c": 7}


def test_params_dict_preserves_signature_order():
    @params
    def sig(a, b=2, *args, c=4, **kwargs):
        pass

    out = sig(10, 20, 30, x=1)
    assert isinstance(out, Params)
    assert list(out.keys()) == ["a", "b", "args", "c", "kwargs"]
    assert out["a"] == 10
    assert out["b"] == 20
    assert out["args"] == (30,)
    assert out["c"] == 4
    assert isinstance(out["kwargs"], FrozenDict)
    assert dict(out["kwargs"]) == {"x": 1}


def test_params_tell_equal_values_of_different_types_apart():
    @params
    def f(a):
        pass

    assert f(1) == f(a=1)
    assert hash(f(1)) == hash(f(a=1))
    assert len({f(1), f(True), f(1.0)}) == 3
    assert f([1]) != f([True])
    assert f({1}) != f({1.0})
    assert f({"k": 1}) != f({"k": True})
    assert f({1: "v"}) != f({True: "v"})


def test_frozen_dict_equality_ignores_order_but_not_types():
    assert FrozenDict({"a": 1, "b": 2}) == FrozenDict({"b": 2, "a": 1})
    assert hash(FrozenDict({"a": 1, "b": 2})) == hash(FrozenDict({"b": 2, "a": 1}))
    assert FrozenDict({"a": 1}) != FrozenDict({"a": True})
    # Other mappings are compared by items only.
    assert FrozenDict({"a": 1}) == {"a": 1}


def test_params_with_unhashable_values_are_hashable_and_comparable():
    class Box:
        def __init__(self, v):
            self.v = v

        def __eq__(self, other):
            return isinstance(other, Box) and self.v == other.v

        __hash__ = None

        def __repr__(self):
            return f"Box({self.v})"

    assert Params([("a", Box(1))]) == Params([("a", Box(1))])
    assert hash(Params([("a", Box(1))])) == hash(Params([("a", Box(1))]))
    assert Params([("a", Box(1))]) != Params([("a", Box(2))])
    assert FrozenDict({"a": Box(1), "b": 2}) == FrozenDict({"b": 2, "a": Box(1)})
