"""Turn function calls into hashable mappings of their parameters.

The `params` decorator transforms a function into one that, instead of
running, returns a `Params` mapping each parameter name to the value it would
receive. Keys follow the function's signature order and defaults are filled
in, so equivalent calls give equal (and equally hashed) mappings. This is what
the cache uses as the key of each entry.

Example:
    .. code-block:: python

        @params
        def f(a, b=2, *args, **kwargs):
            pass

        f(1, 3, 4, x=5)
        # Params({'a': 1, 'b': 3, 'args': (4,), 'kwargs': FrozenDict({'x': 5})})
        f(1) == f(a=1, b=2)
        # True
"""
from __future__ import annotations

import inspect
from collections.abc import Iterable, Mapping
from functools import wraps


def _freeze(value):
    """Recursively convert common mutable containers into hashable equivalents.

    Mappings become `FrozenDict`, lists and tuples become tuples, and sets
    become frozensets. Any other value is returned unchanged.

    Args:
        value: The value to convert.

    Returns:
        The converted value.
    """
    if isinstance(value, (FrozenDict, Params)):
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

    It behaves like a read-only `dict`, but can be hashed and compares equal
    to any mapping with the same items, regardless of their order. Nested
    containers in the values are frozen too.

    If some values are still unhashable after freezing, the hash falls back
    to their `repr`.

    Args:
        mapping: The mapping to copy.
    """

    def __init__(self, mapping: Mapping):
        items: tuple[tuple[object, object], ...] = tuple((k, _freeze(v)) for k, v in mapping.items())
        self._items = items
        self._map = dict(items)
        # Order-independent hash, consistent with __eq__ (which ignores order)
        try:
            self._hash = hash(frozenset(items))
        except TypeError:
            # If some values are still unhashable, fall back to hashing the repr
            self._hash = hash(frozenset((k, repr(v)) for k, v in items))

    def __getitem__(self, key):
        return self._map[key]

    def __iter__(self):
        for k, _ in self._items:
            yield k

    def __len__(self):
        return len(self._items)

    def __repr__(self):
        return f"FrozenDict({self._map!r})"

    def __reduce__(self):
        # Rebuild on unpickle so the hash is recomputed in the loading
        # process (str hashes are randomized per process).
        return (FrozenDict, (self._map,))

    def __hash__(self):
        return self._hash

    def __eq__(self, other):
        if isinstance(other, Mapping):
            return dict(self._items) == dict(other)
        return NotImplemented


class Params(Mapping):
    """Immutable, hashable mapping of parameter names to values.

    Keys keep the order they were given in (the function's signature order
    when built by `params`). Values are frozen like in `FrozenDict`. It
    compares equal to any mapping with the same items, but its hash depends
    on the order of the items.

    Args:
        items: ``(name, value)`` pairs, in signature order.
    """

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
        """Return the ``(name, value)`` pairs in order.

        Returns:
            tuple[tuple[str, object], ...]: The frozen pairs.
        """
        return tuple(self._items)

    def __repr__(self):
        return f"Params({self._map!r})"

    def __reduce__(self):
        # Rebuild on unpickle so the hash is recomputed in the loading
        # process (str hashes are randomized per process).
        return (Params, (self._items,))

    def __hash__(self):
        return self._hash

    def __eq__(self, other):
        if isinstance(other, Mapping):
            return dict(self._items) == dict(other)
        return NotImplemented


def params(func):
    """Make a function return the `Params` of each call instead of running.

    The original function body is never executed: the call is only bound to
    the signature. Every parameter appears in the result, in signature order,
    with defaults applied; a missing ``*args`` becomes ``()`` and a missing
    ``**kwargs`` becomes ``{}``.

    Args:
        func: The function whose signature is used.

    Returns:
        A function with the same signature that returns a `Params`.

    Raises:
        TypeError: When a call does not match the signature, for example
            because a required argument is missing.
    """

    sig = inspect.signature(func)

    @wraps(func)
    def wrapper(*args, **kwargs):
        bound = sig.bind_partial(*args, **kwargs)
        # apply_defaults fills in default values for parameters that have them
        bound.apply_defaults()

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


__all__ = ["FrozenDict", "Params", "params"]
