# Story 2.5: Link Analysis

**Epic**: Observation
**Status**: 🔴 Not Started
**Estimated complexity**: Medium

## Goal

Fetch and summarize linked content, including YouTube video transcripts for videos under 30 minutes.

## Acceptance Criteria

- [ ] URLs extracted from message content
- [ ] Page content fetched (respecting robots.txt)
- [ ] Content summarized with LLM
- [ ] YouTube videos get transcript extraction
- [ ] Videos > 30 min get "TLDW" note
- [ ] Rate limiting for fetches
- [ ] Failures logged but don't block

## Technical Notes

### URL Extraction

```python
import re
from urllib.parse import urlparse

URL_PATTERN = re.compile(
    r'https?://[^\s<>"{}|\\^`\[\]]+'
)

def extract_urls(content: str) -> list[str]:
    """Extract URLs from message content."""
    return URL_PATTERN.findall(content)

def is_youtube_url(url: str) -> bool:
    """Check if URL is a YouTube video."""
    parsed = urlparse(url)
    return parsed.netloc in ('youtube.com', 'www.youtube.com', 'youtu.be')
```

### Link Processing

```python
async def process_links(self, message: discord.Message):
    """Process links in a message."""
    if not self.config.observation.link_fetch_enabled:
        return

    urls = extract_urls(message.content)
    for url in urls:
        if is_youtube_url(url):
            await self.process_youtube(message.id, url)
        else:
            await self.process_webpage(message.id, url)

async def process_webpage(self, message_id: str, url: str):
    """Fetch and summarize a webpage."""
    try:
        await self.link_limiter.acquire()

        # Fetch content
        content = await self.fetch_page(url)
        if not content:
            return

        # Summarize
        summary = await self.llm.complete(
            prompt=LINK_SUMMARY_PROMPT.format(content=content[:10000]),
            model_profile="simple",  # Summarization is straightforward
        )

        # Store
        analysis = LinkAnalysis(
            id=generate_id(),
            message_id=message_id,
            url=url,
            domain=urlparse(url).netloc,
            title=self.extract_title(content),
            summary=summary,
            analyzed_at=datetime.utcnow(),
        )
        await self.db.insert_link_analysis(analysis)

    except Exception as e:
        log.warning("link_analysis_failed", url=url, error=str(e))
```

### Page Fetching

```python
import httpx
from bs4 import BeautifulSoup

async def fetch_page(self, url: str) -> str | None:
    """Fetch page content, respecting robots.txt."""
    try:
        # Check robots.txt (simplified)
        if not await self.can_fetch(url):
            log.debug("robots_blocked", url=url)
            return None

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                follow_redirects=True,
                timeout=10.0,
                headers={"User-Agent": "Zos/1.0 (Discord bot)"},
            )
            response.raise_for_status()

            # Parse HTML and extract text
            soup = BeautifulSoup(response.text, 'html.parser')

            # Remove script/style elements
            for tag in soup(['script', 'style', 'nav', 'footer']):
                tag.decompose()

            return soup.get_text(separator='\n', strip=True)

    except Exception as e:
        log.warning("page_fetch_failed", url=url, error=str(e))
        return None
```

### YouTube Processing

```python
async def process_youtube(self, message_id: str, url: str):
    """Process a YouTube video link."""
    if not self.config.observation.youtube_transcript_enabled:
        return

    try:
        video_id = self.extract_video_id(url)
        if not video_id:
            return

        # Get video metadata
        metadata = await self.get_video_metadata(video_id)
        duration_minutes = metadata.get('duration_seconds', 0) / 60

        # Check duration threshold
        threshold = self.config.observation.video_duration_threshold_minutes
        if duration_minutes > threshold:
            summary = f"Video is {int(duration_minutes)} minutes (>{threshold}min threshold). TLDW requested but transcript not fetched."
        else:
            # Fetch transcript
            transcript = await self.fetch_transcript(video_id)
            if transcript:
                summary = await self.summarize_transcript(transcript, metadata)
            else:
                summary = "Transcript unavailable for this video."

        # Store
        analysis = LinkAnalysis(
            id=generate_id(),
            message_id=message_id,
            url=url,
            domain="youtube.com",
            title=metadata.get('title', 'Unknown'),
            summary=summary,
            content_type="video",
            duration_seconds=metadata.get('duration_seconds'),
            analyzed_at=datetime.utcnow(),
        )
        await self.db.insert_link_analysis(analysis)

    except Exception as e:
        log.warning("youtube_analysis_failed", url=url, error=str(e))

def extract_video_id(self, url: str) -> str | None:
    """Extract YouTube video ID from URL."""
    parsed = urlparse(url)
    if parsed.netloc == 'youtu.be':
        return parsed.path[1:]
    if 'v=' in parsed.query:
        # Parse query string
        from urllib.parse import parse_qs
        params = parse_qs(parsed.query)
        return params.get('v', [None])[0]
    return None
```

### Transcript Fetching

```python
from youtube_transcript_api import YouTubeTranscriptApi

async def fetch_transcript(self, video_id: str) -> str | None:
    """Fetch YouTube video transcript."""
    try:
        # This library is synchronous, run in executor
        loop = asyncio.get_event_loop()
        transcript_list = await loop.run_in_executor(
            None,
            lambda: YouTubeTranscriptApi.get_transcript(video_id)
        )

        # Combine transcript segments
        return ' '.join(segment['text'] for segment in transcript_list)

    except Exception as e:
        log.debug("transcript_unavailable", video_id=video_id, error=str(e))
        return None

async def summarize_transcript(self, transcript: str, metadata: dict) -> str:
    """Summarize a video transcript."""
    prompt = f"""Summarize this YouTube video transcript.

Title: {metadata.get('title', 'Unknown')}
Duration: {metadata.get('duration_seconds', 0) // 60} minutes

Transcript:
{transcript[:15000]}

Provide a 2-3 paragraph summary covering:
1. Main topic and key points
2. Notable claims or insights
3. Overall tone/style of the video"""

    return await self.llm.complete(
        prompt=prompt,
        model_profile="simple",
    )
```

### Link Summary Prompt

```python
LINK_SUMMARY_PROMPT = """Summarize this webpage content for someone who hasn't read it.

Content:
{content}

In 2-3 sentences, capture:
1. What this page is about
2. The key information or argument
3. Why someone might have shared it"""
```

## Link Analysis Model

```python
class LinkAnalysis(BaseModel):
    id: str  # ULID
    message_id: str
    url: str
    domain: str
    title: Optional[str] = None
    summary: str
    content_type: Optional[str] = None  # "video", "article", etc.
    duration_seconds: Optional[int] = None  # For videos
    analyzed_at: datetime

    class Config:
        from_attributes = True
```

## Configuration

```yaml
observation:
  link_fetch_enabled: true
  youtube_transcript_enabled: true
  video_duration_threshold_minutes: 30
  link_rate_limit_per_minute: 5
```

## Dependencies

Add to pyproject.toml:
```toml
"beautifulsoup4>=4.12.0",
"youtube-transcript-api>=0.6.0",
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/observation.py` | Link processing |
| `src/zos/models.py` | LinkAnalysis model |
| `tests/test_links.py` | Link analysis tests |

## Test Cases

1. URL extraction from various formats
2. YouTube URL detection
3. Transcript fetching (mocked)
4. Duration threshold respected
5. robots.txt respected
6. Failures don't block

## Definition of Done

- [ ] Links extracted and summarized
- [ ] YouTube transcripts fetched for short videos
- [ ] Long videos get TLDW note
- [ ] Rate limiting prevents abuse

---

**Requires**: Story 2.2 (message polling), Story 4.4 (LLM client)
**Blocks**: Epic 4 (insights can reference link summaries)
