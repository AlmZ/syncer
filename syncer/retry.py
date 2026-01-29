"""Retry logic with exponential backoff."""

import random
import time
from functools import wraps
from typing import Callable, TypeVar, ParamSpec

from syncer.constants import (
    RETRY_MAX_ATTEMPTS,
    RETRY_BASE_DELAY_SEC,
    RETRY_MAX_DELAY_SEC,
    get_logger,
)

logger = get_logger("retry")

P = ParamSpec("P")
T = TypeVar("T")


def retry_with_backoff(
    max_attempts: int = RETRY_MAX_ATTEMPTS,
    base_delay: float = RETRY_BASE_DELAY_SEC,
    max_delay: float = RETRY_MAX_DELAY_SEC,
    exceptions: tuple = (Exception,),
) -> Callable[[Callable[P, T]], Callable[P, T | None]]:
    """
    Decorator for retrying a function with exponential backoff.

    Args:
        max_attempts: Maximum number of retry attempts
        base_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
        exceptions: Tuple of exception types to catch and retry
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T | None]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T | None:
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_attempts:
                        logger.warning(
                            f"{func.__name__} failed after {max_attempts} attempts: {e}"
                        )
                        return None

                    # Exponential backoff with jitter
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    delay = delay * (0.5 + random.random())  # Add jitter

                    logger.debug(
                        f"{func.__name__} attempt {attempt} failed: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)

            return None

        return wrapper

    return decorator
