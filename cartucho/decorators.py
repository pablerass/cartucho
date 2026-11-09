"""Decorators that memoize functions and methods in a `ReturnCache`.

The cache key is the `Params` built from the call (defaults included) and
each function or method gets its own scope inside the cache, named after its
module and qualified name.

Example:
    .. code-block:: python

        cache = ReturnCache()

        @cached_function(cache)
        def compute(a, b=2):
            return a + b

        compute(1)       # computed and stored
        compute(1)       # returned from the cache
        compute(a=1)     # same key: returned from the cache
        compute(1, b=3)  # different key: computed and stored
"""
from __future__ import annotations

import inspect
from collections.abc import Callable
from functools import wraps

from .params import Params
from .params import params as params_decorator
from .return_cache import Cacheable, ReturnCache

_MISSING = object()

# What a decorator needs to cache one call: the cache, the scope and the key.
# ``None`` means the call is not cached.
_Target = tuple[ReturnCache, str, Params] | None


def _scope(func: Callable) -> str:
    """Return the cache scope of ``func``: its module and qualified name."""
    # Every function has __qualname__, but not every Callable (as typed) does.
    return f"{func.__module__}.{getattr(func, '__qualname__', type(func).__qualname__)}"


def _wrap(func: Callable, resolve: Callable[..., _Target]) -> Callable:
    """Wrap ``func`` so its results are cached where ``resolve`` says.

    Coroutine functions get a coroutine wrapper that caches the awaited
    result, not the coroutine object, so it can be awaited on every call.

    Args:
        func: Function or method to memoize.
        resolve: Called with the call's arguments; returns the cache, scope
            and key to use, or ``None`` to call ``func`` without caching.

    Returns:
        The wrapper. It keeps the original name and docstring (see
        `functools.wraps`).
    """
    # Single lookup with a sentinel: a has()/get() pair could race with
    # expiration in shared backends, and None is a valid cached result.
    if inspect.iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            target = resolve(*args, **kwargs)
            if target is None:
                return await func(*args, **kwargs)
            cache, scope, key = target
            result = cache.get(key, _MISSING, scope=scope)
            if result is _MISSING:
                result = await func(*args, **kwargs)
                cache.set(key, result, scope=scope)
            return result

        return async_wrapper

    @wraps(func)
    def wrapper(*args, **kwargs):
        target = resolve(*args, **kwargs)
        if target is None:
            return func(*args, **kwargs)
        cache, scope, key = target
        result = cache.get(key, _MISSING, scope=scope)
        if result is _MISSING:
            result = func(*args, **kwargs)
            cache.set(key, result, scope=scope)
        return result

    return wrapper


def cached_function(cache: ReturnCache | None) -> Callable[[Callable], Callable]:
    """Memoize a function in ``cache``.

    Calls that bind to the same parameters (positional or keyword, with
    defaults applied) share one entry. ``None`` is a valid result and is
    cached like any other.

    Coroutine functions (``async def``) are supported: the wrapper is a
    coroutine function too and caches the awaited result.

    Args:
        cache: Cache that stores the results. If ``None``, nothing is cached
            and the function is always called, which makes caching easy to
            switch off.

    Returns:
        A decorator that wraps the function. The wrapper keeps the original
        name and docstring (see `functools.wraps`).

    Raises:
        TypeError: When the decorated function is called with a ``self``
            parameter. Use `cached_method` for instance methods.

    Example:
        .. code-block:: python

            @cached_function(cache)
            def get_game(game_id):
                return api.get(f"/games/{game_id}")
    """

    def decorator(func: Callable) -> Callable:
        params_maker = params_decorator(func)
        scope = _scope(func)

        def resolve(*args, **kwargs) -> _Target:
            if cache is None:
                return None
            key = params_maker(*args, **kwargs)
            if "self" in key:
                raise TypeError("cached_function cannot be used on instance methods, use cached_method")
            return cache, scope, key

        return _wrap(func, resolve)

    return decorator


def cached_method(func: Callable) -> Callable:
    """Memoize a method of a `Cacheable` in the instance's ``return_cache``.

    The scope is the method's qualified name plus the instance's
    `Cacheable.cache_id`, so instances with the same id (by default, all of
    them) share results. ``self`` is not part of the key. If the instance's
    ``return_cache`` is ``None``, nothing is cached.

    Coroutine methods (``async def``) are supported: the wrapper is a
    coroutine function too and caches the awaited result.

    Args:
        func: The method to memoize.

    Returns:
        The wrapped method.

    Raises:
        TypeError: When the wrapped method has no ``self`` parameter, or the
            instance is not a `Cacheable`.

    Example:
        .. code-block:: python

            class Bitbucket(Cacheable):
                cache_id_attributes = ("url",)

                def __init__(self, url, return_cache=None):
                    super().__init__(return_cache)
                    self.url = url

                @cached_method
                def repo(self, name):
                    ...
    """

    params_maker = params_decorator(func)

    def resolve(*args, **kwargs) -> _Target:
        key = params_maker(*args, **kwargs)
        if "self" not in key:
            raise TypeError("cached_method must be used on instance methods")

        self_obj = key["self"]
        if not isinstance(self_obj, Cacheable):
            raise TypeError("Instance is not Cacheable; cannot use cached_method")
        if self_obj.return_cache is None:
            return None

        key = Params((k, v) for k, v in key.items() if k != "self")
        scope = _scope(func)
        cache_id = self_obj.cache_id()
        if cache_id:
            scope = f"{scope}[{cache_id}]"
        return self_obj.return_cache, scope, key

    return _wrap(func, resolve)


__all__ = ["cached_function", "cached_method"]
