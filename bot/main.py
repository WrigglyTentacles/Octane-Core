"""Main bot entry point."""
import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from bot.checks import admin_only, mod_or_higher
from bot.cogs import registration, mmr, tournaments, teams, brackets, config_cog
from bot.listeners import signup
from bot.models import init_db
from bot.services.rl_api import RLAPIService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("octane")

intents = discord.Intents.default()
intents.members = True  # Required to see member roles in slash commands; enable in Developer Portal → Bot → Server Members Intent


class OctaneBot(commands.Bot):
    """Octane-Core Discord bot."""

    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            chunk_guilds_at_startup=True,  # Populate member cache so role checks work
        )
        self.rl_service = None

    async def on_ready(self) -> None:
        logger.info("Bot ready: %s (ID: %s)", self.user, self.user.id if self.user else "?")
        # Guild-specific sync: commands appear instantly instead of waiting for global propagation
        guilds = list(self.guilds)
        logger.info("Syncing commands to %d guild(s)", len(guilds))
        for guild in guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                logger.info("Commands synced to guild: %s (%s)", guild.name, guild.id)
            except Exception as e:
                logger.warning("Failed to sync to guild %s: %s", guild.name, e)

    async def setup_hook(self) -> None:
        """Setup on bot ready."""
        await init_db()
        self.rl_service = RLAPIService(config.RLAPI_CLIENT_ID, config.RLAPI_CLIENT_SECRET)

        # Add commands
        self.tree.add_command(registration.register)
        self.tree.add_command(registration.profile)
        self.tree.add_command(registration.mmrcheck)
        self.tree.add_command(mmr.mmr)
        self.tree.add_command(mmr.leaderboard)
        self.tree.add_command(tournaments.tournament_group)
        self.tree.add_command(teams.team_group)
        self.tree.add_command(brackets.bracket_group)
        self.tree.add_command(config_cog.debug_roles)
        self.tree.add_command(config_cog.sync)

        # Sync commands
        await self.tree.sync()
        logger.info("Commands synced")

        # Global error handler: always respond so Discord doesn't show "application did not respond"
        async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
            msg = "Something went wrong. Check bot logs."
            if isinstance(error, app_commands.errors.CheckFailure):
                msg = "You don't have permission to use this command. (Need Tournament Commissioner or Admin role)"
            else:
                logger.exception("Command error: %s", error)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass

        self.tree.on_error = on_app_command_error

        # Reaction-based signup
        signup.setup(self)

    async def close(self) -> None:
        """Cleanup on shutdown."""
        if self.rl_service:
            await self.rl_service.close()
        await super().close()


def main() -> None:
    """Run the bot."""
    if not config.DISCORD_TOKEN:
        raise ValueError("DISCORD_TOKEN is required")
    if not config.RLAPI_CLIENT_ID or not config.RLAPI_CLIENT_SECRET:
        logger.warning("RLAPI credentials not set - MMR/registration features will fail")

    bot = OctaneBot()
    bot.run(config.DISCORD_TOKEN)


if __name__ == "__main__":
    main()
