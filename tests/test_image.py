"""Tests for image generation client and directive parsing."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zos.config import Config, ImageConfig
from zos.executor import IMAGE_DIRECTIVE_RE


# =============================================================================
# Directive parsing tests
# =============================================================================


class TestImageDirectiveParsing:
    """Test [IMAGE: ...] directive extraction and stripping."""

    def test_extract_simple_directive(self):
        text = "Here's a thought. [IMAGE: a warm sunrise over quiet water]"
        match = IMAGE_DIRECTIVE_RE.search(text)
        assert match is not None
        assert match.group(1).strip() == "a warm sunrise over quiet water"

    def test_extract_directive_mid_text(self):
        text = "Some text [IMAGE: night sky with stars] more text"
        match = IMAGE_DIRECTIVE_RE.search(text)
        assert match is not None
        assert match.group(1).strip() == "night sky with stars"

    def test_strip_directive_from_text(self):
        text = "Here's a thought. [IMAGE: a warm sunrise over quiet water]"
        cleaned = IMAGE_DIRECTIVE_RE.sub("", text).strip()
        assert cleaned == "Here's a thought."

    def test_strip_directive_mid_text(self):
        text = "Before [IMAGE: something visual] after"
        cleaned = IMAGE_DIRECTIVE_RE.sub("", text).strip()
        assert cleaned == "Before  after"

    def test_no_directive(self):
        text = "Just a regular message with no image."
        match = IMAGE_DIRECTIVE_RE.search(text)
        assert match is None

    def test_directive_with_extra_whitespace(self):
        text = "[IMAGE:   lots of space here   ]"
        match = IMAGE_DIRECTIVE_RE.search(text)
        assert match is not None
        assert match.group(1).strip() == "lots of space here"

    def test_empty_text_after_strip(self):
        text = "[IMAGE: just an image nothing else]"
        cleaned = IMAGE_DIRECTIVE_RE.sub("", text).strip()
        assert cleaned == ""

    def test_only_first_directive_matched(self):
        text = "[IMAGE: first] text [IMAGE: second]"
        match = IMAGE_DIRECTIVE_RE.search(text)
        assert match is not None
        assert match.group(1).strip() == "first"

    def test_all_directives_stripped(self):
        text = "[IMAGE: first] text [IMAGE: second]"
        cleaned = IMAGE_DIRECTIVE_RE.sub("", text).strip()
        assert cleaned == "text"


# =============================================================================
# ImageConfig tests
# =============================================================================


class TestImageConfig:
    """Test ImageConfig defaults and validation."""

    def test_defaults(self):
        config = ImageConfig()
        assert config.enabled is False
        assert config.model == "dall-e-3"
        assert config.size == "1024x1024"
        assert config.quality == "standard"

    def test_config_includes_image(self):
        config = Config()
        assert hasattr(config, "image")
        assert isinstance(config.image, ImageConfig)
        assert config.image.enabled is False


# =============================================================================
# ImageClient tests
# =============================================================================


class TestImageClient:
    """Test ImageClient with mocked OpenAI responses."""

    @pytest.fixture
    def image_config(self, tmp_path: Path) -> Config:
        """Config with image enabled and mocked OpenAI key."""
        from zos.config import ModelsConfig, ModelProfile

        config = Config(
            data_dir=tmp_path / "data",
            image=ImageConfig(enabled=True),
            models=ModelsConfig(
                profiles={"simple": ModelProfile(provider="openai", model="gpt-4")},
                providers={"openai": {"api_key_env": "OPENAI_API_KEY"}},
            ),
        )
        return config

    @pytest.mark.asyncio
    async def test_generate_saves_image(self, image_config: Config, tmp_path: Path):
        """ImageClient.generate() downloads image and saves to disk."""
        from zos.image import ImageClient

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            client = ImageClient(image_config)

        # Mock the OpenAI response
        mock_image_data = MagicMock()
        mock_image_data.url = "https://example.com/image.png"
        mock_image_data.revised_prompt = "a revised prompt"

        mock_response = MagicMock()
        mock_response.data = [mock_image_data]

        client._client.images.generate = AsyncMock(return_value=mock_response)

        # Mock httpx download
        mock_http_response = MagicMock()
        mock_http_response.content = b"fake-png-bytes"
        mock_http_response.raise_for_status = MagicMock()

        with patch("zos.image.httpx.AsyncClient") as mock_httpx:
            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_http_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_httpx.return_value = mock_client_instance

            result = await client.generate("a warm sunrise")

        assert result.image_path.exists()
        assert result.image_path.read_bytes() == b"fake-png-bytes"
        assert result.revised_prompt == "a revised prompt"
        assert result.size == "1024x1024"
        assert result.image_path.suffix == ".png"

        await client.close()

    @pytest.mark.asyncio
    async def test_generate_calls_openai_with_correct_params(
        self, image_config: Config
    ):
        """Verify the OpenAI API is called with expected parameters."""
        from zos.image import ImageClient

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            client = ImageClient(image_config)

        mock_image_data = MagicMock()
        mock_image_data.url = "https://example.com/img.png"
        mock_image_data.revised_prompt = None

        mock_response = MagicMock()
        mock_response.data = [mock_image_data]

        client._client.images.generate = AsyncMock(return_value=mock_response)

        mock_http_response = MagicMock()
        mock_http_response.content = b"bytes"
        mock_http_response.raise_for_status = MagicMock()

        with patch("zos.image.httpx.AsyncClient") as mock_httpx:
            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_http_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_httpx.return_value = mock_client_instance

            await client.generate("test prompt", size="1792x1024")

        client._client.images.generate.assert_awaited_once_with(
            model="dall-e-3",
            prompt="test prompt",
            size="1792x1024",
            quality="standard",
            n=1,
        )

        await client.close()

    def test_missing_api_key_raises(self, tmp_path: Path):
        """ImageClient raises ValueError without OpenAI API key."""
        from zos.image import ImageClient

        config = Config(
            data_dir=tmp_path,
            image=ImageConfig(enabled=True),
        )
        with pytest.raises(ValueError, match="OpenAI API key required"):
            ImageClient(config)
