"""Registration cog - /profile. Epic linking is optional (future /link with manual approval)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import discord
from discord import app_commands

from bot.models import Player
from bot.models.base import get_async_session
from bot.services.rl_api import RLAPIService
import config

RLAPI_ERROR_MSG = "MMR lookup is unavailable. Check RLAPI_CLIENT_ID and RLAPI_CLIENT_SECRET in .env (Epic Developer Portal)."


async def get_player(session: AsyncSession, discord_id: int) -> Optional[Player]:
    """Get player by Discord ID."""
    result = await session.execute(select(Player).where(Player.discord_id == discord_id))
    return result.scalar_one_or_none()


@app_commands.command(description="View your profile and MMR (if Epic linked)")
async def profile(interaction: discord.Interaction) -> None:
    """Show profile. MMR only if Epic is linked (future /link)."""
    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        player = await get_player(session, interaction.user.id)
        if not player:
            await interaction.followup.send(
                "You don't have a profile yet. React to a signup post or use `/tournament register` to join a tournament — a profile is created automatically.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="Your Profile",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Discord", value=player.display_name or str(interaction.user), inline=False)

        # MMR only if Epic is linked
        if player.epic_id or player.epic_username:
            rl_service = RLAPIService(config.RLAPI_CLIENT_ID, config.RLAPI_CLIENT_SECRET)
            try:
                player_data = None
                if player.epic_id:
                    player_data = await rl_service.get_player_by_epic_id(player.epic_id)
                elif player.epic_username:
                    player_data = await rl_service.get_player_by_epic_name(player.epic_username)
                if player_data:
                    mmr_info = rl_service.get_playlist_mmr(player_data, "doubles")
                    mmr_str = f"Doubles: {mmr_info[1]} ({mmr_info[0]} MMR)" if mmr_info else "No ranked data"
                else:
                    mmr_str = "Could not fetch MMR"
            finally:
                await rl_service.close()
            embed.add_field(name="Epic", value=player.epic_username or player.epic_id or "—", inline=False)
            embed.add_field(name="MMR (Doubles)", value=mmr_str, inline=False)
        else:
            embed.add_field(
                name="Epic",
                value="Not linked. Linking will be available via `/link` (manual approval) in a future update.",
                inline=False,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)
        return
