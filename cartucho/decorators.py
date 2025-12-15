"""Function utilities: a decorator to memoize using a provided `Cache`.

The `cached` decorator below accepts a `Cache` instance and returns a
decorator which will use the function's signature to build a `Params`
key. If the key is present in the cache, the cached result is returned
directly; otherwise the function is executed and its return value stored
in the cache before being returned.

Usage:

    cache = Cache()

    @cached(cache)
    def compute(a, b=2):
        return a + b

    compute(1)  # computed and stored
    compute(1)  # returned from cache

"""
from __future__ import annotations

from functools import wraps
from typing import Callable

from .return_cache import ReturnCache, Cacheable
from .params import Params, params as params_decorator


def cached_function(cache: ReturnCache | None) -> Callable[[Callable], Callable]:
    """Decorator factory that memoizes calls to the decorated function.

    - `cache` should be an instance of `cartucho.return_cache.ReturnCache`.
    - The cache key is a `Params` object built from the function's
      signature and the provided call arguments. Ordering and defaults are
      preserved the same way `Params` would be constructed elsewhere in
      the project.

    The decorated function is executed only when the key is not present
    in the cache. On a cache hit the stored value is returned without
    calling the function.
    """

    def decorator(func: Callable) -> Callable:
        params_maker = params_decorator(func)
        scope = f"{func.__module__}.{func.__name__}"

        @wraps(func)
        def wrapper(*args, **kwargs):
            # If the function-level cache is None, skip caching entirely
            if cache is None:
                return func(*args, **kwargs)
            key = params_maker(*args, **kwargs)

            if "self" in key:
                # for class methods use cache_method instead
                raise TypeError("cached_function cannot be used on instance methods")

            present = cache.has(key, scope=scope)

            if present:
                cached_value = cache.get(key, scope=scope)
                return cached_value

            result = func(*args, **kwargs)
            try:
                cache.set(key, result, scope=scope)
            except TypeError:
                cache.set(key, result)
            return result

        return wrapper

    return decorator


def cached_method(func: Callable) -> Callable:
    """Decorator for instance methods of `Cacheable` classes.

    The decorated method will use the instance's `cache` attribute to
    store and retrieve results. The instance must inherit from
    `Cacheable` and have been constructed with a `Cache`.
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

        # Remove raw 'self' and append instance-specific key items
        items = [(k, v) for k, v in key.items() if k != "self"]
        key = Params(items)

        # build scope: module, class name, method name, and instance identifier
        method_module = func.__module__
        method_name = func.__name__
        class_name = self_obj.__class__.__name__
        instance_id = id(self_obj)
        scope = f"{method_module}.{class_name}.{method_name}.{instance_id}"
        # Prefer using the instance's ReturnCache; if absent, skip caching.
        rc = getattr(self_obj, "return_cache", None)
        if rc is None:
            return func(*args, **kwargs)

        try:
            present = rc.has(key, scope=scope)
        except TypeError:
            present = rc.has(key)
        if present:
            cached_value = rc.get(key, scope=scope)
            return cached_value

        result = func(*args, **kwargs)
        rc.set(key, result, scope=scope)
        return result

    return wrapper


__all__ = ["cached_function", "cached_method"]
