"""TopicKey dataclass for canonical topic identification."""

from dataclasses import dataclass
from enum import Enum
from typing import Self


class TopicCategory(str, Enum):
    """Categories of topic keys for budget allocation."""

    USER = "user"
    CHANNEL = "channel"
    USER_IN_CHANNEL = "user_in_channel"
    DYAD = "dyad"
    DYAD_IN_CHANNEL = "dyad_in_channel"


@dataclass(frozen=True, slots=True)
class TopicKey:
    """Canonical topic key for salience tracking.

    Immutable and hashable for use as dictionary keys and set members.

    Canonical key formats:
    - user:<user_id>
    - channel:<channel_id>
    - user_in_channel:<channel_id>:<user_id>
    - dyad:<user_a>:<user_b>  (sorted, a < b)
    - dyad_in_channel:<channel_id>:<user_a>:<user_b>
    """

    category: TopicCategory
    key: str  # Canonical string representation

    # Component IDs for queries (optional based on category)
    user_id: int | None = None
    channel_id: int | None = None
    user_a_id: int | None = None  # For dyads, always < user_b_id
    user_b_id: int | None = None

    @classmethod
    def user(cls, user_id: int) -> Self:
        """Create a user topic key."""
        return cls(
            category=TopicCategory.USER,
            key=f"user:{user_id}",
            user_id=user_id,
        )

    @classmethod
    def channel(cls, channel_id: int) -> Self:
        """Create a channel topic key."""
        return cls(
            category=TopicCategory.CHANNEL,
            key=f"channel:{channel_id}",
            channel_id=channel_id,
        )

    @classmethod
    def user_in_channel(cls, channel_id: int, user_id: int) -> Self:
        """Create a user-in-channel topic key."""
        return cls(
            category=TopicCategory.USER_IN_CHANNEL,
            key=f"user_in_channel:{channel_id}:{user_id}",
            channel_id=channel_id,
            user_id=user_id,
        )

    @classmethod
    def dyad(cls, user_a: int, user_b: int) -> Self:
        """Create a dyad topic key (sorted for canonical form)."""
        a, b = sorted([user_a, user_b])
        return cls(
            category=TopicCategory.DYAD,
            key=f"dyad:{a}:{b}",
            user_a_id=a,
            user_b_id=b,
        )

    @classmethod
    def dyad_in_channel(cls, channel_id: int, user_a: int, user_b: int) -> Self:
        """Create a dyad-in-channel topic key."""
        a, b = sorted([user_a, user_b])
        return cls(
            category=TopicCategory.DYAD_IN_CHANNEL,
            key=f"dyad_in_channel:{channel_id}:{a}:{b}",
            channel_id=channel_id,
            user_a_id=a,
            user_b_id=b,
        )

    @classmethod
    def parse(cls, key_str: str) -> Self:
        """Parse a canonical key string back into a TopicKey.

        Args:
            key_str: Canonical key string (e.g., "user:123", "dyad:100:200")

        Returns:
            Reconstructed TopicKey.

        Raises:
            ValueError: If the key format is invalid.
        """
        parts = key_str.split(":")
        if len(parts) < 2:
            raise ValueError(f"Invalid topic key format: {key_str}")

        category = parts[0]

        try:
            if category == "user":
                return cls.user(int(parts[1]))
            elif category == "channel":
                return cls.channel(int(parts[1]))
            elif category == "user_in_channel":
                return cls.user_in_channel(int(parts[1]), int(parts[2]))
            elif category == "dyad":
                return cls.dyad(int(parts[1]), int(parts[2]))
            elif category == "dyad_in_channel":
                return cls.dyad_in_channel(int(parts[1]), int(parts[2]), int(parts[3]))
            else:
                raise ValueError(f"Unknown topic category: {category}")
        except (IndexError, ValueError) as e:
            raise ValueError(f"Invalid topic key format: {key_str}") from e

    def __str__(self) -> str:
        """Return the canonical key string."""
        return self.key
