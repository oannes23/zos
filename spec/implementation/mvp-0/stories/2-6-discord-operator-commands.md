# Story 2.6: Discord Operator Commands

**Epic**: Observation
**Status**: 🟢 Complete
**Estimated complexity**: Medium

## Goal

Implement Discord slash commands for operators to monitor and control Zos without needing shell access.

## Acceptance Criteria

- [x] `/ping` responds with "pong" (no LLM, health check)
- [x] `/status` shows salience summary, active topics, recent activity (placeholder for Epic 3/4 data)
- [x] `/silence` toggles observation pause
- [x] `/reflect-now` triggers manual reflection (placeholder for Epic 4)
- [x] `/insights <topic>` queries insights for a topic (placeholder for Epic 4)
- [x] `/topics` lists all topics with salience (placeholder for Epic 3)
- [x] `/layer-run <name>` manually triggers a specific layer (placeholder for Epic 4)
- [x] `/dev-mode` toggles dev mode (enables CRUD operations)
- [x] Commands restricted to operators (role or user ID)

## Technical Notes

### Command Registration

```python
# src/zos/commands.py
from discord import app_commands
from discord.ext import commands
import structlog

log = structlog.get_logger()

class OperatorCommands(commands.Cog):
    """Slash commands for Zos operators."""

    def __init__(self, bot: ZosBot):
        self.bot = bot
        self.db = bot.db
        self.config = bot.config

    def is_operator(self, interaction: discord.Interaction) -> bool:
        """Check if user is an operator."""
        # Check by user ID
        if str(interaction.user.id) in self.config.operator_user_ids:
            return True

        # Check by role
        if interaction.guild:
            user_roles = {str(r.id) for r in interaction.user.roles}
            if self.config.operator_role_id in user_roles:
                return True

        return False

    async def operator_check(self, interaction: discord.Interaction) -> bool:
        """Interaction check for operator commands."""
        if not self.is_operator(interaction):
            await interaction.response.send_message(
                "This command is restricted to operators.",
                ephemeral=True
            )
            return False
        return True
```

### Ping Command

```python
    @app_commands.command(name="ping", description="Health check - responds with pong")
    async def ping(self, interaction: discord.Interaction):
        """Simple health check, no LLM involved."""
        if not await self.operator_check(interaction):
            return

        await interaction.response.send_message("pong", ephemeral=True)
        log.info("ping_command", user=str(interaction.user))
```

### Status Command

```python
    @app_commands.command(name="status", description="Show Zos status summary")
    async def status(self, interaction: discord.Interaction):
        """Show salience summary and recent activity."""
        if not await self.operator_check(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        # Gather status info
        warm_topics = await self.db.get_warm_topics(limit=10)
        recent_runs = await self.db.get_recent_layer_runs(limit=5)
        total_insights = await self.db.count_insights()
        is_silenced = self.bot.is_silenced

        # Format response
        lines = [
            f"**Zos Status**",
            f"",
            f"🔇 Silenced: {'Yes' if is_silenced else 'No'}",
            f"💡 Total insights: {total_insights}",
            f"",
            f"**Top Warm Topics:**",
        ]
        for topic in warm_topics:
            lines.append(f"  • `{topic.key}`: {topic.balance:.1f}")

        lines.append("")
        lines.append("**Recent Layer Runs:**")
        for run in recent_runs:
            status_emoji = "✅" if run.status == "completed" else "❌"
            lines.append(f"  {status_emoji} {run.layer_name} ({run.insights_created} insights)")

        await interaction.followup.send("\n".join(lines), ephemeral=True)
```

### Silence Command

```python
    @app_commands.command(name="silence", description="Toggle observation pause")
    async def silence(self, interaction: discord.Interaction):
        """Pause or resume observation."""
        if not await self.operator_check(interaction):
            return

        self.bot.is_silenced = not self.bot.is_silenced
        state = "paused" if self.bot.is_silenced else "resumed"

        await interaction.response.send_message(
            f"Observation {state}.",
            ephemeral=True
        )
        log.info("silence_toggled", state=state, user=str(interaction.user))
```

### Reflect-Now Command

```python
    @app_commands.command(name="reflect-now", description="Trigger reflection immediately")
    async def reflect_now(self, interaction: discord.Interaction):
        """Manually trigger reflection cycle."""
        if not await self.operator_check(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        # Trigger reflection
        result = await self.bot.trigger_reflection()

        await interaction.followup.send(
            f"Reflection triggered. {result.topics_processed} topics processed, "
            f"{result.insights_created} insights created.",
            ephemeral=True
        )
```

### Insights Command

```python
    @app_commands.command(name="insights", description="Query insights for a topic")
    @app_commands.describe(topic="Topic key (e.g., user:123, channel:456)")
    async def insights(self, interaction: discord.Interaction, topic: str):
        """Query recent insights for a topic."""
        if not await self.operator_check(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        insights = await self.db.get_insights_for_topic(topic, limit=5)

        if not insights:
            await interaction.followup.send(
                f"No insights found for `{topic}`",
                ephemeral=True
            )
            return

        lines = [f"**Recent insights for `{topic}`:**\n"]
        for insight in insights:
            age = relative_time(insight.created_at)
            lines.append(f"[{age}] {insight.content[:200]}...")
            lines.append("")

        await interaction.followup.send("\n".join(lines), ephemeral=True)
```

### Topics Command

```python
    @app_commands.command(name="topics", description="List all topics with salience")
    async def topics(self, interaction: discord.Interaction):
        """List topics ordered by salience."""
        if not await self.operator_check(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        topics = await self.db.get_all_topics_with_salience(limit=20)

        lines = ["**Topics by Salience:**\n"]
        for topic in topics:
            warm = "🔥" if topic.balance >= self.config.warm_threshold else "❄️"
            lines.append(f"{warm} `{topic.key}`: {topic.balance:.1f}")

        await interaction.followup.send("\n".join(lines), ephemeral=True)
```

### Layer-Run Command

```python
    @app_commands.command(name="layer-run", description="Manually run a specific layer")
    @app_commands.describe(layer_name="Name of the layer to run")
    async def layer_run(
        self,
        interaction: discord.Interaction,
        layer_name: str
    ):
        """Manually trigger a specific layer."""
        if not await self.operator_check(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        # Validate layer exists
        if layer_name not in self.bot.available_layers:
            await interaction.followup.send(
                f"Unknown layer: `{layer_name}`\n"
                f"Available: {', '.join(self.bot.available_layers)}",
                ephemeral=True
            )
            return

        # Run layer
        result = await self.bot.run_layer(layer_name)

        await interaction.followup.send(
            f"Layer `{layer_name}` completed: {result.status}\n"
            f"Topics: {result.topics_processed}, Insights: {result.insights_created}",
            ephemeral=True
        )
```

### Dev-Mode Command

```python
    @app_commands.command(name="dev-mode", description="Toggle dev mode")
    async def dev_mode(self, interaction: discord.Interaction):
        """Toggle dev mode (enables CRUD operations)."""
        if not await self.operator_check(interaction):
            return

        self.config.dev_mode = not self.config.dev_mode
        state = "enabled" if self.config.dev_mode else "disabled"

        await interaction.response.send_message(
            f"Dev mode {state}. CRUD operations {'available' if self.config.dev_mode else 'restricted'}.",
            ephemeral=True
        )
        log.info("dev_mode_toggled", state=state, user=str(interaction.user))
```

### Bot Integration

```python
# In ZosBot.__init__ or setup_hook
async def setup_hook(self):
    # ... existing setup
    await self.add_cog(OperatorCommands(self))

    # Sync commands to Discord
    await self.tree.sync()
```

## Configuration

```yaml
# config.yaml
operators:
  user_ids:
    - "123456789"  # Operator user IDs
  role_id: "987654321"  # Optional: role that grants operator access
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/commands.py` | OperatorCommands cog |
| `src/zos/observation.py` | Add cog to bot, is_silenced flag |
| `src/zos/config.py` | Operator config section |
| `tests/test_commands.py` | Command tests (mocked) |

## Test Cases

1. Non-operator gets rejection message
2. Ping responds immediately
3. Status shows correct counts
4. Silence toggles observation
5. Reflect-now triggers reflection
6. Insights query returns results
7. Topics list is ordered by salience
8. Layer-run validates layer name
9. Dev-mode toggles config flag

## Definition of Done

- [x] All 8 commands implemented
- [x] Operator check works (user ID and role)
- [x] Commands respond ephemerally
- [x] Logging captures command usage
- [x] Commands synced to Discord

---

**Requires**: Story 2.1 (Discord connection)
**Blocks**: None (operators can manage Zos via Discord)
