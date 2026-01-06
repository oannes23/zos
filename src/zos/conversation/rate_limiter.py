"""Rate limiting for conversation responses.

Implements per-channel rate limiting to prevent spammy behavior:
- Maximum responses per channel within a time window
- Cooldown period between responses
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from zos.logging import get_logger

if TYPE_CHECKING:
    from zos.config import RateLimitConfig

logger = get_logger("conversation.rate_limiter")


@dataclass
class ChannelRateState:
    """Rate limit state for a single channel."""

    response_times: list[datetime] = field(default_factory=list)
    last_response: datetime | None = None

    def add_response(self, timestamp: datetime | None = None) -> None:
        """Record a response at the given time."""
        if timestamp is None:
            timestamp = datetime.now(UTC)
        self.response_times.append(timestamp)
        self.last_response = timestamp

    def prune_old(self, window_seconds: int) -> None:
        """Remove response times older than the window."""
        cutoff = datetime.now(UTC).timestamp() - window_seconds
        self.response_times = [
            t for t in self.response_times if t.timestamp() > cutoff
        ]


@dataclass(frozen=True)
class RateLimitResult:
    """Result of rate limit check.

    Attributes:
        allowed: Whether the response is allowed.
        reason: Reason for denial (if not allowed).
        retry_after_seconds: Suggested wait time before retrying.
    """

    allowed: bool
    reason: str = ""
    retry_after_seconds: float = 0.0

    @classmethod
    def allow(cls) -> RateLimitResult:
        """Create an allowed result."""
        return cls(allowed=True)

    @classmethod
    def deny(cls, reason: str, retry_after: float = 0.0) -> RateLimitResult:
        """Create a denied result."""
        return cls(allowed=False, reason=reason, retry_after_seconds=retry_after)


class RateLimiter:
    """Rate limiter for conversation responses.

    Tracks response frequency per channel and enforces limits.
    Thread-safe for use in async context (single event loop).
    """

    def __init__(self, config: RateLimitConfig) -> None:
        """Initialize the rate limiter.

        Args:
            config: Rate limit configuration.
        """
        self.config = config
        self._channel_states: dict[int, ChannelRateState] = defaultdict(
            ChannelRateState
        )

    def check(self, channel_id: int) -> RateLimitResult:
        """Check if a response is allowed in the given channel.

        Args:
            channel_id: The Discord channel ID.

        Returns:
            RateLimitResult indicating whether response is allowed.
        """
        if not self.config.enabled:
            return RateLimitResult.allow()

        state = self._channel_states[channel_id]
        now = datetime.now(UTC)

        # Prune old entries
        state.prune_old(self.config.window_seconds)

        # Check cooldown
        if state.last_response:
            seconds_since_last = (now - state.last_response).total_seconds()
            if seconds_since_last < self.config.cooldown_seconds:
                retry_after = self.config.cooldown_seconds - seconds_since_last
                logger.debug(
                    f"Rate limited (cooldown): channel {channel_id}, "
                    f"retry in {retry_after:.1f}s"
                )
                return RateLimitResult.deny(
                    reason=f"cooldown ({retry_after:.1f}s remaining)",
                    retry_after=retry_after,
                )

        # Check window limit
        if len(state.response_times) >= self.config.max_responses_per_channel:
            # Calculate when the oldest response will expire
            oldest = min(state.response_times)
            retry_after = (
                oldest.timestamp()
                + self.config.window_seconds
                - now.timestamp()
            )
            logger.debug(
                f"Rate limited (window): channel {channel_id}, "
                f"{len(state.response_times)}/{self.config.max_responses_per_channel} "
                f"responses in window"
            )
            return RateLimitResult.deny(
                reason=f"rate limit ({self.config.max_responses_per_channel} "
                f"per {self.config.window_seconds}s)",
                retry_after=max(0.0, retry_after),
            )

        return RateLimitResult.allow()

    def record_response(self, channel_id: int) -> None:
        """Record that a response was sent to a channel.

        Args:
            channel_id: The Discord channel ID.
        """
        state = self._channel_states[channel_id]
        state.add_response()
        logger.debug(
            f"Recorded response: channel {channel_id}, "
            f"{len(state.response_times)} responses in window"
        )

    def get_channel_state(self, channel_id: int) -> dict[str, int | float | None]:
        """Get rate limit state for a channel (for debugging/API).

        Args:
            channel_id: The Discord channel ID.

        Returns:
            Dict with response count and time until reset.
        """
        state = self._channel_states[channel_id]
        state.prune_old(self.config.window_seconds)

        time_until_reset = None
        if state.response_times:
            oldest = min(state.response_times)
            time_until_reset = (
                oldest.timestamp()
                + self.config.window_seconds
                - datetime.now(UTC).timestamp()
            )

        return {
            "response_count": len(state.response_times),
            "max_responses": self.config.max_responses_per_channel,
            "window_seconds": self.config.window_seconds,
            "time_until_reset": time_until_reset,
        }

    def reset_channel(self, channel_id: int) -> None:
        """Reset rate limit state for a channel.

        Args:
            channel_id: The Discord channel ID.
        """
        if channel_id in self._channel_states:
            del self._channel_states[channel_id]

    def reset_all(self) -> None:
        """Reset all rate limit state."""
        self._channel_states.clear()
