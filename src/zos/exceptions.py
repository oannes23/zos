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


class PipelineError(LayerError):
    """Error during pipeline execution."""

    pass


class NodeExecutionError(PipelineError):
    """Error executing a specific node."""

    def __init__(self, node_name: str, message: str) -> None:
        self.node_name = node_name
        super().__init__(f"Node '{node_name}': {message}")


class PrivacyScopeError(LayerError):
    """Privacy scope violation."""

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
