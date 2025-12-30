"""Zos-specific exceptions."""


class ZosError(Exception):
    """Base exception for all Zos errors."""

    pass


class ConfigError(ZosError):
    """Configuration-related errors."""

    pass


class DatabaseError(ZosError):
    """Database-related errors."""

    pass


class MigrationError(DatabaseError):
    """Database migration errors."""

    pass


class LayerError(ZosError):
    """Layer execution errors."""

    pass


class LayerValidationError(LayerError):
    """Layer definition validation errors."""

    pass


class BudgetExhaustedError(ZosError):
    """Raised when budget is exhausted during a run."""

    pass


class LLMError(ZosError):
    """LLM provider errors."""

    pass


class DiscordError(ZosError):
    """Discord-related errors."""

    pass
