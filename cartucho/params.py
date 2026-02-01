"""Small utilities for parameter-to-dictionary conversion.

This module provides the `params' decorator which transforms a
function into one that returns an ordered mapping of its parameter
names to the values supplied when called. The order of keys follows
the function's definition order. Defaults are filled when available.

Example:

    @params
    def f(a, b=2, *args, **kwargs):
        pass

    f(1, 3, 4, x=5)  # -> OrderedDict([('a', 1), ('b', 3), ('args', (4,)), ('kwargs', {'x': 5})])

"""
from __future__ import annotations

import inspect
from functools import wraps
from collections.abc import Mapping, Iterable


def _freeze(value):
    """Recursively convert common mutable containers into immutable/hashable equivalents."""
    if isinstance(value, FrozenDict) or isinstance(value, Params):
        return value
    if isinstance(value, Mapping):
        return FrozenDict(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, set):
        return frozenset(_freeze(v) for v in value)
    # leave other objects as-is
    return value


class FrozenDict(Mapping):
    """An immutable, hashable mapping that preserves insertion order.

    It behaves like a read-only dict but is hashable and compares equal to
    regular mappings with the same items.
    """

    def __init__(self, mapping: Mapping):
        items: tuple[tuple[object, object], ...] = tuple((k, _freeze(v)) for k, v in mapping.items())
        self._items = items
        self._map = dict(items)
        try:
            self._hash = hash(items)
        except TypeError:
            # If some values are still unhashable, fall back to hashing the repr
            self._hash = hash(tuple((k, repr(v)) for k, v in items))

    def __getitem__(self, key):
        return self._map[key]

    def __iter__(self):
        for k, _ in self._items:
            yield k

    def __len__(self):
        return len(self._items)

    def __repr__(self):
        return f"FrozenDict({self._map!r})"

    def __hash__(self):
        return self._hash

    def __eq__(self, other):
        if isinstance(other, Mapping):
            return dict(self._items) == dict(other)
        return NotImplemented


class Params(Mapping):
    """Immutable, hashable parameters mapping that preserves function signature order."""
    def __init__(self, items: Iterable[tuple[str, object]]):
        self._items = tuple((k, _freeze(v)) for k, v in items)
        self._map = dict(self._items)
        try:
            self._hash = hash(self._items)
        except TypeError:
            self._hash = hash(tuple((k, repr(v)) for k, v in self._items))

    def __getitem__(self, key):
        return self._map[key]

    def __iter__(self):
        for k, _ in self._items:
            yield k

    def __len__(self):
        return len(self._items)

    def items(self):
        return tuple(self._items)

    def __repr__(self):
        return f"Params({self._map!r})"

    def __hash__(self):
        return self._hash

    def __eq__(self, other):
        if isinstance(other, Mapping):
            return dict(self._items) == dict(other)
        return NotImplemented


def params(func):
    """Decorator that makes a function return an ordered mapping of its parameters.

    The returned value is an ``OrderedDict`` whose keys are the parameter
    names in the same order as the function signature and whose values are the
    corresponding bound values (including defaults when not provided).

    The decorator does not call the original function body; it only
    inspects the call and returns the parameter mapping.
    """

    sig = inspect.signature(func)

    @wraps(func)
    def wrapper(*args, **kwargs):
        bound = sig.bind_partial(*args, **kwargs)
        # apply_defaults fills in default values for parameters that have them
        try:
            bound.apply_defaults()
        except Exception:
            # In case apply_defaults isn't available or fails, fall back to manual defaults
            pass

        items = []
        for name, param in sig.parameters.items():
            if name in bound.arguments:
                value = bound.arguments[name]
            else:
                if param.kind == inspect.Parameter.VAR_POSITIONAL:
                    value = ()
                elif param.kind == inspect.Parameter.VAR_KEYWORD:
                    value = {}
                elif param.default is not inspect._empty:
                    value = param.default
                else:
                    raise TypeError(f"Missing required argument: {name}")
            items.append((name, value))

        return Params(items)

    return wrapper


__all__ = ["params", "Params", "FrozenDict"]
