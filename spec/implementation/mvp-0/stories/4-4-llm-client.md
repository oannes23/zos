# Story 4.4: LLM Client

**Epic**: Reflection
**Status**: 🔴 Not Started
**Estimated complexity**: Medium

## Goal

Implement a thin LLM client wrapper with provider adapters and model profile resolution.

## Acceptance Criteria

- [ ] Model profiles resolve to provider/model
- [ ] Anthropic adapter works
- [ ] OpenAI adapter works (optional for MVP 0)
- [ ] Usage tracking (input/output tokens)
- [ ] Rate limiting per provider
- [ ] Errors produce clear messages
- [ ] Vision calls supported

## Technical Notes

### Model Client

```python
# src/zos/llm.py
from dataclasses import dataclass
from anthropic import AsyncAnthropic
import structlog

log = structlog.get_logger()

@dataclass
class Usage:
    """Token usage from an LLM call."""
    input_tokens: int
    output_tokens: int

@dataclass
class ModelProfile:
    """Resolved model configuration."""
    provider: str
    model: str

class ModelClient:
    """Thin wrapper for LLM calls with multi-provider support."""

    def __init__(self, config: Config):
        self.config = config
        self._anthropic: AsyncAnthropic | None = None
        self._rate_limiters: dict[str, RateLimiter] = {}

    def _get_anthropic(self) -> AsyncAnthropic:
        """Lazy initialization of Anthropic client."""
        if self._anthropic is None:
            api_key = self._get_api_key('anthropic')
            self._anthropic = AsyncAnthropic(api_key=api_key)
        return self._anthropic

    def _get_api_key(self, provider: str) -> str:
        """Get API key for a provider from environment."""
        import os
        provider_config = self.config.models.providers.get(provider, {})
        env_var = provider_config.get('api_key_env', f'{provider.upper()}_API_KEY')
        key = os.environ.get(env_var)
        if not key:
            raise ValueError(f"API key not found: {env_var}")
        return key

    def resolve_profile(self, name: str) -> ModelProfile:
        """Resolve a profile name to provider/model."""
        profiles = self.config.models.profiles
        profile = profiles.get(name)

        if profile is None:
            raise ValueError(f"Unknown model profile: {name}")

        # Handle aliases (string that points to another profile)
        if isinstance(profile, str):
            return self.resolve_profile(profile)

        return ModelProfile(
            provider=profile.provider,
            model=profile.model,
        )
```

### Text Completion

```python
    async def complete(
        self,
        prompt: str,
        model_profile: str = "default",
        max_tokens: int = 500,
        temperature: float = 0.7,
    ) -> tuple[str, Usage]:
        """Complete a text prompt."""
        profile = self.resolve_profile(model_profile)

        # Rate limit
        await self._rate_limit(profile.provider)

        if profile.provider == "anthropic":
            return await self._anthropic_complete(
                prompt, profile.model, max_tokens, temperature
            )
        elif profile.provider == "openai":
            return await self._openai_complete(
                prompt, profile.model, max_tokens, temperature
            )
        else:
            raise ValueError(f"Unsupported provider: {profile.provider}")

    async def _anthropic_complete(
        self,
        prompt: str,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, Usage]:
        """Call Anthropic API."""
        client = self._get_anthropic()

        log.debug(
            "llm_call_start",
            provider="anthropic",
            model=model,
            prompt_length=len(prompt),
        )

        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )

        usage = Usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        log.debug(
            "llm_call_complete",
            provider="anthropic",
            model=model,
            tokens_in=usage.input_tokens,
            tokens_out=usage.output_tokens,
        )

        return response.content[0].text, usage
```

### Vision Calls

```python
    async def analyze_image(
        self,
        image_base64: str,
        media_type: str,
        prompt: str,
        model_profile: str = "vision",
    ) -> tuple[str, Usage]:
        """Analyze an image with vision model."""
        profile = self.resolve_profile(model_profile)

        await self._rate_limit(profile.provider)

        if profile.provider == "anthropic":
            return await self._anthropic_vision(
                image_base64, media_type, prompt, profile.model
            )
        else:
            raise ValueError(f"Provider {profile.provider} doesn't support vision")

    async def _anthropic_vision(
        self,
        image_base64: str,
        media_type: str,
        prompt: str,
        model: str,
    ) -> tuple[str, Usage]:
        """Call Anthropic vision API."""
        client = self._get_anthropic()

        response = await client.messages.create(
            model=model,
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_base64,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }],
        )

        usage = Usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        return response.content[0].text, usage
```

### Rate Limiting

```python
    async def _rate_limit(self, provider: str):
        """Apply rate limiting for a provider."""
        if provider not in self._rate_limiters:
            # Default: 50 requests per minute
            self._rate_limiters[provider] = RateLimiter(
                calls_per_minute=50
            )
        await self._rate_limiters[provider].acquire()

class RateLimiter:
    """Simple token bucket rate limiter."""

    def __init__(self, calls_per_minute: int = 50):
        self.calls_per_minute = calls_per_minute
        self.calls: list[datetime] = []
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Wait until rate limit allows another call."""
        async with self._lock:
            now = datetime.utcnow()
            minute_ago = now - timedelta(minutes=1)

            # Remove old calls
            self.calls = [t for t in self.calls if t > minute_ago]

            if len(self.calls) >= self.calls_per_minute:
                # Wait for oldest call to expire
                wait_time = (self.calls[0] - minute_ago).total_seconds()
                if wait_time > 0:
                    await asyncio.sleep(wait_time)

            self.calls.append(now)
```

### Error Handling

```python
    async def complete(self, ...):
        try:
            # ... actual call ...
        except anthropic.RateLimitError as e:
            log.warning("rate_limit_hit", provider="anthropic")
            # Wait and retry once
            await asyncio.sleep(60)
            return await self._anthropic_complete(...)
        except anthropic.APIError as e:
            log.error("api_error", provider="anthropic", error=str(e))
            raise
```

### Cost Estimation

```python
def estimate_cost(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Estimate cost in USD for a completion."""
    # Prices per 1M tokens (approximate, update as needed)
    prices = {
        'anthropic': {
            'claude-opus-4-20250514': (15.0, 75.0),     # input, output
            'claude-sonnet-4-20250514': (3.0, 15.0),
            'claude-3-5-haiku-20241022': (0.25, 1.25),
        },
    }

    provider_prices = prices.get(provider, {})
    model_prices = provider_prices.get(model, (1.0, 3.0))  # Default

    input_cost = (input_tokens / 1_000_000) * model_prices[0]
    output_cost = (output_tokens / 1_000_000) * model_prices[1]

    return input_cost + output_cost
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/llm.py` | ModelClient class |
| `tests/test_llm.py` | LLM client tests (mocked) |

## Test Cases

1. Profile resolution works
2. Alias profiles resolve
3. Unknown profile raises error
4. Anthropic adapter returns response and usage
5. Rate limiter prevents burst
6. API errors handled gracefully
7. Vision calls work

## Definition of Done

- [ ] Profiles resolve correctly
- [ ] Anthropic adapter works
- [ ] Token tracking accurate
- [ ] Rate limiting works

---

## Open Design Questions

### Q1: Cost Tracking Precision — By What Grain?
Current tracking stores `tokens_input`, `tokens_output`, `estimated_cost` per LayerRun. But a layer might call multiple LLM endpoints (e.g., vision + text completion). Should cost tracking be:
- **Per layer run** (current) — aggregate across all calls in the run
- **Per LLM call** — separate tracking for each API call
- **Per insight** — attribute cost to the insight it produced

Finer granularity helps understand what's expensive (e.g., "vision analysis is 40% of cost") but adds schema complexity.

### Q2: Provider Fallback — Automatic or Configured?
The spec mentions "offline-capable" via Ollama. If Anthropic API is down, should the client:
- **Fail fast** — if configured provider unavailable, error immediately
- **Auto-fallback** — try next provider in priority order
- **Config-driven fallback** — specify explicit fallback chain per profile

Auto-fallback is resilient but might produce inconsistent quality (Anthropic → local Ollama is a capability drop). The phenomenological question: would Zos running on degraded capability feel different? Should it know?

### Q3: Structured Output — JSON Mode vs Free-Form Parsing?
Current approach parses JSON from free-form responses via regex. Anthropic supports JSON mode with tool_use. Should we:
- **Continue free-form** (current) — flexibility, works across providers
- **Use JSON mode where available** — more reliable parsing, provider-specific
- **Hybrid** — JSON mode for strict schemas, free-form for creative content

The insight response structure (content + metrics + valence) is well-defined enough for structured extraction, but forcing JSON might constrain the LLM's thinking.

---

**Requires**: Story 1.2 (config with profiles)
**Blocks**: Stories 2.4, 2.5, 4.3 (media, links, executor use LLM)
