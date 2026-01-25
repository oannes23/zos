"""Discord slash commands for Zos operators.

These commands provide operators with windows into Zos's internal state -
insight into phenomenological experience, control over observation,
and triggers for reflection.

All commands respond ephemerally (only visible to the caller) and
are restricted to operators (by user ID or role).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from zos.logging import get_logger

if TYPE_CHECKING:
    from zos.observation import ZosBot

log = get_logger("commands")


class OperatorCommands(commands.Cog):
    """Slash commands for Zos operators.

    Provides monitoring and control capabilities without requiring
    shell access. These are the operator's interface to Zos's
    internal experience.
    """

    def __init__(self, bot: ZosBot) -> None:
        """Initialize the commands cog.

        Args:
            bot: The ZosBot instance.
        """
        self.bot = bot
        self.config = bot.config

    def is_operator(self, interaction: discord.Interaction) -> bool:
        """Check if user is an operator.

        Operators are identified by:
        1. User ID in the configured operator_user_ids list
        2. Having the configured operator_role_id (if set)

        Args:
            interaction: The Discord interaction to check.

        Returns:
            True if the user is an operator, False otherwise.
        """
        operators_config = self.config.discord.operators

        # Check by user ID
        if str(interaction.user.id) in operators_config.user_ids:
            return True

        # Check by role (if configured and in a guild)
        if operators_config.role_id and interaction.guild:
            # interaction.user in a guild context is a Member with roles
            member = interaction.user
            if isinstance(member, discord.Member):
                user_role_ids = {str(r.id) for r in member.roles}
                if operators_config.role_id in user_role_ids:
                    return True

        return False

    async def operator_check(self, interaction: discord.Interaction) -> bool:
        """Interaction check for operator commands.

        Sends a rejection message if the user is not an operator.

        Args:
            interaction: The Discord interaction to check.

        Returns:
            True if the user is an operator and can proceed.
        """
        if not self.is_operator(interaction):
            await interaction.response.send_message(
                "This command is restricted to operators.",
                ephemeral=True,
            )
            log.info(
                "command_rejected",
                command=interaction.command.name if interaction.command else "unknown",
                user=str(interaction.user),
                reason="not_operator",
            )
            return False
        return True

    @app_commands.command(name="ping", description="Health check - responds with pong")
    async def ping(self, interaction: discord.Interaction) -> None:
        """Simple health check, no LLM involved.

        This is the most basic operator command - confirms Zos is alive
        and responsive without any processing overhead.
        """
        if not await self.operator_check(interaction):
            return

        await interaction.response.send_message("pong", ephemeral=True)
        log.info("ping_command", user=str(interaction.user))

    @app_commands.command(name="status", description="Show Zos status summary")
    async def status(self, interaction: discord.Interaction) -> None:
        """Show salience summary and recent activity.

        Provides a window into Zos's current state:
        - Whether observation is silenced
        - Dev mode status
        - Placeholder for future: warm topics, recent layer runs, insight counts
        """
        if not await self.operator_check(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        # Current state flags
        is_silenced = self.bot.is_silenced
        dev_mode = self.bot.dev_mode

        # Format response
        # Note: Detailed status (warm topics, layer runs, insights) will be
        # implemented as database queries are added in Epic 3/4
        lines = [
            "**Zos Status**",
            "",
            f"Silenced: {'Yes' if is_silenced else 'No'}",
            f"Dev Mode: {'Enabled' if dev_mode else 'Disabled'}",
            "",
            "**Warm Topics:** (not yet implemented)",
            "**Recent Layer Runs:** (not yet implemented)",
            "**Total Insights:** (not yet implemented)",
        ]

        await interaction.followup.send("\n".join(lines), ephemeral=True)
        log.info("status_command", user=str(interaction.user))

    @app_commands.command(name="silence", description="Toggle observation pause")
    async def silence(self, interaction: discord.Interaction) -> None:
        """Pause or resume observation.

        When silenced, Zos stops ingesting new messages but remains
        connected to Discord. This is useful during maintenance or
        when the community needs quiet.
        """
        if not await self.operator_check(interaction):
            return

        self.bot.is_silenced = not self.bot.is_silenced
        state = "paused" if self.bot.is_silenced else "resumed"

        await interaction.response.send_message(
            f"Observation {state}.",
            ephemeral=True,
        )
        log.info("silence_toggled", state=state, user=str(interaction.user))

    @app_commands.command(
        name="reflect-now", description="Trigger reflection immediately"
    )
    async def reflect_now(self, interaction: discord.Interaction) -> None:
        """Manually trigger reflection cycle.

        This bypasses the scheduled reflection timing and runs
        reflection immediately. Useful for testing and after
        significant community events.

        Note: Full implementation in Epic 4.
        """
        if not await self.operator_check(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        # Placeholder for Epic 4 implementation
        # result = await self.bot.trigger_reflection()
        await interaction.followup.send(
            "Reflection trigger not yet implemented (Epic 4).\n"
            "This will run reflection layers on warm topics.",
            ephemeral=True,
        )
        log.info("reflect_now_command", user=str(interaction.user))

    @app_commands.command(name="insights", description="Query insights for a topic")
    @app_commands.describe(topic="Topic key (e.g., server:123:user:456)")
    async def insights(self, interaction: discord.Interaction, topic: str) -> None:
        """Query recent insights for a topic.

        Provides a view into Zos's accumulated understanding of a
        particular topic - what has been learned over time.

        Note: Full implementation in Epic 4.

        Args:
            topic: The topic key to query (e.g., server:123:user:456).
        """
        if not await self.operator_check(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        # Placeholder for Epic 4 implementation
        # insights = await self.db.get_insights_for_topic(topic, limit=5)
        await interaction.followup.send(
            f"Insights query not yet implemented (Epic 4).\n"
            f"Topic: `{topic}`\n\n"
            "This will show recent insights for the topic.",
            ephemeral=True,
        )
        log.info("insights_command", topic=topic, user=str(interaction.user))

    @app_commands.command(name="topics", description="List all topics with salience")
    async def topics(self, interaction: discord.Interaction) -> None:
        """List topics ordered by salience.

        Shows what Zos is currently paying attention to - which
        topics have accumulated enough activity to warrant reflection.

        Note: Full implementation in Epic 3.
        """
        if not await self.operator_check(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        # Placeholder for Epic 3 implementation
        # topics = await self.db.get_all_topics_with_salience(limit=20)
        await interaction.followup.send(
            "Topics listing not yet implemented (Epic 3).\n\n"
            "This will show topics ordered by salience balance.",
            ephemeral=True,
        )
        log.info("topics_command", user=str(interaction.user))

    @app_commands.command(
        name="layer-run", description="Manually run a specific layer"
    )
    @app_commands.describe(layer_name="Name of the layer to run")
    async def layer_run(
        self, interaction: discord.Interaction, layer_name: str
    ) -> None:
        """Manually trigger a specific layer.

        Runs a named layer outside of its scheduled time. Useful
        for testing layer changes or processing specific topics.

        Note: Full implementation in Epic 4.

        Args:
            layer_name: The name of the layer to run.
        """
        if not await self.operator_check(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        # Placeholder for Epic 4 implementation
        # if layer_name not in self.bot.available_layers:
        #     await interaction.followup.send(
        #         f"Unknown layer: `{layer_name}`\n"
        #         f"Available: {', '.join(self.bot.available_layers)}",
        #         ephemeral=True
        #     )
        #     return
        # result = await self.bot.run_layer(layer_name)

        await interaction.followup.send(
            f"Layer run not yet implemented (Epic 4).\n"
            f"Layer: `{layer_name}`\n\n"
            "This will execute the named layer manually.",
            ephemeral=True,
        )
        log.info("layer_run_command", layer_name=layer_name, user=str(interaction.user))

    @app_commands.command(name="dev-mode", description="Toggle dev mode")
    async def dev_mode(self, interaction: discord.Interaction) -> None:
        """Toggle dev mode (enables CRUD operations).

        Dev mode enables manual editing of insights and other
        development-only operations. Should not be enabled in
        production without good reason.
        """
        if not await self.operator_check(interaction):
            return

        self.bot.dev_mode = not self.bot.dev_mode
        state = "enabled" if self.bot.dev_mode else "disabled"

        await interaction.response.send_message(
            f"Dev mode {state}. "
            f"CRUD operations {'available' if self.bot.dev_mode else 'restricted'}.",
            ephemeral=True,
        )
        log.info("dev_mode_toggled", state=state, user=str(interaction.user))


async def setup(bot: ZosBot) -> None:
    """Setup function for loading the cog.

    Args:
        bot: The ZosBot instance to add the cog to.
    """
    await bot.add_cog(OperatorCommands(bot))
