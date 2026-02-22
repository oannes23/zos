"""Tests for per-server speech channel routing.

Covers:
- Speech channel overrides channel_id for channel topics
- Speech channel overrides channel_id for subject topics
- Speech channel does NOT affect user/DM topics
- Speech channel is ignored when operator_dm_only is true
- No speech_channel configured = existing behavior unchanged
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zos.config import ChattinessConfig, Config, ServerOverrideConfig
from zos.observation import ZosBot


SERVER_ID = "1074189977832914985"
SPEECH_CHANNEL_ID = "9999999999"
ORIGINAL_CHANNEL_ID = "1111111111"


def _make_bot(
    *,
    speech_channel: str | None = None,
    operator_dm_only: bool = False,
) -> ZosBot:
    """Create a ZosBot with the given speech channel config."""
    config = Config(
        chattiness=ChattinessConfig(operator_dm_only=operator_dm_only),
        servers={
            SERVER_ID: ServerOverrideConfig(
                speech_channel=speech_channel,
            ),
        },
    )
    bot = ZosBot(config)

    # Mock executor and layer_loader so _dispatch_conversation doesn't bail early
    bot._executor = MagicMock()
    bot._executor.execute_layer = AsyncMock(return_value=MagicMock())
    bot._layer_loader = MagicMock()
    bot._layer_loader.get_layer = MagicMock(return_value=MagicMock())

    # Mock get_channel to return a channel-like object with a name
    def fake_get_channel(channel_id: int) -> MagicMock | None:
        names = {
            int(SPEECH_CHANNEL_ID): "zos-speaks",
            int(ORIGINAL_CHANNEL_ID): "general",
        }
        if channel_id in names:
            ch = MagicMock()
            ch.name = names[channel_id]
            return ch
        return None

    bot.get_channel = fake_get_channel
    return bot


def _extract_send_context(bot: ZosBot) -> dict:
    """Extract the send_context dict passed to execute_layer."""
    call_args = bot._executor.execute_layer.call_args
    return call_args.kwargs.get("send_context", call_args[1].get("send_context", {}))


class TestSpeechChannelRouting:
    """Tests for speech_channel override in _dispatch_conversation."""

    @pytest.mark.asyncio
    async def test_channel_topic_routed_to_speech_channel(self) -> None:
        """Channel topic should be redirected to speech_channel."""
        bot = _make_bot(speech_channel=SPEECH_CHANNEL_ID)
        topic_key = f"server:{SERVER_ID}:channel:{ORIGINAL_CHANNEL_ID}"

        await bot._dispatch_conversation(topic_key, "channel-speak")

        ctx = _extract_send_context(bot)
        assert ctx["channel_id"] == SPEECH_CHANNEL_ID
        assert ctx["channel_name"] == "zos-speaks"
        assert ctx["source_channel_name"] == "general"
        assert ctx["speech_channel"] is True

    @pytest.mark.asyncio
    async def test_subject_topic_routed_to_speech_channel(self) -> None:
        """Subject topic should get channel_id set to speech_channel."""
        bot = _make_bot(speech_channel=SPEECH_CHANNEL_ID)
        topic_key = f"server:{SERVER_ID}:subject:ai-ethics"

        await bot._dispatch_conversation(topic_key, "subject-share")

        ctx = _extract_send_context(bot)
        assert ctx["channel_id"] == SPEECH_CHANNEL_ID
        assert ctx["channel_name"] == "zos-speaks"
        assert ctx["speech_channel"] is True
        # Subject topics have no source channel
        assert "source_channel_name" not in ctx

    @pytest.mark.asyncio
    async def test_dm_topic_unaffected_by_speech_channel(self) -> None:
        """User/DM topics should NOT be affected by speech_channel."""
        bot = _make_bot(speech_channel=SPEECH_CHANNEL_ID)
        topic_key = "user:123456789"

        await bot._dispatch_conversation(topic_key, "dm-response")

        ctx = _extract_send_context(bot)
        assert ctx.get("dm_user_id") == "123456789"
        assert "speech_channel" not in ctx
        assert ctx.get("channel_id") is None

    @pytest.mark.asyncio
    async def test_speech_channel_ignored_when_operator_dm_only(self) -> None:
        """Speech channel should be ignored when operator_dm_only is true."""
        bot = _make_bot(
            speech_channel=SPEECH_CHANNEL_ID, operator_dm_only=True
        )
        topic_key = f"server:{SERVER_ID}:channel:{ORIGINAL_CHANNEL_ID}"

        await bot._dispatch_conversation(topic_key, "channel-speak")

        ctx = _extract_send_context(bot)
        assert ctx.get("operator_dm") is True
        assert "speech_channel" not in ctx
        assert ctx.get("channel_id") is None

    @pytest.mark.asyncio
    async def test_no_speech_channel_preserves_existing_behavior(self) -> None:
        """Without speech_channel, channel topics route to their natural channel."""
        bot = _make_bot(speech_channel=None)
        topic_key = f"server:{SERVER_ID}:channel:{ORIGINAL_CHANNEL_ID}"

        await bot._dispatch_conversation(topic_key, "channel-speak")

        ctx = _extract_send_context(bot)
        assert ctx["channel_id"] == ORIGINAL_CHANNEL_ID
        assert ctx["channel_name"] == "general"
        assert "speech_channel" not in ctx
        assert "source_channel_name" not in ctx

    @pytest.mark.asyncio
    async def test_server_id_extracted_into_send_context(self) -> None:
        """Server ID should always be in send_context for server-scoped topics."""
        bot = _make_bot(speech_channel=None)
        topic_key = f"server:{SERVER_ID}:channel:{ORIGINAL_CHANNEL_ID}"

        await bot._dispatch_conversation(topic_key, "channel-speak")

        ctx = _extract_send_context(bot)
        assert ctx["server_id"] == SERVER_ID


class TestSpeechChannelConfig:
    """Tests for speech_channel in ServerOverrideConfig."""

    def test_speech_channel_defaults_to_none(self) -> None:
        """speech_channel should default to None."""
        config = ServerOverrideConfig()
        assert config.speech_channel is None

    def test_speech_channel_configurable(self) -> None:
        """speech_channel should accept a channel ID string."""
        config = ServerOverrideConfig(speech_channel="1234567890")
        assert config.speech_channel == "1234567890"

    def test_speech_channel_from_yaml(self, tmp_path) -> None:
        """speech_channel should load from YAML config."""
        import yaml

        config_data = {
            "servers": {
                SERVER_ID: {
                    "speech_channel": SPEECH_CHANNEL_ID,
                }
            }
        }
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(config_data))

        config = Config.model_validate(config_data)
        server_config = config.get_server_config(SERVER_ID)
        assert server_config.speech_channel == SPEECH_CHANNEL_ID
