"""Link analysis for Zos.

This module handles fetching and summarizing linked content from messages,
including special handling for YouTube videos with transcript extraction.

Link summaries capture why someone might have shared the content - social
context matters. The goal is to understand not just what was shared, but
what it means in the conversation.

Key features:
- URL extraction from message content
- Page content fetching (respecting robots.txt)
- YouTube video handling with transcript extraction
- LLM-powered summarization
- Rate limiting for fetches
- TLDW principle: videos >30min get metadata only
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from zos.database import generate_id, link_analysis
from zos.logging import get_logger
from zos.models import ContentType, LinkAnalysis

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from zos.config import Config
    from zos.llm import ModelClient, RateLimiter

log = get_logger("links")

# URL extraction pattern - matches http/https URLs
URL_PATTERN = re.compile(r"https?://[^\s<>\"{}|\\^`\[\]]+")

# YouTube domains for detection
YOUTUBE_DOMAINS = frozenset({"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"})

# User agent for web requests
USER_AGENT = "Zos/1.0 (Discord bot; +https://github.com/jns/zos)"

# Link summary prompt - captures social context
LINK_SUMMARY_PROMPT = """Summarize this webpage content for someone who hasn't read it.

Content:
{content}

In 2-3 sentences, capture:
1. What this page is about
2. The key information or argument
3. Why someone might have shared it"""

# Video transcript summary prompt
TRANSCRIPT_SUMMARY_PROMPT = """Summarize this YouTube video transcript.

Title: {title}
Duration: {duration_minutes} minutes

Transcript:
{transcript}

Provide a 2-3 paragraph summary covering:
1. Main topic and key points
2. Notable claims or insights
3. Overall tone/style of the video"""


def extract_urls(content: str) -> list[str]:
    """Extract URLs from message content.

    Args:
        content: Message text to scan for URLs.

    Returns:
        List of URLs found in the content.
    """
    return URL_PATTERN.findall(content)


def is_youtube_url(url: str) -> bool:
    """Check if URL is a YouTube video.

    Args:
        url: URL to check.

    Returns:
        True if URL is a YouTube video link.
    """
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower() in YOUTUBE_DOMAINS
    except Exception:
        return False


def extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from URL.

    Handles various YouTube URL formats:
    - https://youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://youtube.com/embed/VIDEO_ID
    - https://youtube.com/shorts/VIDEO_ID

    Args:
        url: YouTube URL.

    Returns:
        Video ID string, or None if not found.
    """
    try:
        parsed = urlparse(url)

        # youtu.be short links
        if parsed.netloc == "youtu.be":
            # Path is /VIDEO_ID
            return parsed.path[1:].split("?")[0] if parsed.path else None

        # Standard youtube.com URLs
        if "v=" in parsed.query:
            params = parse_qs(parsed.query)
            video_ids = params.get("v")
            return video_ids[0] if video_ids else None

        # Embed or shorts URLs: /embed/VIDEO_ID or /shorts/VIDEO_ID
        path_parts = parsed.path.split("/")
        if len(path_parts) >= 3 and path_parts[1] in ("embed", "shorts", "v"):
            return path_parts[2].split("?")[0]

        return None
    except Exception:
        return None


def extract_domain(url: str) -> str:
    """Extract domain from URL.

    Args:
        url: Full URL.

    Returns:
        Domain string.
    """
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower()
    except Exception:
        return "unknown"


class LinkAnalyzer:
    """Handles link fetching, analysis, and summarization.

    This class coordinates all link analysis operations:
    - Fetching webpage content
    - Extracting YouTube transcripts
    - Summarizing content with LLM
    - Storing results in the database

    Rate limiting is applied to both web fetches and LLM calls.
    """

    def __init__(
        self,
        config: Config,
        engine: Engine,
        llm_client: ModelClient,
        link_rate_limiter: RateLimiter | None = None,
    ) -> None:
        """Initialize the link analyzer.

        Args:
            config: Application configuration.
            engine: SQLAlchemy database engine.
            llm_client: LLM client for summarization.
            link_rate_limiter: Optional rate limiter for link fetches.
        """
        self.config = config
        self.engine = engine
        self.llm_client = llm_client

        # Create rate limiter if not provided
        if link_rate_limiter is None:
            from zos.llm import RateLimiter

            link_rate_limiter = RateLimiter(calls_per_minute=5)
        self.link_rate_limiter = link_rate_limiter

    async def process_links(self, message_id: str, content: str) -> int:
        """Process all links in a message.

        Args:
            message_id: Message ID the links came from.
            content: Message content to scan for links.

        Returns:
            Number of links processed.
        """
        if not self.config.observation.link_fetch_enabled:
            return 0

        urls = extract_urls(content)
        if not urls:
            return 0

        log.debug(
            "processing_links",
            message_id=message_id,
            url_count=len(urls),
        )

        processed = 0
        for url in urls:
            try:
                if is_youtube_url(url):
                    await self._process_youtube(message_id, url)
                else:
                    await self._process_webpage(message_id, url)
                processed += 1
            except Exception as e:
                log.warning(
                    "link_processing_failed",
                    message_id=message_id,
                    url=url,
                    error=str(e),
                )

        return processed

    async def _process_webpage(self, message_id: str, url: str) -> None:
        """Fetch and summarize a webpage.

        Args:
            message_id: Message ID containing the link.
            url: URL to fetch and analyze.
        """
        # Rate limit
        await self.link_rate_limiter.acquire()

        # Fetch content
        content, title = await self._fetch_page(url)
        if not content:
            # Store failure record
            self._store_link_analysis(
                LinkAnalysis(
                    id=generate_id(),
                    message_id=message_id,
                    url=url,
                    domain=extract_domain(url),
                    content_type=ContentType.OTHER,
                    title=title,
                    fetch_failed=True,
                    fetch_error="Failed to fetch content",
                )
            )
            return

        # Summarize with LLM
        try:
            prompt = LINK_SUMMARY_PROMPT.format(content=content[:10000])
            result = await self.llm_client.complete(
                prompt=prompt,
                model_profile="simple",
                max_tokens=300,
            )
            summary = result.text
        except Exception as e:
            log.warning("link_summarization_failed", url=url, error=str(e))
            summary = None

        # Determine content type based on domain/content
        content_type = self._infer_content_type(url, content)

        # Store result
        self._store_link_analysis(
            LinkAnalysis(
                id=generate_id(),
                message_id=message_id,
                url=url,
                domain=extract_domain(url),
                content_type=content_type,
                title=title,
                summary=summary,
                is_youtube=False,
                fetched_at=datetime.now(timezone.utc),
                fetch_failed=False,
            )
        )

        log.debug(
            "webpage_analyzed",
            message_id=message_id,
            url=url,
            has_summary=summary is not None,
        )

    async def _process_youtube(self, message_id: str, url: str) -> None:
        """Process a YouTube video link.

        For videos under the duration threshold, fetches transcript and
        summarizes. For longer videos, records metadata only (TLDW principle).

        Args:
            message_id: Message ID containing the link.
            url: YouTube URL.
        """
        if not self.config.observation.youtube_transcript_enabled:
            return

        video_id = extract_video_id(url)
        if not video_id:
            log.debug("youtube_no_video_id", url=url)
            return

        # Get video metadata
        metadata = await self._get_video_metadata(video_id)
        title = metadata.get("title", "Unknown")
        duration_seconds = metadata.get("duration_seconds", 0)
        duration_minutes = duration_seconds / 60

        # Check duration threshold
        threshold = self.config.observation.video_duration_threshold_minutes
        if duration_minutes > threshold:
            # TLDW: Too Long, Didn't Watch
            summary = (
                f"Video is {int(duration_minutes)} minutes "
                f"(>{threshold}min threshold). "
                "TLDW requested but transcript not fetched."
            )
            transcript_available = False
        else:
            # Fetch transcript
            await self.link_rate_limiter.acquire()
            transcript = await self._fetch_transcript(video_id)

            if transcript:
                # Summarize transcript
                try:
                    prompt = TRANSCRIPT_SUMMARY_PROMPT.format(
                        title=title,
                        duration_minutes=int(duration_minutes),
                        transcript=transcript[:15000],
                    )
                    result = await self.llm_client.complete(
                        prompt=prompt,
                        model_profile="simple",
                        max_tokens=500,
                    )
                    summary = result.text
                    transcript_available = True
                except Exception as e:
                    log.warning(
                        "transcript_summarization_failed",
                        video_id=video_id,
                        error=str(e),
                    )
                    summary = "Transcript available but summarization failed."
                    transcript_available = True
            else:
                summary = "Transcript unavailable for this video."
                transcript_available = False

        # Store result
        self._store_link_analysis(
            LinkAnalysis(
                id=generate_id(),
                message_id=message_id,
                url=url,
                domain="youtube.com",
                content_type=ContentType.VIDEO,
                title=title,
                summary=summary,
                is_youtube=True,
                duration_seconds=duration_seconds if duration_seconds > 0 else None,
                transcript_available=transcript_available,
                fetched_at=datetime.now(timezone.utc),
                fetch_failed=False,
            )
        )

        log.debug(
            "youtube_analyzed",
            message_id=message_id,
            video_id=video_id,
            duration_minutes=int(duration_minutes),
            transcript_available=transcript_available,
        )

    async def _fetch_page(self, url: str) -> tuple[str | None, str | None]:
        """Fetch page content, respecting robots.txt.

        Args:
            url: URL to fetch.

        Returns:
            Tuple of (content, title), or (None, None) on failure.
        """
        try:
            # Check robots.txt
            if not await self._can_fetch(url):
                log.debug("robots_blocked", url=url)
                return None, None

            async with httpx.AsyncClient(
                timeout=10.0,
                follow_redirects=True,
            ) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": USER_AGENT},
                )
                response.raise_for_status()

                # Check content type - only process HTML
                content_type = response.headers.get("content-type", "")
                if "text/html" not in content_type.lower():
                    log.debug("non_html_content", url=url, content_type=content_type)
                    return None, None

                # Parse HTML and extract text
                soup = BeautifulSoup(response.text, "html.parser")

                # Extract title
                title_tag = soup.find("title")
                title = title_tag.get_text(strip=True) if title_tag else None

                # Remove script/style elements
                for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    tag.decompose()

                # Get text content
                content = soup.get_text(separator="\n", strip=True)

                return content, title

        except httpx.HTTPStatusError as e:
            log.debug("page_fetch_http_error", url=url, status=e.response.status_code)
            return None, None
        except Exception as e:
            log.warning("page_fetch_failed", url=url, error=str(e))
            return None, None

    async def _can_fetch(self, url: str) -> bool:
        """Check if robots.txt allows fetching the URL.

        This is a simplified check - we check if the path is explicitly
        disallowed for our user agent or all user agents.

        Args:
            url: URL to check.

        Returns:
            True if fetching is allowed.
        """
        try:
            parsed = urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    robots_url,
                    headers={"User-Agent": USER_AGENT},
                )

                if response.status_code != 200:
                    # No robots.txt or error - assume allowed
                    return True

                # Simple parsing - look for Disallow rules
                path = parsed.path or "/"
                current_agent = None
                disallow_all = False

                for line in response.text.splitlines():
                    line = line.strip().lower()

                    if line.startswith("user-agent:"):
                        agent = line.split(":", 1)[1].strip()
                        current_agent = agent

                    elif line.startswith("disallow:"):
                        if current_agent in ("*", "zos"):
                            disallowed = line.split(":", 1)[1].strip()
                            if disallowed == "/" or path.startswith(disallowed):
                                disallow_all = True

                return not disallow_all

        except Exception:
            # If we can't check robots.txt, assume allowed
            return True

    async def _fetch_transcript(self, video_id: str) -> str | None:
        """Fetch YouTube video transcript.

        Uses the youtube_transcript_api library which is synchronous,
        so we run it in an executor.

        Args:
            video_id: YouTube video ID.

        Returns:
            Combined transcript text, or None if unavailable.
        """
        try:
            from youtube_transcript_api import YouTubeTranscriptApi

            # This library is synchronous, run in executor
            loop = asyncio.get_event_loop()
            ytt = YouTubeTranscriptApi()
            transcript = await loop.run_in_executor(
                None, lambda: ytt.fetch(video_id)
            )

            # Combine transcript snippets
            return " ".join(snippet.text for snippet in transcript.snippets)

        except Exception as e:
            log.debug("transcript_unavailable", video_id=video_id, error=str(e))
            return None

    async def _get_video_metadata(self, video_id: str) -> dict:
        """Get YouTube video metadata.

        Uses oEmbed API which doesn't require an API key.
        Duration is approximated from description if available.

        Args:
            video_id: YouTube video ID.

        Returns:
            Dictionary with title and duration_seconds.
        """
        try:
            oembed_url = (
                f"https://www.youtube.com/oembed"
                f"?url=https://www.youtube.com/watch?v={video_id}&format=json"
            )

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(oembed_url)
                response.raise_for_status()
                data = response.json()

                title = data.get("title", "Unknown")

                # oEmbed doesn't provide duration, so we try to get it from
                # the transcript API metadata or default to 0
                duration_seconds = 0

                # Try to get duration from youtube_transcript_api
                try:
                    from youtube_transcript_api import YouTubeTranscriptApi

                    loop = asyncio.get_event_loop()
                    ytt = YouTubeTranscriptApi()
                    transcript = await loop.run_in_executor(
                        None, lambda: ytt.fetch(video_id)
                    )
                    if transcript.snippets:
                        # Duration is approximately the end time of the last snippet
                        last_snippet = transcript.snippets[-1]
                        duration_seconds = int(
                            last_snippet.start + last_snippet.duration
                        )
                except Exception:
                    pass

                return {
                    "title": title,
                    "duration_seconds": duration_seconds,
                }

        except Exception as e:
            log.debug("metadata_fetch_failed", video_id=video_id, error=str(e))
            return {"title": "Unknown", "duration_seconds": 0}

    def _infer_content_type(self, url: str, content: str) -> ContentType:
        """Infer content type from URL and content.

        Args:
            url: Original URL.
            content: Fetched page content.

        Returns:
            ContentType enum value.
        """
        url_lower = url.lower()
        domain = extract_domain(url)

        # Check for video hosting sites
        video_domains = {"vimeo.com", "twitch.tv", "dailymotion.com"}
        if domain in video_domains or "/video" in url_lower:
            return ContentType.VIDEO

        # Check for audio/podcast sites
        audio_domains = {"spotify.com", "soundcloud.com", "podcasts.apple.com"}
        if domain in audio_domains or "/podcast" in url_lower:
            return ContentType.AUDIO

        # Check for image hosting sites
        image_domains = {"imgur.com", "i.redd.it", "flickr.com"}
        image_extensions = (".jpg", ".jpeg", ".png", ".gif", ".webp")
        if domain in image_domains or any(url_lower.endswith(ext) for ext in image_extensions):
            return ContentType.IMAGE

        # Default to article
        return ContentType.ARTICLE

    def _store_link_analysis(self, analysis: LinkAnalysis) -> None:
        """Store link analysis result in database.

        Args:
            analysis: LinkAnalysis model to store.
        """
        from zos.models import model_to_dict

        data = model_to_dict(analysis)

        # Convert enum to string for database
        if isinstance(data.get("content_type"), ContentType):
            data["content_type"] = data["content_type"].value

        with self.engine.connect() as conn:
            stmt = sqlite_insert(link_analysis).values(**data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "summary": data.get("summary"),
                    "fetch_failed": data.get("fetch_failed"),
                    "fetch_error": data.get("fetch_error"),
                    "fetched_at": data.get("fetched_at"),
                },
            )
            conn.execute(stmt)
            conn.commit()


# =============================================================================
# Database Query Functions
# =============================================================================


def get_link_analysis_for_message(engine: Engine, message_id: str) -> list[LinkAnalysis]:
    """Get all link analyses for a message.

    Args:
        engine: SQLAlchemy engine.
        message_id: Message ID to query.

    Returns:
        List of LinkAnalysis records.
    """
    with engine.connect() as conn:
        result = conn.execute(
            select(link_analysis).where(link_analysis.c.message_id == message_id)
        )
        rows = result.fetchall()

        return [
            LinkAnalysis(
                id=row.id,
                message_id=row.message_id,
                url=row.url,
                domain=row.domain,
                content_type=ContentType(row.content_type),
                title=row.title,
                summary=row.summary,
                is_youtube=row.is_youtube,
                duration_seconds=row.duration_seconds,
                transcript_available=row.transcript_available,
                fetched_at=row.fetched_at,
                fetch_failed=row.fetch_failed,
                fetch_error=row.fetch_error,
            )
            for row in rows
        ]


def get_link_analyses_for_messages(
    engine: Engine, message_ids: list[str]
) -> dict[str, list[LinkAnalysis]]:
    """Get link analyses for multiple messages in a single batch query.

    Args:
        engine: SQLAlchemy engine.
        message_ids: List of message IDs to query.

    Returns:
        Dictionary mapping message_id to list of LinkAnalysis records.
    """
    if not message_ids:
        return {}

    result_map: dict[str, list[LinkAnalysis]] = {}

    with engine.connect() as conn:
        result = conn.execute(
            select(link_analysis).where(link_analysis.c.message_id.in_(message_ids))
        )
        rows = result.fetchall()

        for row in rows:
            analysis = LinkAnalysis(
                id=row.id,
                message_id=row.message_id,
                url=row.url,
                domain=row.domain,
                content_type=ContentType(row.content_type),
                title=row.title,
                summary=row.summary,
                is_youtube=row.is_youtube,
                duration_seconds=row.duration_seconds,
                transcript_available=row.transcript_available,
                fetched_at=row.fetched_at,
                fetch_failed=row.fetch_failed,
                fetch_error=row.fetch_error,
            )
            if row.message_id not in result_map:
                result_map[row.message_id] = []
            result_map[row.message_id].append(analysis)

    return result_map


def insert_link_analysis(engine: Engine, analysis: LinkAnalysis) -> None:
    """Insert a link analysis record.

    Args:
        engine: SQLAlchemy engine.
        analysis: LinkAnalysis model to insert.
    """
    from zos.models import model_to_dict

    data = model_to_dict(analysis)

    # Convert enum to string for database
    if isinstance(data.get("content_type"), ContentType):
        data["content_type"] = data["content_type"].value

    with engine.connect() as conn:
        conn.execute(link_analysis.insert().values(**data))
        conn.commit()
