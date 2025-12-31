"""Configuration models for LLM providers."""

from pydantic import BaseModel, Field


class RetryConfig(BaseModel):
    """Configuration for retry behavior with exponential backoff."""

    max_attempts: int = Field(
        default=3, ge=1, description="Maximum number of retry attempts"
    )
    base_delay_seconds: float = Field(
        default=1.0, ge=0, description="Initial delay between retries in seconds"
    )
    max_delay_seconds: float = Field(
        default=60.0, ge=0, description="Maximum delay between retries in seconds"
    )
    exponential_base: float = Field(
        default=2.0, ge=1, description="Base for exponential backoff calculation"
    )
    retryable_status_codes: list[int] = Field(
        default_factory=lambda: [429, 500, 502, 503, 504],
        description="HTTP status codes that should trigger a retry",
    )


class OpenAIProviderConfig(BaseModel):
    """Configuration for OpenAI-compatible providers."""

    api_key: str = Field(
        default="", description="API key (prefer env: ZOS_LLM__OPENAI__API_KEY)"
    )
    base_url: str = Field(
        default="https://api.openai.com/v1",
        description="API base URL (change for Azure or local)",
    )
    default_model: str = Field(
        default="gpt-4o-mini", description="Default model to use"
    )
    timeout_seconds: float = Field(
        default=60.0, ge=1, description="Request timeout in seconds"
    )


class AnthropicProviderConfig(BaseModel):
    """Configuration for Anthropic Claude."""

    api_key: str = Field(
        default="", description="API key (prefer env: ZOS_LLM__ANTHROPIC__API_KEY)"
    )
    default_model: str = Field(
        default="claude-sonnet-4-20250514", description="Default model to use"
    )
    timeout_seconds: float = Field(
        default=60.0, ge=1, description="Request timeout in seconds"
    )
    max_tokens: int = Field(
        default=4096, ge=1, description="Default max tokens for completions"
    )


class OllamaProviderConfig(BaseModel):
    """Configuration for Ollama local models."""

    base_url: str = Field(
        default="http://localhost:11434", description="Ollama API base URL"
    )
    default_model: str = Field(
        default="llama3.2", description="Default model to use"
    )
    timeout_seconds: float = Field(
        default=120.0, ge=1, description="Request timeout in seconds (longer for local)"
    )


class GenericHTTPProviderConfig(BaseModel):
    """Configuration for generic HTTP LLM endpoints."""

    base_url: str = Field(..., description="API base URL")
    api_key: str | None = Field(
        default=None, description="Optional API key for authentication"
    )
    default_model: str = Field(
        default="default", description="Default model identifier"
    )
    timeout_seconds: float = Field(
        default=60.0, ge=1, description="Request timeout in seconds"
    )
    endpoint_path: str | None = Field(
        default=None,
        description="API endpoint path (default: /v1/chat/completions)",
    )
    request_template: str = Field(
        default="",
        description="Jinja2 template for request body (optional, uses OpenAI format if empty)",
    )
    response_content_path: str = Field(
        default="choices.0.message.content",
        description="JSONPath-like path to extract content from response",
    )
    response_prompt_tokens_path: str | None = Field(
        default=None,
        description="JSONPath-like path to extract prompt token count (optional)",
    )
    response_completion_tokens_path: str | None = Field(
        default=None,
        description="JSONPath-like path to extract completion token count (optional)",
    )
    response_finish_reason_path: str | None = Field(
        default=None,
        description="JSONPath-like path to extract finish reason (optional)",
    )


class LLMConfig(BaseModel):
    """Top-level LLM configuration."""

    default_provider: str = Field(
        default="openai", description="Default provider to use"
    )
    default_model: str | None = Field(
        default=None, description="Global default model (overrides provider default)"
    )
    retry: RetryConfig = Field(default_factory=RetryConfig)

    openai: OpenAIProviderConfig | None = Field(
        default=None, description="OpenAI provider configuration"
    )
    anthropic: AnthropicProviderConfig | None = Field(
        default=None, description="Anthropic provider configuration"
    )
    ollama: OllamaProviderConfig | None = Field(
        default=None, description="Ollama provider configuration"
    )
    generic: dict[str, GenericHTTPProviderConfig] = Field(
        default_factory=dict, description="Named generic HTTP provider configurations"
    )
