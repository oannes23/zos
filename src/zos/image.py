"""Image generation client for Zos.

Thin async wrapper around OpenAI's DALL-E API. Generates images from text
prompts and saves them locally for Discord attachment.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
from openai import AsyncOpenAI

from zos.database import generate_id
from zos.logging import get_logger

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zos.config import Config

log = get_logger("image")


@dataclass
class ImageResult:
    """Result of an image generation request."""

    image_path: Path
    revised_prompt: str
    size: str


class ImageClient:
    """Async client for image generation via OpenAI DALL-E."""

    def __init__(self, config: "Config") -> None:
        api_key = config.models.get_api_key("openai") if config.models else None
        if not api_key:
            raise ValueError("OpenAI API key required for image generation")

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = config.image.model
        self._size = config.image.size
        self._quality = config.image.quality
        self._output_dir = config.data_dir / "media" / "generated"

    async def generate(self, prompt: str, size: str | None = None) -> ImageResult:
        """Generate an image from a text prompt.

        Args:
            prompt: Description of the image to generate.
            size: Optional size override (e.g., "1024x1024").

        Returns:
            ImageResult with local file path and metadata.
        """
        effective_size = size or self._size

        log.info("image_generate_start", prompt=prompt[:100], size=effective_size)

        response = await self._client.images.generate(
            model=self._model,
            prompt=prompt,
            size=effective_size,
            quality=self._quality,
            n=1,
        )

        image_data = response.data[0]
        image_url = image_data.url
        revised_prompt = image_data.revised_prompt or prompt

        # Download the image
        async with httpx.AsyncClient() as http:
            dl = await http.get(image_url)
            dl.raise_for_status()
            image_bytes = dl.content

        # Save to disk
        self._output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{generate_id()}.png"
        image_path = self._output_dir / filename

        image_path.write_bytes(image_bytes)

        log.info(
            "image_generate_complete",
            path=str(image_path),
            revised_prompt=revised_prompt[:100],
            size=effective_size,
            bytes=len(image_bytes),
        )

        return ImageResult(
            image_path=image_path,
            revised_prompt=revised_prompt,
            size=effective_size,
        )

    async def close(self) -> None:
        """Close the underlying OpenAI client."""
        await self._client.close()
