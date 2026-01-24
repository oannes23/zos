# Story 2.4: Media Analysis

**Epic**: Observation
**Status**: 🔴 Not Started
**Estimated complexity**: Medium

## Goal

Analyze images attached to messages using a vision model, producing phenomenological descriptions that capture what it's like to see the image.

## Acceptance Criteria

- [ ] Images detected in message attachments
- [ ] Vision model called for each image
- [ ] Description stored in `media_analysis` table
- [ ] Rate limiting prevents API exhaustion
- [ ] Failures logged but don't block message storage
- [ ] Uses `vision` model profile from config

## Technical Notes

### Media Detection

```python
async def process_media(self, message: discord.Message):
    """Process media attachments in a message."""
    if not self.config.observation.vision_enabled:
        return

    for attachment in message.attachments:
        if self.is_image(attachment):
            await self.analyze_image(message.id, attachment)

def is_image(self, attachment: discord.Attachment) -> bool:
    """Check if attachment is an image."""
    image_types = {'image/png', 'image/jpeg', 'image/gif', 'image/webp'}
    return attachment.content_type in image_types
```

### Vision Analysis

```python
async def analyze_image(
    self,
    message_id: str,
    attachment: discord.Attachment,
) -> None:
    """Analyze an image with vision model."""
    try:
        # Download image
        image_data = await attachment.read()
        image_base64 = base64.b64encode(image_data).decode()

        # Call vision model
        description = await self.llm.analyze_image(
            image_base64=image_base64,
            media_type=attachment.content_type,
            prompt=VISION_PROMPT,
            model_profile="vision",
        )

        # Store analysis
        analysis = MediaAnalysis(
            id=generate_id(),
            message_id=message_id,
            media_type=attachment.content_type,
            media_url=attachment.url,
            description=description,
            analyzed_at=datetime.utcnow(),
        )
        await self.db.insert_media_analysis(analysis)

        log.info(
            "media_analyzed",
            message_id=message_id,
            media_type=attachment.content_type,
        )

    except Exception as e:
        log.warning(
            "media_analysis_failed",
            message_id=message_id,
            error=str(e),
        )
        # Don't re-raise - media analysis failure shouldn't block observation
```

### Vision Prompt

The prompt should elicit phenomenological description, not just object detection:

```python
VISION_PROMPT = """Describe this image as if you were recounting it to someone who can't see it.

Focus on:
- What draws your attention first
- The overall mood or atmosphere
- Notable details that seem meaningful
- Any text or symbols visible
- What the image might mean in a social context (meme, photo, screenshot, etc.)

Write 2-3 sentences capturing both what you see and what it feels like to look at it."""
```

### Rate Limiting

```python
class RateLimiter:
    """Simple rate limiter for API calls."""

    def __init__(self, calls_per_minute: int = 10):
        self.calls_per_minute = calls_per_minute
        self.calls = []

    async def acquire(self):
        """Wait until rate limit allows another call."""
        now = datetime.utcnow()
        minute_ago = now - timedelta(minutes=1)

        # Remove old calls
        self.calls = [t for t in self.calls if t > minute_ago]

        if len(self.calls) >= self.calls_per_minute:
            # Wait for oldest call to expire
            wait_time = (self.calls[0] - minute_ago).total_seconds()
            await asyncio.sleep(wait_time)

        self.calls.append(now)


# Usage in observation.py
self.vision_limiter = RateLimiter(calls_per_minute=10)

async def analyze_image(self, ...):
    await self.vision_limiter.acquire()
    # ... rest of analysis
```

### LLM Client Integration

```python
# src/zos/llm.py

class ModelClient:
    async def analyze_image(
        self,
        image_base64: str,
        media_type: str,
        prompt: str,
        model_profile: str = "vision",
    ) -> str:
        """Analyze an image with vision model."""
        profile = self.config.resolve_model_profile(model_profile)

        if profile.provider == "anthropic":
            return await self._anthropic_vision(
                image_base64, media_type, prompt, profile
            )
        elif profile.provider == "openai":
            return await self._openai_vision(
                image_base64, media_type, prompt, profile
            )
        else:
            raise ValueError(f"Provider {profile.provider} doesn't support vision")

    async def _anthropic_vision(
        self,
        image_base64: str,
        media_type: str,
        prompt: str,
        profile: ModelProfile,
    ) -> str:
        """Call Anthropic vision API."""
        response = await self.anthropic.messages.create(
            model=profile.model,
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
        return response.content[0].text
```

## Media Analysis Model

```python
class MediaAnalysis(BaseModel):
    id: str  # ULID
    message_id: str
    media_type: str  # MIME type
    media_url: str
    description: str
    analyzed_at: datetime

    class Config:
        from_attributes = True
```

## Configuration

```yaml
observation:
  vision_enabled: true
  vision_rate_limit_per_minute: 10
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/observation.py` | Media detection and analysis |
| `src/zos/llm.py` | Vision model integration |
| `src/zos/models.py` | MediaAnalysis model |
| `tests/test_media.py` | Media analysis tests |

## Test Cases

1. Image detection works for supported types
2. Non-images are skipped
3. Rate limiter prevents burst
4. Failures don't block message storage
5. Description stored correctly
6. Vision disabled respects config

## Definition of Done

- [ ] Images analyzed with vision model
- [ ] Descriptions are phenomenological, not clinical
- [ ] Rate limiting prevents API exhaustion
- [ ] Failures logged, not fatal

---

## Open Design Questions

### Q1: Vision Analysis Voice — First or Third Person?
The prompt asks for phenomenological description ("what it feels like to look at it"), but the example shows a somewhat detached analytical voice. When Zos later reflects on a user who shares images, should the media description feel like:
- **First-person experience**: "I see a sunset over mountains. The warmth of the colors draws me in..."
- **Third-person observation**: "The image shows a sunset over mountains. The composition emphasizes..."
- **Contextual bridging**: "They shared a sunset photograph — something contemplative in the choice..."

This affects whether media analysis feels like Zos's own perception or a tool generating metadata.

### Q2: Timing — Inline vs Queued Analysis
The story says vision analysis happens "real-time inline" during polling. But with rate limiting (10/min), a burst of image-heavy messages could delay polling significantly. Should media analysis be:
- **Inline blocking** (current) — complete before storing message, simple but blocking
- **Inline async** — store message immediately, fire-and-forget analysis, update later
- **Queued batch** — flag messages with media, process queue separately

The "real-time inline" from observation.md might need revisiting given practical rate limits.

### Q3: Custom Emoji as "Media"
Discord custom emoji in messages (`:pepe:`, server-specific stickers) aren't in `attachments` but carry visual meaning. Should custom emoji be:
- **Ignored for vision analysis** — treat as text tokens
- **Analyzed via vision** — fetch emoji image, describe it
- **Handled separately** — emoji culture tracking handles meaning (per salience spec)

This intersects with the emoji topics in salience — if we're already tracking emoji semantically, vision analysis might be redundant.

---

**Requires**: Story 2.2 (message polling), Story 4.4 (LLM client)
**Blocks**: Epic 4 (insights can reference media descriptions)
