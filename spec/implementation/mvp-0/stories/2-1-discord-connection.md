# Story 2.1: Discord Connection

**Epic**: Observation
**Status**: 🔴 Not Started
**Estimated complexity**: Medium

## Goal

Establish a discord.py bot that connects to Discord, maintains gateway presence, and provides the foundation for message polling.

## Acceptance Criteria

- [ ] Bot connects to Discord gateway successfully
- [ ] Bot logs "ready" with server/channel counts
- [ ] Bot handles reconnection gracefully
- [ ] Background task scaffold runs on interval
- [ ] `zos observe` CLI command starts the bot
- [ ] Graceful shutdown on SIGINT/SIGTERM

## Technical Notes

### Bot Setup

```python
# src/zos/observation.py
import discord
from discord.ext import tasks
import structlog

log = structlog.get_logger()

class ZosBot(discord.Client):
    def __init__(self, config: Config):
        # Minimal intents for observation
        intents = discord.Intents.default()
        intents.message_content = True
        intents.reactions = True
        intents.members = True  # For user info

        super().__init__(intents=intents)
        self.config = config

    async def setup_hook(self):
        """Called when bot is ready to start tasks."""
        self.poll_messages.start()

    async def on_ready(self):
        """Called when connected to Discord."""
        log.info(
            "discord_ready",
            user=str(self.user),
            guilds=len(self.guilds),
            channels=sum(len(g.text_channels) for g in self.guilds),
        )

    async def on_disconnect(self):
        """Called when disconnected."""
        log.warning("discord_disconnected")

    async def on_resumed(self):
        """Called when connection resumed."""
        log.info("discord_resumed")

    @tasks.loop(seconds=60)  # Configurable via config
    async def poll_messages(self):
        """Background task for message polling."""
        # Implemented in Story 2.2
        pass

    @poll_messages.before_loop
    async def before_poll(self):
        """Wait until bot is ready before polling."""
        await self.wait_until_ready()
```

### CLI Command

```python
# src/zos/cli.py
import asyncio

@cli.command()
@click.pass_context
def observe(ctx):
    """Start the Discord observation bot."""
    config = ctx.obj["config"]

    if not config.discord_token:
        click.echo("Error: DISCORD_TOKEN not set", err=True)
        raise SystemExit(1)

    bot = ZosBot(config)

    async def run():
        async with bot:
            await bot.start(config.discord_token)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("shutdown_requested")
```

### Intents Configuration

The bot needs these intents:
- `message_content` — Read message text
- `reactions` — Track reactions
- `members` — Get user information
- `guilds` — Server membership (default)

These must be enabled in the Discord Developer Portal.

### Graceful Shutdown

```python
import signal

def setup_signal_handlers(bot: ZosBot):
    """Setup graceful shutdown handlers."""
    loop = asyncio.get_event_loop()

    async def shutdown():
        log.info("shutting_down")
        bot.poll_messages.cancel()
        await bot.close()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig,
            lambda: asyncio.create_task(shutdown())
        )
```

## Configuration

```yaml
# config.yaml
discord:
  polling_interval_seconds: 60
  # token from DISCORD_TOKEN env var
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/observation.py` | ZosBot class, connection logic |
| `src/zos/cli.py` | Add `observe` command |
| `tests/test_observation.py` | Connection tests (mocked) |

## Test Cases

1. Bot initializes with correct intents
2. CLI fails gracefully without token
3. Polling task starts after ready
4. Signal handlers trigger clean shutdown

## Definition of Done

- [ ] `zos observe` connects to Discord
- [ ] Logs show ready state with counts
- [ ] Ctrl+C shuts down cleanly
- [ ] Reconnection works after brief disconnect

---

**Requires**: Epic 1 complete
**Blocks**: Stories 2.2-2.5
