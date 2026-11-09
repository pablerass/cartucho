"""cartucho: cache function and method return values.

    from cartucho import ReturnCache, cached_function

    cache = ReturnCache()  # or ReturnCache(RedisBackend.from_url("redis://..."))

    @cached_function(cache)
    def get_game(game_id):
        ...
"""

from .decorators import cached_function, cached_method
from .return_cache import Cacheable, ReturnCache

__version__ = "0.1.0a1"

__all__ = ["__version__", "ReturnCache", "Cacheable", "cached_function", "cached_method"]
