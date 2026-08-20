"""LLM call retry with exponential backoff."""
from __future__ import annotations

import time
from typing import Callable, TypeVar

from onep.strategy.repair import classify_exception

T = TypeVar("T")

def is_transient_error(error: Exception) -> bool:
    return classify_exception(error).retry_lane == "transport"


def retry_with_backoff(
    fn: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> T | None:
    """Call fn, retrying on transient errors with exponential backoff.

    Returns None if all retries exhausted. Non-transient errors are re-raised.
    """
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            if not is_transient_error(e):
                raise
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                time.sleep(delay)
    return None
