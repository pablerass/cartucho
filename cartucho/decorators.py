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

Both decorators accept ``key`` or ``ignore`` to choose which parameters make
up the key (see `cached_function`). `cached_evicts` marks functions or
methods that change data, so the cached results they make stale are removed.
"""
from __future__ import annotations

import asyncio
import inspect
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from functools import wraps
from typing import Any

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


@dataclass
class _Cached:
    """What `cached_evicts` needs to rebuild the keys of a cached function or method.

    Attached to the wrappers made by `cached_function` and `cached_method`.
    """

    func: Callable
    scope: str
    names: tuple[str, ...]
    method: bool
    cache: ReturnCache | None = None  # functions only; methods use the instance's
    defaults: dict[str, Any] = field(default_factory=dict)
    owner: type | None = None  # class of a method, found on first use

    def __post_init__(self) -> None:
        for name, param in inspect.signature(self.func).parameters.items():
            if name not in self.names:
                continue
            if param.kind == inspect.Parameter.VAR_POSITIONAL:
                self.defaults[name] = ()
            elif param.kind == inspect.Parameter.VAR_KEYWORD:
                self.defaults[name] = {}
            elif param.default is not inspect.Parameter.empty:
                self.defaults[name] = param.default


_CACHED_ATTRIBUTE = "__cartucho_cached__"


def _cached_of(target: Any) -> _Cached | None:
    """Return the `_Cached` of a decorated function, through other wrappers."""
    while target is not None:
        cached = getattr(target, _CACHED_ATTRIBUTE, None)
        if isinstance(cached, _Cached):
            return cached
        target = getattr(target, "__wrapped__", None)
    return None


def _names(value: Iterable[str] | None, option: str) -> tuple[str, ...] | None:
    """Return ``value`` as a tuple of parameter names, refusing a bare string."""
    if value is None:
        return None
    if isinstance(value, str):
        # key="name" would otherwise be read as ("n", "a", "m", "e").
        raise TypeError(f"{option} must be a list of parameter names, not a string: use ({value!r},)")
    names = tuple(value)
    if not all(isinstance(name, str) for name in names):
        raise TypeError(f"{option} must contain parameter names (strings)")
    return names


def _key_names(
    func: Callable,
    key: Iterable[str] | None,
    ignore: Iterable[str] | None,
    exclude: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Return the names of the parameters of ``func`` that make up its cache key.

    ``key`` and ``ignore`` are two ways of saying the same thing and are
    resolved here, once, to a single tuple: the rest of the code only knows
    the resulting names.

    Args:
        func: The decorated function.
        key: Parameters to include, or ``None``.
        ignore: Parameters to leave out, or ``None``.
        exclude: Parameters that are never part of the key and can't be
            named in ``key`` or ``ignore`` (``self`` for methods).

    Returns:
        The key parameters, in signature order.

    Raises:
        TypeError: When both ``key`` and ``ignore`` are given, or they name a
            parameter that ``func`` doesn't have or that is in ``exclude``.
    """
    key_names = _names(key, "key")
    ignore_names = _names(ignore, "ignore")
    if key_names is not None and ignore_names is not None:
        raise TypeError("pass either key or ignore, not both")

    available = [name for name in inspect.signature(func).parameters if name not in exclude]
    for option, names in (("key", key_names), ("ignore", ignore_names)):
        for name in names or ():
            if name in exclude:
                raise TypeError(f"{option} cannot name {name!r}: it is never part of the key")
            if name not in available:
                raise TypeError(f"{option} names {name!r}, which is not a parameter of {_scope(func)}")

    if key_names is not None:
        return tuple(name for name in available if name in key_names)
    return tuple(name for name in available if name not in (ignore_names or ()))


def _select(params: Params, names: tuple[str, ...]) -> Params:
    """Return the `Params` with only ``names``, keeping their order."""
    return Params((name, value) for name, value in params.items() if name in names)


def _wrap(func: Callable, resolve: Callable[..., _Target]) -> Callable:
    """Wrap ``func`` so its results are cached where ``resolve`` says.

    Coroutine functions get a coroutine wrapper that caches the awaited
    result, not the coroutine object, so it can be awaited on every call.
    Concurrent calls that miss the cache with the same arguments share one
    run of the coroutine instead of starting one each.

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
        # Runs of func not finished yet, by event loop, cache, scope and key.
        running: dict[tuple, asyncio.Task] = {}

        async def compute(cache: ReturnCache, scope: str, key: Params, args, kwargs):
            result = await func(*args, **kwargs)
            cache.set(key, result, scope=scope)
            return result

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            target = resolve(*args, **kwargs)
            if target is None:
                return await func(*args, **kwargs)
            cache, scope, key = target
            result = cache.get(key, _MISSING, scope=scope)
            if result is not _MISSING:
                return result

            run_key = (asyncio.get_running_loop(), cache, scope, key)
            task = running.get(run_key)
            if task is None:
                task = asyncio.ensure_future(compute(cache, scope, key, args, kwargs))
                running[run_key] = task

                def done(task: asyncio.Task) -> None:
                    running.pop(run_key, None)
                    if not task.cancelled():
                        task.exception()  # retrieved, even if every caller was cancelled

                task.add_done_callback(done)
            # Shielded: a caller being cancelled doesn't cancel the run others await.
            return await asyncio.shield(task)

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


def cached_function(
    cache: ReturnCache | None,
    *,
    key: Iterable[str] | None = None,
    ignore: Iterable[str] | None = None,
) -> Callable[[Callable], Callable]:
    """Memoize a function in ``cache``.

    Calls that bind to the same parameters (positional or keyword, with
    defaults applied) share one entry. ``None`` is a valid result and is
    cached like any other.

    Arguments are compared by value and type, so ``f(1)`` and ``f(True)``
    are separate entries.

    By default every parameter is part of the key. To leave some out, such
    as a timeout, a session or a logger, pass **either** ``key`` (the
    parameters to use) **or** ``ignore`` (the parameters to leave out),
    never both. Either way the result is a fixed list of key parameters,
    checked when the function is decorated. Calls that differ only in
    parameters left out of the key share one entry, so only leave out
    parameters that don't change the result. Prefer ``ignore`` when only a
    few parameters must be left out: a parameter added to the function
    later is then part of the key unless you say otherwise. ``*args`` and
    ``**kwargs`` are included or left out as a whole, by their name.

    Coroutine functions (``async def``) are supported: the wrapper is a
    coroutine function too and caches the awaited result. Concurrent calls
    with the same arguments share a single run.

    Args:
        cache: Cache that stores the results. If ``None``, nothing is cached
            and the function is always called, which makes caching easy to
            switch off.
        key: Names of the parameters that make up the key. Can't be used
            with ``ignore``.
        ignore: Names of the parameters left out of the key. Can't be used
            with ``key``.

    Returns:
        A decorator that wraps the function. The wrapper keeps the original
        name and docstring (see `functools.wraps`).

    Raises:
        TypeError: When decorating, if both ``key`` and ``ignore`` are given
            or they name a parameter the function doesn't have. When the
            decorated function is called with a ``self`` parameter: use
            `cached_method` for instance methods.

    Example:
        .. code-block:: python

            @cached_function(cache, ignore=("timeout",))
            def get_game(game_id, timeout=10):
                return api.get(f"/games/{game_id}", timeout=timeout)
    """

    def decorator(func: Callable) -> Callable:
        params_maker = params_decorator(func)
        scope = _scope(func)
        names = _key_names(func, key, ignore)

        def resolve(*args, **kwargs) -> _Target:
            if cache is None:
                return None
            call_params = params_maker(*args, **kwargs)
            if "self" in call_params:
                raise TypeError("cached_function cannot be used on instance methods, use cached_method")
            return cache, scope, _select(call_params, names)

        wrapper = _wrap(func, resolve)
        setattr(wrapper, _CACHED_ATTRIBUTE, _Cached(func, scope, names, method=False, cache=cache))
        return wrapper

    return decorator


def cached_method(
    func: Callable | None = None,
    *,
    key: Iterable[str] | None = None,
    ignore: Iterable[str] | None = None,
) -> Callable:
    """Memoize a method of a `Cacheable` in the instance's ``return_cache``.

    Use it bare (``@cached_method``) to put every parameter but ``self`` in
    the key, or with ``key`` or ``ignore`` (``@cached_method(ignore=...)``)
    to choose them, as described in `cached_function`. ``self`` can't be
    named in either.

    The scope is the method's qualified name plus the instance's
    `Cacheable.cache_id`, so instances with the same id (by default, all of
    them) share results. ``self`` is not part of the key. If the instance's
    ``return_cache`` is ``None``, nothing is cached.

    Coroutine methods (``async def``) are supported: the wrapper is a
    coroutine function too and caches the awaited result. Concurrent calls
    with the same arguments share a single run.

    Args:
        func: The method to memoize. Omitted when called with options.
        key: Names of the parameters that make up the key. Can't be used
            with ``ignore``.
        ignore: Names of the parameters left out of the key. Can't be used
            with ``key``.

    Returns:
        The wrapped method, or a decorator when called with options.

    Raises:
        TypeError: When decorating, if both ``key`` and ``ignore`` are given
            or they name ``self`` or a parameter the method doesn't have.
            When called, if the method has no ``self`` parameter or the
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

                @cached_method(ignore=("page_size",))
                def commits(self, repo, page_size=100):
                    ...
    """

    if func is None:
        return lambda f: cached_method(f, key=key, ignore=ignore)

    params_maker = params_decorator(func)
    names = _key_names(func, key, ignore, exclude=("self",))
    base_scope = _scope(func)

    def resolve(*args, **kwargs) -> _Target:
        call_params = params_maker(*args, **kwargs)
        if "self" not in call_params:
            raise TypeError("cached_method must be used on instance methods")

        self_obj = call_params["self"]
        if not isinstance(self_obj, Cacheable):
            raise TypeError("Instance is not Cacheable; cannot use cached_method")
        if self_obj.return_cache is None:
            return None

        scope = base_scope
        cache_id = self_obj.cache_id()
        if cache_id:
            scope = f"{scope}[{cache_id}]"
        return self_obj.return_cache, scope, _select(call_params, names)

    wrapper = _wrap(func, resolve)
    setattr(wrapper, _CACHED_ATTRIBUTE, _Cached(func, base_scope, names, method=True))
    return wrapper


_Source = str | Callable[[Params], Any]


def _owner_class(cached: _Cached) -> type | None:
    """Return the class defining a cached method, found from its qualified name."""
    if cached.owner is None:
        *path, _ = getattr(cached.func, "__qualname__", "").split(".")
        if path and "<locals>" not in path:
            obj: Any = sys.modules.get(cached.func.__module__)
            for part in path:
                obj = getattr(obj, part, None)
            if isinstance(obj, type):
                cached.owner = obj
    return cached.owner


def _defines(cls: type, cached: _Cached) -> bool:
    """Return whether ``cls`` (or a base) has the cached method of ``cached``."""
    return _cached_of(getattr(cls, getattr(cached.func, "__name__", ""), None)) is cached


class _Lookup:
    """Finds the values of a key from one call to the decorated function.

    Args:
        call: `Params` of the call, ``self`` included.
        sources: The ``sources`` given to `cached_evicts`.
        target: Name of the cached function, for error messages.
    """

    _MISSING = object()

    def __init__(self, call: Params, sources: Mapping[str, _Source], target: str) -> None:
        self.call = call
        self.self_obj = call.get("self")
        self.sources = sources
        self.target = target

    def _argument(self, name: str) -> Any:
        if name != "self" and name in self.call:
            return self.call[name]
        return self._MISSING

    def _attribute(self, name: str) -> Any:
        return getattr(self.self_obj, name, self._MISSING) if self.self_obj is not None else self._MISSING

    def value(self, name: str, attributes_first: bool, default: Any = _MISSING) -> Any:
        """Return the value of ``name``.

        Raises:
            TypeError: When it can't be found and there is no ``default``.
        """
        source = self.sources.get(name)
        if callable(source):
            return source(self.call)
        if isinstance(source, str):
            name_found = source
        else:
            name_found = name
        order = (self._attribute, self._argument) if attributes_first else (self._argument, self._attribute)
        for find in order:
            value = find(name_found)
            if value is not self._MISSING:
                return value
        if default is not self._MISSING:
            return default
        raise TypeError(
            f"cached_evicts({self.target}) can't find {name_found!r} in the call arguments "
            "or the instance's attributes; map it with a keyword argument"
        )


def _eviction(cached: _Cached, sources: Mapping[str, _Source], target: str, call: Params):
    """Return the cache, scope and key that a call evicts, or ``None``."""
    lookup = _Lookup(call, sources, target)
    self_obj = lookup.self_obj

    if not cached.method:
        if cached.cache is None:
            return None
        cache, scope = cached.cache, cached.scope
    else:
        if not isinstance(self_obj, Cacheable):
            raise TypeError(f"cached_evicts({target}) must decorate a method of a Cacheable")
        owner = type(self_obj) if _defines(type(self_obj), cached) else _owner_class(cached)
        if owner is None or not issubclass(owner, Cacheable):
            raise TypeError(f"cached_evicts({target}) can't find the class that defines it")
        unknown = set(sources) - set(cached.names) - set(owner.cache_id_attributes)
        if unknown:
            raise TypeError(f"cached_evicts({target}) got values for {sorted(unknown)}, which are not part of its key")
        # The writer's cache: the cached method uses its own instance's, which
        # is the same one when, as usual, related objects share their client's.
        cache = self_obj.return_cache
        if cache is None:
            return None
        if owner.cache_id is not Cacheable.cache_id:
            # A custom cache_id can't be rebuilt from values: only use it on
            # instances of the class itself.
            if not isinstance(self_obj, owner):
                raise TypeError(
                    f"cached_evicts({target}) can't rebuild the cache id of {owner.__name__}, "
                    "which overrides cache_id(); use it from a method of that class"
                )
            cache_id = self_obj.cache_id()
        else:
            cache_id = owner.build_cache_id(lambda name: lookup.value(name, attributes_first=True))
        scope = f"{cached.scope}[{cache_id}]" if cache_id else cached.scope

    key = Params(
        (name, lookup.value(name, attributes_first=False, default=cached.defaults.get(name, _Lookup._MISSING)))
        for name in cached.names
    )
    return cache, scope, key


def cached_evicts(target: Callable, **sources: _Source) -> Callable[[Callable], Callable]:
    """Remove a cached result of ``target`` whenever the decorated function runs.

    Use it on functions and methods that change the data a cached function
    or method returns, such as an API call that renames or deletes something.
    No cached value is read: the key of ``target`` is rebuilt from the call
    and removed.

    The key is the one ``target`` would use for its own call, so each of its
    key parameters (see the ``key`` and ``ignore`` options of
    `cached_function`) gets a value, looked up by name:

    1. In ``sources``, if given (see below).
    2. In the call's arguments, then in the attributes of ``self``.
    3. In ``target``'s default for that parameter, if it has one.

    For a cached method, the scope also needs the cache id of its class
    (`Cacheable.cache_id_attributes`). Those values are looked up the other
    way round, attributes of ``self`` first, because an argument with the
    same name is usually a new value (``move(self, url)``), not the current
    one. A method of another class can evict, as long as it is a `Cacheable`
    holding the needed values (for example a ``Repo`` with the ``url`` of its
    client) and sharing the same ``return_cache``.

    Values are read **before** the decorated function runs, so a method that
    changes ``self.name`` evicts the entry of the old name. The entry is
    removed **after** it runs, also when it raises, since a failed change may
    have been applied partly. A read running at the same time may store the
    old value again right after the eviction.

    To evict several entries (e.g. the old and the new name of a rename),
    stack the decorator.

    Args:
        target: A function or method decorated with `cached_function` or
            `cached_method`.
        **sources: Where to get the value of a key parameter or cache id
            attribute with a different name: the name of an argument or
            attribute (``name="new_name"``), or a callable that receives the
            `Params` of the call (``self`` included) and returns the value.

    Returns:
        A decorator. Coroutine functions are supported.

    Raises:
        TypeError: When decorating, if ``target`` is not a cached function or
            method, or a source is neither a name nor a callable. When
            called, before running the decorated function, if a value can't
            be found or a source names something that is not part of the
            key.

    Example:
        .. code-block:: python

            class Bitbucket(Cacheable):
                cache_id_attributes = ("url",)

                @cached_method
                def repo(self, name): ...

                @cached_evicts(repo)                    # name from the arguments
                def delete_repo(self, name): ...


            class Repo(Cacheable):
                def __init__(self, client, name):
                    super().__init__(client.return_cache)
                    self.url = client.url
                    self.name = name

                @cached_evicts(Bitbucket.repo)          # url and old name from self
                @cached_evicts(Bitbucket.repo, name="new_name")
                def rename(self, new_name):
                    ...
                    self.name = new_name
    """

    cached = _cached_of(target)
    if cached is None:
        raise TypeError("cached_evicts needs a function or method decorated with cached_function or cached_method")
    for name, source in sources.items():
        if not (isinstance(source, str) or callable(source)):
            raise TypeError(f"cached_evicts source for {name!r} must be a name or a callable")
    if not cached.method:
        unknown = set(sources) - set(cached.names)
        if unknown:
            raise TypeError(f"cached_evicts got values for {sorted(unknown)}, which are not part of the key")
    target_name = _scope(cached.func)

    def decorator(func: Callable) -> Callable:
        params_maker = params_decorator(func)

        def evictions(args, kwargs):
            return _eviction(cached, sources, target_name, params_maker(*args, **kwargs))

        def evict(eviction) -> None:
            if eviction is not None:
                cache, scope, key = eviction
                cache.discard(key, scope=scope)

        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                eviction = evictions(args, kwargs)
                try:
                    return await func(*args, **kwargs)
                finally:
                    evict(eviction)

            return async_wrapper

        @wraps(func)
        def wrapper(*args, **kwargs):
            eviction = evictions(args, kwargs)
            try:
                return func(*args, **kwargs)
            finally:
                evict(eviction)

        return wrapper

    return decorator


__all__ = ["cached_evicts", "cached_function", "cached_method"]
