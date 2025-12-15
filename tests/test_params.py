import pytest

from cartucho.params import params, Params, FrozenDict


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
