"""Retry logic with exponential backoff for LLM API calls."""

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

from zos.exceptions import LLMError
from zos.llm.config import RetryConfig
from zos.logging import get_logger

logger = get_logger("llm.retry")

T = TypeVar("T")


class RetryableError(Exception):
    """Exception that should trigger a retry."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def calculate_delay(
    attempt: int,
    config: RetryConfig,
) -> float:
    """Calculate delay before next retry with exponential backoff and jitter.

    Args:
        attempt: Current attempt number (1-indexed).
        config: Retry configuration.

    Returns:
        Delay in seconds.
    """
    # Exponential backoff
    delay = config.base_delay_seconds * (config.exponential_base ** (attempt - 1))

    # Cap at max delay
    delay = min(delay, config.max_delay_seconds)

    # Add jitter (±25%)
    jitter = delay * 0.25 * (2 * random.random() - 1)
    delay += jitter

    return max(0, delay)


def is_retryable_error(error: Exception, config: RetryConfig) -> bool:
    """Check if an error should trigger a retry.

    Args:
        error: The exception to check.
        config: Retry configuration with retryable status codes.

    Returns:
        True if the error is retryable.
    """
    # Check for RetryableError with status code
    if isinstance(error, RetryableError) and error.status_code:
        return error.status_code in config.retryable_status_codes

    # Check for httpx HTTP status errors
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in config.retryable_status_codes

    # Network errors are retryable
    if isinstance(error, (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout)):
        return True

    return False


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    config: RetryConfig,
    operation_name: str = "operation",
) -> T:
    """Execute an async function with retry logic.

    Implements exponential backoff with jitter for retryable errors.

    Args:
        fn: Async function to execute.
        config: Retry configuration.
        operation_name: Name for logging purposes.

    Returns:
        Result of the function.

    Raises:
        LLMError: After all retry attempts are exhausted.
        Exception: For non-retryable errors.
    """
    last_error: Exception | None = None

    for attempt in range(1, config.max_attempts + 1):
        try:
            return await fn()
        except Exception as e:
            last_error = e

            # Check if this error is retryable
            if not is_retryable_error(e, config):
                logger.debug(f"{operation_name} failed with non-retryable error: {e}")
                raise

            # Check if we have more attempts
            if attempt >= config.max_attempts:
                logger.warning(
                    f"{operation_name} failed after {attempt} attempts: {e}"
                )
                break

            # Calculate and wait for delay
            delay = calculate_delay(attempt, config)
            logger.info(
                f"{operation_name} failed (attempt {attempt}/{config.max_attempts}), "
                f"retrying in {delay:.1f}s: {e}"
            )
            await asyncio.sleep(delay)

    # All retries exhausted
    raise LLMError(
        f"{operation_name} failed after {config.max_attempts} attempts: {last_error}"
    ) from last_error
