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

from zos.insights import get_insights_for_topic
from zos.layers import LayerCategory
from zos.logging import get_logger
from zos.salience import BudgetGroup, SalienceLedger, get_budget_group

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
        - Top topics by salience
        - Total insights accumulated
        """
        if not await self.operator_check(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        # Current state flags
        is_silenced = self.bot.is_silenced
        dev_mode = self.bot.dev_mode

        lines = [
            "**Zos Status**",
            "",
            f"Silenced: {'Yes' if is_silenced else 'No'}",
            f"Dev Mode: {'Enabled' if dev_mode else 'Disabled'}",
            "",
        ]

        # Get warm topics if database is available
        if self.bot.engine:
            try:
                from sqlalchemy import select, func
                from zos.database import insights as insights_table

                ledger = SalienceLedger(self.bot.engine, self.config)
                topics_with_balance = await ledger.get_top_topics(group=None, limit=5)

                if topics_with_balance:
                    lines.append("**Warm Topics:**")
                    for topic_data in topics_with_balance:
                        display_key = topic_data.key
                        if len(display_key) > 40:
                            display_key = display_key[:37] + "..."
                        lines.append(f"  • `{display_key}` ({topic_data.balance:.1f})")
                else:
                    lines.append("**Warm Topics:** None yet")

                # Get total insight count
                async with self.bot.engine.begin() as conn:
                    result = await conn.execute(
                        select(func.count()).select_from(insights_table)
                    )
                    insight_count = result.scalar() or 0
                    lines.append("")
                    lines.append(f"**Total Insights:** {insight_count}")

            except Exception as e:
                log.error("status_query_failed", error=str(e))
                lines.append("")
                lines.append("**Warm Topics:** (query failed)")
                lines.append("**Total Insights:** (query failed)")
        else:
            lines.append("**Warm Topics:** (database not available)")
            lines.append("**Total Insights:** (database not available)")

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
        """
        if not await self.operator_check(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        # Check if scheduler is available
        if not self.bot.scheduler:
            await interaction.followup.send(
                "❌ Reflection not available.\n"
                "Scheduler not initialized. Use `zos serve` to run with reflection support.",
                ephemeral=True,
            )
            return

        log.info("reflect_now_command", user=str(interaction.user))

        # Get all scheduled layers, ordered so self-reflection runs last
        # (mirroring the cron schedule where entity layers run at 3 AM
        # and self/synthesis run at 4 AM, ensuring prior insights exist)
        _CATEGORY_ORDER = {
            LayerCategory.USER: 0,
            LayerCategory.DYAD: 0,
            LayerCategory.CHANNEL: 0,
            LayerCategory.SUBJECT: 1,
            LayerCategory.SYNTHESIS: 2,
            LayerCategory.SELF: 3,
        }

        try:
            layers = self.bot.scheduler.loader.load_all()
            scheduled_layers = sorted(
                [
                    (name, layer)
                    for name, layer in layers.items()
                    if layer.schedule
                ],
                key=lambda pair: _CATEGORY_ORDER.get(pair[1].category, 1),
            )

            if not scheduled_layers:
                await interaction.followup.send(
                    "No scheduled reflection layers found.",
                    ephemeral=True,
                )
                return

            # Trigger each scheduled layer sequentially
            results = []
            for layer_name, layer in scheduled_layers:
                run = await self.bot.scheduler.trigger_now(layer_name)
                if run:
                    results.append((layer_name, run))

            # Format results
            if not results:
                message = "✅ Reflection triggered, but no topics had sufficient salience."
            else:
                lines = ["✅ Reflection completed:\n"]
                for layer_name, run in results:
                    lines.append(f"**{layer_name}**")
                    lines.append(f"  • Status: {run.status.value}")
                    lines.append(f"  • Targets processed: {run.targets_processed}")
                    lines.append(f"  • Insights created: {run.insights_created}")
                    if run.tokens_total:
                        lines.append(f"  • Tokens: {run.tokens_total}")
                    if run.estimated_cost_usd:
                        lines.append(f"  • Cost: ${run.estimated_cost_usd:.4f}")
                    lines.append("")

                message = "\n".join(lines)

            await interaction.followup.send(message, ephemeral=True)

        except Exception as e:
            log.error("reflect_now_failed", error=str(e), user=str(interaction.user))
            await interaction.followup.send(
                f"❌ Reflection failed: {str(e)}",
                ephemeral=True,
            )

    @app_commands.command(name="insights", description="Query insights for a topic")
    @app_commands.describe(topic="Topic key (e.g., server:123:user:456)")
    async def insights(self, interaction: discord.Interaction, topic: str) -> None:
        """Query recent insights for a topic.

        Provides a view into Zos's accumulated understanding of a
        particular topic - what has been learned over time.

        Args:
            topic: The topic key to query (e.g., server:123:user:456).
        """
        if not await self.operator_check(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        # Get insights for the topic
        if not self.bot.engine:
            await interaction.followup.send(
                "❌ Database not available.",
                ephemeral=True,
            )
            return

        insights = await get_insights_for_topic(
            self.bot.engine, self.config, topic, limit=5
        )

        if not insights:
            await interaction.followup.send(
                f"No insights found for topic: `{topic}`",
                ephemeral=True,
            )
            return

        # Format the response
        lines = [f"**Insights for Topic:** `{topic}`", ""]
        for insight in insights:
            # Truncate long insights for Discord message limits
            content = insight.content
            if len(content) > 200:
                content = content[:197] + "..."

            timestamp = insight.created_at.strftime("%Y-%m-%d %H:%M")
            lines.append(
                f"**{insight.category}** ({timestamp})\n"
                f"{content}\n"
            )

        await interaction.followup.send("\n".join(lines), ephemeral=True)
        log.info("insights_command", topic=topic, user=str(interaction.user), insight_count=len(insights))

    @app_commands.command(name="topics", description="List all topics with salience")
    async def topics(self, interaction: discord.Interaction) -> None:
        """List topics ordered by salience.

        Shows what Zos is currently paying attention to - which
        topics have accumulated enough activity to warrant reflection.
        """
        if not await self.operator_check(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        # Get the salience ledger
        if not self.bot.engine:
            await interaction.followup.send(
                "❌ Database not available.",
                ephemeral=True,
            )
            return

        ledger = SalienceLedger(self.bot.engine, self.config)

        # Get top topics across all groups
        topics_with_balance = await ledger.get_top_topics(group=None, limit=20)

        if not topics_with_balance:
            await interaction.followup.send(
                "No topics with salience found.",
                ephemeral=True,
            )
            return

        # Format the response
        lines = ["**Top Topics by Salience**", ""]
        for topic_data in topics_with_balance:
            budget_group = get_budget_group(topic_data.key)
            cap = ledger.get_cap(topic_data.key)
            utilization = (topic_data.balance / cap * 100) if cap > 0 else 0

            # Truncate long topic keys for readability
            display_key = topic_data.key
            if len(display_key) > 50:
                display_key = display_key[:47] + "..."

            lines.append(
                f"• `{display_key}`\n"
                f"  Balance: {topic_data.balance:.1f}/{cap:.1f} ({utilization:.0f}%) • "
                f"Group: {budget_group.value}"
            )

        await interaction.followup.send("\n".join(lines), ephemeral=True)
        log.info("topics_command", user=str(interaction.user), topic_count=len(topics_with_balance))

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

        Args:
            layer_name: The name of the layer to run.
        """
        if not await self.operator_check(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        # Check if scheduler is available
        if not self.bot.scheduler:
            await interaction.followup.send(
                "❌ Reflection scheduler not available.",
                ephemeral=True,
            )
            return

        # Get all available layers
        try:
            layers = self.bot.scheduler.loader.load_all()
            available_layer_names = [name for name, _ in layers]
        except Exception as e:
            await interaction.followup.send(
                f"❌ Failed to load layers: {e}",
                ephemeral=True,
            )
            log.error("layer_run_load_failed", error=str(e))
            return

        # Check if the layer exists
        if layer_name not in available_layer_names:
            await interaction.followup.send(
                f"❌ Unknown layer: `{layer_name}`\n\n"
                f"Available layers: {', '.join(f'`{name}`' for name in available_layer_names)}",
                ephemeral=True,
            )
            return

        # Trigger the layer
        try:
            run = await self.bot.scheduler.trigger_now(layer_name)
            if run:
                await interaction.followup.send(
                    f"✅ Layer `{layer_name}` executed successfully.\n\n"
                    f"Run ID: `{run.id}`\n"
                    f"Insights generated: {run.insight_count}",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"⚠️ Layer `{layer_name}` execution completed but returned no result.",
                    ephemeral=True,
                )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Failed to run layer `{layer_name}`: {e}",
                ephemeral=True,
            )
            log.error("layer_run_failed", layer_name=layer_name, error=str(e))
            return

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
