"""LLM call retry with exponential backoff."""
from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")

_TRANSIENT_PATTERNS = [
    "rate limit", "rate_limit", "ratelimit",
    "too many requests", "429",
    "connection reset", "connection error",
    "timeout", "timed out",
    "server error", "internal server error", "503",
    "service unavailable",
    "overloaded",
]


def is_transient_error(error: Exception) -> bool:
    msg = str(error).lower()
    return any(p in msg for p in _TRANSIENT_PATTERNS)


def retry_with_backoff(
    fn: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> T | None:
    """Call fn, retrying on transient errors with exponential backoff.

    Returns None if all retries exhausted. Non-transient errors are re-raised.
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            last_error = e
            if not is_transient_error(e):
                raise
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                time.sleep(delay)
    return None
