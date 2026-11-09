"""Cache function and method return values.

Cartucho memoizes the results of functions and methods in a `ReturnCache`,
which keeps its entries in a pluggable backend (see `cartucho.backends`).

Example:
    .. code-block:: python

        from cartucho import ReturnCache, cached_function

        cache = ReturnCache()  # or ReturnCache(RedisBackend.from_url("redis://..."))

        @cached_function(cache)
        def get_game(game_id):
            ...

        get_game(13)  # computed and stored
        get_game(13)  # returned from the cache

Attributes:
    __version__ (str): The installed version of cartucho.
"""

from .decorators import cached_function, cached_method
from .return_cache import Cacheable, ReturnCache

__version__ = "0.1.0a1"

__all__ = ["Cacheable", "ReturnCache", "__version__", "cached_function", "cached_method"]
