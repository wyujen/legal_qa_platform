"""Portable ownership of top-level asynchronous execution.

Windows defaults to a Proactor event loop, which psycopg's asynchronous
connections do not support.  Top-level application entry points use this
module so Windows receives a selector-backed loop while other platforms keep
the standard ``asyncio.run`` behavior.  Domain and service code remains
unaware of the process-level event-loop choice.
"""

from __future__ import annotations

import asyncio
import selectors
import sys
from collections.abc import Coroutine
from typing import Any, TypeVar

_T = TypeVar("_T")


def _windows_selector_loop() -> asyncio.AbstractEventLoop:
    """Create the selector loop required by psycopg async on Windows."""

    return asyncio.SelectorEventLoop(selectors.SelectSelector())


def run_async(main: Coroutine[Any, Any, _T]) -> _T:
    """Run one top-level coroutine with a psycopg-compatible Windows loop."""

    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=_windows_selector_loop) as runner:
            return runner.run(main)
    return asyncio.run(main)


__all__ = ["run_async"]
