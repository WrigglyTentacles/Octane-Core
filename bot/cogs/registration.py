"""Registration cog - /register, /profile. Epic linking is optional (future /link with manual approval)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import discord
from discord import app_commands

from bot.models import Player, init_db
from bot.models.base import get_async_session
from bot.services.rl_api import RLAPIService
import config


async def get_player(session: AsyncSession, discord_id: int) -> Optional[Player]:
    """Get player by Discord ID."""
    result = await session.execute(select(Player).where(Player.discord_id == discord_id))
    return result.scalar_one_or_none()


@app_commands.command(description="Register for tournaments (Discord only, no Epic required)")
async def register(interaction: discord.Interaction) -> None:
    """Register your Discord account for tournaments. MMR tracking is optional."""
    await interaction.response.defer(ephemeral=True)

    display_name = interaction.user.display_name or str(interaction.user)
    async for session in get_async_session():
        await init_db()
        existing = await get_player(session, interaction.user.id)
        if existing:
            existing.display_name = display_name
        else:
            session.add(
                Player(
                    discord_id=interaction.user.id,
                    display_name=display_name,
                )
            )
        await session.commit()
        break

    await interaction.followup.send(
        "You're registered! Use `/tournament register <id>` to sign up for tournaments. "
        "MMR lookup is optional — use `/mmrcheck [username]` to look up any Epic username.",
        ephemeral=True,
    )


@app_commands.command(description="View your profile and MMR (if Epic linked)")
async def profile(interaction: discord.Interaction) -> None:
    """Show profile. MMR only if Epic is linked (future /link)."""
    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        player = await get_player(session, interaction.user.id)
        if not player:
            await interaction.followup.send(
                "You haven't registered yet. Use `/register` to register for tournaments.",
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
                value="Not linked. Use `/mmrcheck [username]` to look up any player. Linking will be available via `/link` (manual approval).",
                inline=False,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)
        return


@app_commands.command(description="Look up MMR for an Epic username (no registration required)")
@app_commands.describe(username="Epic display name to look up")
async def mmrcheck(interaction: discord.Interaction, username: str) -> None:
    """Look up MMR for any Epic username. Does not require registration."""
    username = username.strip()
    if not username:
        await interaction.response.send_message("Please provide an Epic username.", ephemeral=True)
        return

    await interaction.response.defer()

    rl_service = RLAPIService(config.RLAPI_CLIENT_ID, config.RLAPI_CLIENT_SECRET)
    try:
        player_data = await rl_service.get_player_by_epic_name(username)
    finally:
        await rl_service.close()

    if not player_data:
        await interaction.followup.send(
            f"Could not find player **{username}** on Epic. Check the spelling or try again later.",
            ephemeral=True,
        )
        return

    mmr_info = rl_service.get_playlist_mmr(player_data, "doubles")
    if not mmr_info:
        await interaction.followup.send(
            f"Found **{player_data.user_name or username}** but no Doubles rank data.",
            ephemeral=True,
        )
        return

    skill, rank_str = mmr_info
    embed = discord.Embed(
        title=f"MMR — {player_data.user_name or username}",
        color=discord.Color.green(),
    )
    embed.add_field(name="Epic", value=player_data.user_name or username, inline=False)
    embed.add_field(name="Playlist", value="Doubles", inline=True)
    embed.add_field(name="Rank", value=rank_str, inline=True)
    embed.add_field(name="MMR", value=str(skill), inline=True)
    await interaction.followup.send(embed=embed)
