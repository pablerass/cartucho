"""Decorators that memoize functions and methods in a `ReturnCache`.

    cache = ReturnCache()

    @cached_function(cache)
    def compute(a, b=2):
        return a + b

    compute(1)  # computed and stored
    compute(1)  # returned from cache

The cache key is the `Params` built from the call (defaults included) and
each function or method gets its own scope inside the cache.
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from .params import Params, params as params_decorator
from .return_cache import Cacheable, ReturnCache

_MISSING = object()


def _cached_call(cache: ReturnCache, scope: str, key: Params, func: Callable, args: Any, kwargs: Any) -> Any:
    # Single lookup with a sentinel: a has()/get() pair could race with
    # expiration in shared backends, and None is a valid cached result.
    result = cache.get(key, _MISSING, scope=scope)
    if result is _MISSING:
        result = func(*args, **kwargs)
        cache.set(key, result, scope=scope)
    return result


def cached_function(cache: ReturnCache | None) -> Callable[[Callable], Callable]:
    """Memoize a function in `cache`. If `cache` is None nothing is cached."""

    def decorator(func: Callable) -> Callable:
        params_maker = params_decorator(func)
        scope = f"{func.__module__}.{func.__qualname__}"

        @wraps(func)
        def wrapper(*args, **kwargs):
            if cache is None:
                return func(*args, **kwargs)
            key = params_maker(*args, **kwargs)
            if "self" in key:
                raise TypeError("cached_function cannot be used on instance methods, use cached_method")
            return _cached_call(cache, scope, key, func, args, kwargs)

        return wrapper

    return decorator


def cached_method(func: Callable) -> Callable:
    """Memoize a method of a `Cacheable` in the instance's `return_cache`.

    The scope is the method plus the instance's `cache_id()`, so instances
    with the same id (by default, all of them) share results. If the
    instance's `return_cache` is None nothing is cached.
    """

    params_maker = params_decorator(func)

    @wraps(func)
    def wrapper(*args, **kwargs):
        key = params_maker(*args, **kwargs)
        if "self" not in key:
            raise TypeError("cached_method must be used on instance methods")

        self_obj = key["self"]
        if not isinstance(self_obj, Cacheable):
            raise TypeError("Instance is not Cacheable; cannot use cached_method")
        if self_obj.return_cache is None:
            return func(*args, **kwargs)

        key = Params((k, v) for k, v in key.items() if k != "self")
        scope = f"{func.__module__}.{func.__qualname__}"
        cache_id = self_obj.cache_id()
        if cache_id:
            scope = f"{scope}[{cache_id}]"
        return _cached_call(self_obj.return_cache, scope, key, func, args, kwargs)

    return wrapper


__all__ = ["cached_function", "cached_method"]
