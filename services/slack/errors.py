"""Exception types the Slack daemon recovers from.

The daemon keeps running when a single message, Slack API call, Claude call or
D-Bus call fails. These are the failures those calls raise. Programming errors
outside this set are not swallowed.
"""

import asyncio
import importlib
import sqlite3
from collections.abc import Callable

_BUILTIN_ERRORS: tuple[type[Exception], ...] = (
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    LookupError,
    AttributeError,
    asyncio.TimeoutError,
    sqlite3.Error,
)


def _optional_errors() -> tuple[type[Exception], ...]:
    """Error base classes of optional third-party clients that are installed."""
    loaders: tuple[Callable[[], type[Exception]], ...] = (
        lambda: importlib.import_module("httpx").HTTPError,
        lambda: importlib.import_module("anthropic").APIError,
        lambda: importlib.import_module("dbus_next.errors").DBusError,
    )
    found: list[type[Exception]] = []
    for load in loaders:
        try:
            found.append(load())
        except (ImportError, AttributeError):
            continue
    return tuple(found)


SLACK_ERRORS: tuple[type[Exception], ...] = _BUILTIN_ERRORS + _optional_errors()

# Also covers a missing optional module behind a lazy import.
IMPORT_OR_SLACK_ERRORS: tuple[type[Exception], ...] = (ImportError, *SLACK_ERRORS)
