"""Generic HTTP LLM provider for arbitrary REST APIs."""

from typing import Any

import httpx
import jinja2

from zos.exceptions import LLMError
from zos.llm.config import GenericHTTPProviderConfig
from zos.llm.provider import LLMProvider, LLMResponse, Message
from zos.llm.retry import RetryableError
from zos.logging import get_logger

logger = get_logger("llm.generic")


def extract_path(data: dict[str, Any], path: str) -> Any:
    """Extract a value from nested dict using dot notation.

    Supports array indexing with numeric keys.

    Args:
        data: The data to extract from.
        path: Dot-separated path (e.g., "choices.0.message.content").

    Returns:
        The extracted value.

    Raises:
        KeyError: If path not found.
        IndexError: If array index out of bounds.
    """
    current = data
    for key in path.split("."):
        if isinstance(current, list):
            current = current[int(key)]
        elif isinstance(current, dict):
            current = current[key]
        else:
            raise KeyError(f"Cannot traverse into {type(current)} at key {key}")
    return current


class GenericHTTPProvider(LLMProvider):
    """Generic HTTP LLM provider.

    Allows connecting to arbitrary REST APIs using Jinja2 templates
    for request formatting and path-based response extraction.

    This is useful for:
    - Custom/internal LLM APIs
    - APIs with non-standard formats
    - Testing with mock servers
    """

    def __init__(self, config: GenericHTTPProviderConfig, provider_name: str) -> None:
        """Initialize the generic HTTP provider.

        Args:
            config: Provider configuration with templates.
            provider_name: Name to identify this provider instance.
        """
        self.config = config
        self._provider_name = provider_name
        self._client: httpx.AsyncClient | None = None
        self._jinja_env = jinja2.Environment(
            autoescape=False,
            undefined=jinja2.StrictUndefined,
        )

    @property
    def name(self) -> str:
        return self._provider_name

    @property
    def default_model(self) -> str:
        return self.config.default_model

    def is_available(self) -> bool:
        """Check if provider is configured."""
        return bool(self.config.base_url)

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if self.config.api_key:
                headers["Authorization"] = f"Bearer {self.config.api_key}"

            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                headers=headers,
                timeout=httpx.Timeout(self.config.timeout_seconds),
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _render_request_body(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int,
        temperature: float,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Render the request body using Jinja2 template.

        Args:
            messages: List of conversation messages.
            model: Model to use.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.
            **kwargs: Additional options.

        Returns:
            Rendered request body as dict.

        Raises:
            LLMError: On template rendering errors.
        """
        # Build message list
        msg_list = [
            {"role": m.role.value, "content": m.content}
            for m in messages
        ]

        # If no template, use OpenAI-compatible format
        if not self.config.request_template:
            body: dict[str, Any] = {
                "model": model,
                "messages": msg_list,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            body.update(kwargs)
            return body

        # Build template context
        context = {
            "model": model,
            "messages": msg_list,
            "max_tokens": max_tokens,
            "temperature": temperature,
            **kwargs,
        }

        try:
            template = self._jinja_env.from_string(self.config.request_template)
            rendered = template.render(**context)
            # Parse the rendered JSON
            import json
            return json.loads(rendered)
        except jinja2.TemplateError as e:
            raise LLMError(f"Failed to render request template: {e}") from e
        except Exception as e:
            raise LLMError(f"Failed to parse rendered request body: {e}") from e

    async def complete(
        self,
        messages: list[Message],
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion from the generic HTTP endpoint.

        Args:
            messages: List of conversation messages.
            model: Model to use (None = provider default).
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.
            **kwargs: Additional API options (passed to template).

        Returns:
            LLMResponse with content and token counts.

        Raises:
            LLMError: On API errors.
        """
        model = model or self.config.default_model
        client = self._get_client()

        # Render request body using template
        request_body = self._render_request_body(
            messages, model, max_tokens, temperature, **kwargs
        )

        # Determine endpoint path
        endpoint = self.config.endpoint_path or "/v1/chat/completions"

        try:
            response = await client.post(endpoint, json=request_body)

            # Handle error responses
            if response.status_code >= 400:
                error_body = response.text
                if response.status_code in (429, 500, 502, 503, 504):
                    raise RetryableError(
                        f"Generic API error {response.status_code}: {error_body}",
                        status_code=response.status_code,
                    )
                raise LLMError(f"Generic API error {response.status_code}: {error_body}")

            data = response.json()

        except httpx.HTTPStatusError as e:
            if e.response.status_code in (429, 500, 502, 503, 504):
                raise RetryableError(
                    f"Generic API error {e.response.status_code}",
                    status_code=e.response.status_code,
                ) from e
            raise LLMError(f"Generic API error: {e}") from e
        except httpx.RequestError as e:
            raise LLMError(f"Generic API request failed: {e}") from e

        # Extract response content using path
        try:
            content = extract_path(data, self.config.response_content_path)
            if not isinstance(content, str):
                content = str(content)

            # Try to extract token counts (optional)
            prompt_tokens = 0
            completion_tokens = 0
            finish_reason = "stop"

            if self.config.response_prompt_tokens_path:
                try:
                    prompt_tokens = int(
                        extract_path(data, self.config.response_prompt_tokens_path)
                    )
                except (KeyError, IndexError, ValueError):
                    pass

            if self.config.response_completion_tokens_path:
                try:
                    completion_tokens = int(
                        extract_path(data, self.config.response_completion_tokens_path)
                    )
                except (KeyError, IndexError, ValueError):
                    pass

            if self.config.response_finish_reason_path:
                try:
                    finish_reason = str(
                        extract_path(data, self.config.response_finish_reason_path)
                    )
                except (KeyError, IndexError, ValueError):
                    pass

            return LLMResponse(
                content=content,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                finish_reason=finish_reason,
                model=model,
                raw_response=data,
            )
        except (KeyError, IndexError) as e:
            raise LLMError(
                f"Failed to extract content from response using path "
                f"'{self.config.response_content_path}': {e}"
            ) from e

    def estimate_cost(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float | None:
        """Estimate cost in USD.

        Generic providers don't have known pricing, so this always returns None.

        Args:
            model: Model identifier (ignored).
            prompt_tokens: Input token count (ignored).
            completion_tokens: Output token count (ignored).

        Returns:
            None (pricing unknown for generic endpoints).
        """
        return None
