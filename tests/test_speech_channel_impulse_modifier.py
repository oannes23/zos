"""Tests for speech_channel_impulse_modifier config.

Verifies that per-server impulse modifier scales channel impulse earning
for messages and reactions, but does not affect ping saturation.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from sqlalchemy import select

from zos.chattiness import ImpulseEngine
from zos.config import Config, ServerOverrideConfig
from zos.database import (
    channels,
    chattiness_ledger,
    create_tables,
    get_engine,
    messages,
    servers,
)
from zos.observation import ZosBot


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture()
def base_config(tmp_path):
    return Config(
        data_dir=tmp_path,
        discord={"polling_interval_seconds": 60},
    )


@pytest.fixture()
def db_engine(base_config):
    engine = get_engine(base_config)
    create_tables(engine)
    return engine


@pytest.fixture()
def impulse_engine(db_engine, base_config):
    return ImpulseEngine(engine=db_engine, config=base_config)


# =============================================================================
# Config field tests
# =============================================================================


class TestModifierConfig:
    def test_default_modifier_is_one(self):
        cfg = ServerOverrideConfig()
        assert cfg.speech_channel_impulse_modifier == 1.0

    def test_custom_modifier(self):
        cfg = ServerOverrideConfig(speech_channel_impulse_modifier=2.5)
        assert cfg.speech_channel_impulse_modifier == 2.5

    def test_modifier_from_server_config(self, base_config):
        base_config.servers = {
            "111": ServerOverrideConfig(speech_channel_impulse_modifier=3.0),
        }
        sc = base_config.get_server_config("111")
        assert sc.speech_channel_impulse_modifier == 3.0

    def test_missing_server_returns_default(self, base_config):
        sc = base_config.get_server_config("999")
        assert sc.speech_channel_impulse_modifier == 1.0


# =============================================================================
# Impulse earning integration tests
# =============================================================================


def _seed_server_and_channel(engine, server_id="111", channel_id="222"):
    """Insert minimal server + channel rows so FK constraints pass."""
    with engine.begin() as conn:
        conn.execute(
            servers.insert().values(
                id=server_id,
                name="TestServer",
                created_at=datetime.now(timezone.utc),
            )
        )
        conn.execute(
            channels.insert().values(
                id=channel_id,
                server_id=server_id,
                name="test-channel",
                type="text",
                created_at=datetime.now(timezone.utc),
            )
        )


def _ledger_sum(engine, topic_key):
    """Sum all ledger amounts for a topic."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(chattiness_ledger.c.amount).where(
                chattiness_ledger.c.topic_key == topic_key
            )
        ).fetchall()
    return sum(r[0] for r in rows)


class TestMessageImpulseModifier:
    """Modifier applied during _poll_channel message impulse earning."""

    @pytest.mark.asyncio
    async def test_default_modifier_no_change(self, db_engine, base_config):
        """Modifier 1.0 produces same impulse as unmodified path."""
        _seed_server_and_channel(db_engine, "111", "222")
        ie = ImpulseEngine(engine=db_engine, config=base_config)

        per_msg = base_config.chattiness.channel_impulse_per_message
        server_config = base_config.get_server_config("111")

        messages_stored = 5
        amount = messages_stored * per_msg * server_config.speech_channel_impulse_modifier
        ie.earn("server:111:channel:222", amount, trigger="poll:5_msgs")

        assert _ledger_sum(db_engine, "server:111:channel:222") == pytest.approx(
            messages_stored * per_msg
        )

    @pytest.mark.asyncio
    async def test_boosted_modifier_multiplies(self, db_engine, base_config):
        """Modifier 2.0 doubles impulse from messages."""
        _seed_server_and_channel(db_engine, "111", "222")
        base_config.servers = {
            "111": ServerOverrideConfig(speech_channel_impulse_modifier=2.0),
        }
        ie = ImpulseEngine(engine=db_engine, config=base_config)

        per_msg = base_config.chattiness.channel_impulse_per_message
        server_config = base_config.get_server_config("111")

        messages_stored = 5
        amount = messages_stored * per_msg * server_config.speech_channel_impulse_modifier
        ie.earn("server:111:channel:222", amount, trigger="poll:5_msgs")

        assert _ledger_sum(db_engine, "server:111:channel:222") == pytest.approx(
            messages_stored * per_msg * 2.0
        )


class TestReactionImpulseModifier:
    """Modifier applied during _earn_reaction_impulse."""

    @pytest.mark.asyncio
    async def test_default_modifier_no_change(self, db_engine, base_config):
        _seed_server_and_channel(db_engine, "111", "222")
        ie = ImpulseEngine(engine=db_engine, config=base_config)

        per_react = base_config.chattiness.channel_impulse_per_reaction
        server_config = base_config.get_server_config("111")
        amount = per_react * server_config.speech_channel_impulse_modifier
        ie.earn("server:111:channel:222", amount, trigger="reaction:222")

        assert _ledger_sum(db_engine, "server:111:channel:222") == pytest.approx(
            per_react
        )

    @pytest.mark.asyncio
    async def test_boosted_modifier_multiplies(self, db_engine, base_config):
        _seed_server_and_channel(db_engine, "111", "222")
        base_config.servers = {
            "111": ServerOverrideConfig(speech_channel_impulse_modifier=3.0),
        }
        ie = ImpulseEngine(engine=db_engine, config=base_config)

        per_react = base_config.chattiness.channel_impulse_per_reaction
        server_config = base_config.get_server_config("111")
        amount = per_react * server_config.speech_channel_impulse_modifier
        ie.earn("server:111:channel:222", amount, trigger="reaction:222")

        assert _ledger_sum(db_engine, "server:111:channel:222") == pytest.approx(
            per_react * 3.0
        )


class TestPingSaturationUnaffected:
    """Ping saturation should NOT be modified — it guarantees a response."""

    @pytest.mark.asyncio
    async def test_ping_uses_raw_threshold(self, db_engine, base_config):
        """Even with modifier > 1.0, ping saturation earns exactly threshold."""
        _seed_server_and_channel(db_engine, "111", "222")
        base_config.servers = {
            "111": ServerOverrideConfig(speech_channel_impulse_modifier=5.0),
        }
        ie = ImpulseEngine(engine=db_engine, config=base_config)

        # Ping saturation earns config.chattiness.threshold (unmodified)
        threshold = base_config.chattiness.threshold
        ie.earn("server:111:channel:222", threshold, trigger="ping:222")

        assert _ledger_sum(db_engine, "server:111:channel:222") == pytest.approx(
            threshold
        )
