"""Main bot entry point."""
import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from bot.checks import admin_only, mod_or_higher
from bot.cogs import registration, mmr, tournaments, teams, brackets, config_cog
from bot.models import init_db
from bot.services.rl_api import RLAPIService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("octane")

intents = discord.Intents.default()
intents.members = True
intents.guilds = True


class OctaneBot(commands.Bot):
    """Octane-Core Discord bot."""

    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
        )
        self.rl_service = None

    async def setup_hook(self) -> None:
        """Setup on bot ready."""
        await init_db()
        self.rl_service = RLAPIService(config.RLAPI_CLIENT_ID, config.RLAPI_CLIENT_SECRET)

        # Add commands
        self.tree.add_command(registration.register)
        self.tree.add_command(registration.profile)
        self.tree.add_command(registration.update_epic)
        self.tree.add_command(mmr.mmr)
        self.tree.add_command(mmr.leaderboard)
        self.tree.add_command(tournaments.tournament_group)
        self.tree.add_command(teams.team_group)
        self.tree.add_command(brackets.bracket_group)

        # Sync commands
        await self.tree.sync()
        logger.info("Commands synced")

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
