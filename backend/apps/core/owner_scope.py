"""Owner-scope runtime guard for query functions.

@scoped is a runtime guard — NOT a SQL rewriter. The decorated query function
still owns the ``WHERE owner_id = %(owner_id)s`` clause in its SQL. This
decorator only ensures ``owner_id`` is present and non-None in ``params``
before the query reaches the database.

BE-D4: owner isolation enforced at three levels (service injection, composite
FKs, and this guard). Cross-owner access returns 404, never 403.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any


def scoped(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that enforces owner_id presence in the params dict.

    Raises ValueError if the wrapped function is called with a ``params``
    argument that is missing ``owner_id`` or has ``owner_id = None``.

    The ``params`` argument may be positional or keyword.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Resolve params: prefer keyword arg 'params' when present; fall back
        # to the first positional arg. This supports both the single-arg pattern
        # (query(params={...})) and the cursor-first pattern used in catalog
        # queries (query(cur, params={...})).
        if "params" in kwargs:
            params = kwargs["params"]
        elif args:
            params = args[0]
        else:
            params = {}

        if not isinstance(params, dict) or params.get("owner_id") is None:
            raise ValueError(
                f"{fn.__name__}: owner_id is required in params but was missing or None"
            )

        return fn(*args, **kwargs)

    return wrapper
