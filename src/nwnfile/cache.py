"""Caching what an install's tables say, keyed by the install itself.

Reading a game folder's 2DAs and talk table is slow enough to be worth keeping,
and the obvious way is for whoever needs them to hold onto the result. That turns
out to be the wrong shape: the moment the folders can change, every holder has to
be told to forget — and the one that is forgotten keeps answering with the old
install's data, which looks like a display bug rather than a stale cache.

Keying on the folder instead removes the question. A different install is a
different key and therefore a different object; there is nothing to invalidate,
so there is nothing to forget to invalidate. It also means opening a second
window costs nothing, where before each one re-read everything.

The cache is bounded because the keys are paths a person chose, so there are only
ever a handful. :func:`clear` exists for tests, which build different content at
the same path within one process.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from typing import Any

#: How many distinct installs to keep. A person switches between one or two.
MAX_ENTRIES = 4

_caches: list[OrderedDict] = []


def by_install(build: Callable[..., Any]) -> Callable[..., Any]:
    """Memoize a ``(game_root, hak_dir)`` factory on its arguments.

    Not :func:`functools.lru_cache`: this keeps a registry so :func:`clear` can
    empty every one of them at once, which tests need and a long-running process
    may want after the files on disk change.
    """
    import functools

    cache: OrderedDict = OrderedDict()
    _caches.append(cache)

    @functools.wraps(build)
    def wrapper(*args, **kwargs):
        key = (args, tuple(sorted(kwargs.items())))
        if key in cache:
            cache.move_to_end(key)
            return cache[key]
        value = build(*args, **kwargs)
        cache[key] = value
        if len(cache) > MAX_ENTRIES:
            cache.popitem(last=False)
        return value

    wrapper.cache_clear = cache.clear  # type: ignore[attr-defined]
    return wrapper


def clear() -> None:
    """Empty every install-keyed cache.

    For tests, and for a caller that knows the files on disk have changed under
    it — the keys are paths, so nothing else notices a rewritten 2DA.
    """
    for cache in _caches:
        cache.clear()
