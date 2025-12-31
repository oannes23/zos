"""Pytest fixtures for Zos tests."""

import tempfile
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from zos.config import DatabaseConfig, DiscordConfig, EarningWeights, ZosConfig
from zos.db import Database
from zos.discord.repository import MessageRepository
from zos.salience.earner import SalienceEarner


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def test_config(temp_dir: Path) -> ZosConfig:
    """Create a test configuration with temporary paths."""
    return ZosConfig(
        database=DatabaseConfig(path=temp_dir / "test.db"),
    )


@pytest.fixture
def test_db(temp_dir: Path) -> Generator[Database, None, None]:
    """Create a test database instance."""
    config = DatabaseConfig(path=temp_dir / "test.db")
    db = Database(config)
    db.initialize()
    yield db
    db.close()


# --- Discord Mock Fixtures ---


@pytest.fixture
def mock_discord_user() -> MagicMock:
    """Create a mock Discord user."""
    user = MagicMock()
    user.id = 123456789
    user.name = "TestUser"
    user.display_name = "Test User"
    user.bot = False
    return user


@pytest.fixture
def mock_discord_member(mock_discord_user: MagicMock) -> MagicMock:
    """Create a mock Discord member (user with roles)."""
    member = mock_discord_user
    role1 = MagicMock()
    role1.id = 111
    role1.name = "Role1"
    role2 = MagicMock()
    role2.id = 222
    role2.name = "@everyone"
    member.roles = [role1, role2]
    return member


@pytest.fixture
def mock_discord_guild() -> MagicMock:
    """Create a mock Discord guild."""
    guild = MagicMock()
    guild.id = 987654321
    guild.name = "TestGuild"
    return guild


@pytest.fixture
def mock_discord_channel(mock_discord_guild: MagicMock) -> MagicMock:
    """Create a mock Discord text channel."""
    channel = MagicMock()
    channel.id = 555555555
    channel.name = "test-channel"
    channel.guild = mock_discord_guild
    return channel


@pytest.fixture
def mock_discord_message(
    mock_discord_member: MagicMock,
    mock_discord_channel: MagicMock,
    mock_discord_guild: MagicMock,
) -> MagicMock:
    """Create a mock Discord message."""
    message = MagicMock()
    message.id = 1234567890
    message.content = "Test message content"
    message.author = mock_discord_member
    message.channel = mock_discord_channel
    message.guild = mock_discord_guild
    message.created_at = datetime.now(UTC)
    message.edited_at = None
    return message


@pytest.fixture
def mock_discord_reaction(mock_discord_message: MagicMock) -> MagicMock:
    """Create a mock Discord reaction."""
    reaction = MagicMock()
    reaction.message = mock_discord_message
    reaction.emoji = "👍"
    return reaction


@pytest.fixture
def test_discord_config() -> DiscordConfig:
    """Create a test Discord configuration."""
    return DiscordConfig(token="test-token")


@pytest.fixture
def message_repository(test_db: Database) -> MessageRepository:
    """Create a message repository with test database."""
    return MessageRepository(test_db)


@pytest.fixture
def salience_earner(test_db: Database) -> SalienceEarner:
    """Create a salience earner with test database."""
    return SalienceEarner(test_db, EarningWeights())
