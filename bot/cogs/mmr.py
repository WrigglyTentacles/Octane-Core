"""MMR cog - /mmr, /leaderboard."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import discord
from discord import app_commands

from bot.models import Player, Registration, Tournament, init_db
from bot.models.base import get_async_session
from bot.services.rl_api import RLAPIService
import config

PLAYLIST_CHOICES = [
    app_commands.Choice(name="Solo Duel", value="solo_duel"),
    app_commands.Choice(name="Doubles", value="doubles"),
    app_commands.Choice(name="Standard", value="standard"),
    app_commands.Choice(name="Hoops", value="hoops"),
    app_commands.Choice(name="Rumble", value="rumble"),
    app_commands.Choice(name="Dropshot", value="dropshot"),
    app_commands.Choice(name="Snow Day", value="snow_day"),
    app_commands.Choice(name="Tournaments", value="tournaments"),
]


async def get_player(session: AsyncSession, discord_id: int):
    """Get player by Discord ID."""
    result = await session.execute(select(Player).where(Player.discord_id == discord_id))
    return result.scalar_one_or_none()


@app_commands.command(description="Show MMR and rank for a player")
@app_commands.describe(
    user="User to check (default: yourself)",
    playlist="Playlist to show MMR for (default: doubles)",
)
async def mmr(
    interaction: discord.Interaction,
    user: Optional[discord.Member] = None,
    playlist: str = "doubles",
) -> None:
    """Show MMR and rank."""
    target = user or interaction.user
    await interaction.response.defer()

    async for session in get_async_session():
        player = await get_player(session, target.id)
        if not player:
            await interaction.followup.send(
                f"{target.mention} hasn't registered an Epic ID yet." if user else "You haven't registered yet. Use `/register epic_id` first.",
                ephemeral=not user,
            )
            return

        rl_service = RLAPIService(config.RLAPI_CLIENT_ID, config.RLAPI_CLIENT_SECRET)
        try:
            player_data = await rl_service.get_player_by_epic_id(player.epic_id)
            if not player_data:
                await interaction.followup.send("Could not fetch player data from Rocket League API.")
                return
            mmr_info = rl_service.get_playlist_mmr(player_data, playlist)
        finally:
            await rl_service.close()

        if not mmr_info:
            await interaction.followup.send(f"No {playlist} rank data found.")
            return

        skill, rank_str = mmr_info
        embed = discord.Embed(
            title=f"MMR — {target.display_name}",
            color=discord.Color.green(),
        )
        embed.add_field(name="Playlist", value=playlist.replace("_", " ").title(), inline=True)
        embed.add_field(name="Rank", value=rank_str, inline=True)
        embed.add_field(name="MMR", value=str(skill), inline=True)
        await interaction.followup.send(embed=embed)
        return


@app_commands.command(description="Show leaderboard of registered players for a tournament")
@app_commands.describe(tournament="Tournament name or ID")
async def leaderboard(interaction: discord.Interaction, tournament: str) -> None:
    """Show leaderboard by MMR for a tournament."""
    if not interaction.guild_id:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    await interaction.response.defer()

    async for session in get_async_session():
        # Find tournament by id or name
        try:
            tid = int(tournament)
            result = await session.execute(
                select(Tournament).where(Tournament.id == tid, Tournament.guild_id == interaction.guild_id)
            )
        except ValueError:
            result = await session.execute(
                select(Tournament).where(
                    Tournament.name.ilike(f"%{tournament}%"),
                    Tournament.guild_id == interaction.guild_id,
                )
            )
        t = result.scalar_one_or_none()
        if not t:
            await interaction.followup.send("Tournament not found.")
            return

        regs = await session.execute(
            select(Registration)
            .where(Registration.tournament_id == t.id)
            .options(selectinload(Registration.player))
        )
        regs = regs.scalars().all()
        if not regs:
            await interaction.followup.send("No registrations for this tournament yet.")
            return

        rl_service = RLAPIService(config.RLAPI_CLIENT_ID, config.RLAPI_CLIENT_SECRET)
        mmr_list: list[tuple[Player, int]] = []
        try:
            for reg in regs:
                player_data = await rl_service.get_player_by_epic_id(reg.player.epic_id)
                if player_data:
                    info = rl_service.get_playlist_mmr(player_data, t.mmr_playlist)
                    if info:
                        mmr_list.append((reg.player, info[0]))
        finally:
            await rl_service.close()

        mmr_list.sort(key=lambda x: x[1], reverse=True)

        lines = []
        for i, (p, skill) in enumerate(mmr_list, 1):
            name = p.display_name or str(p.discord_id)
            lines.append(f"{i}. **{name}** — {skill} MMR")

        embed = discord.Embed(
            title=f"Leaderboard — {t.name}",
            description="\n".join(lines[:20]) or "No MMR data",
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"Playlist: {t.mmr_playlist}")
        await interaction.followup.send(embed=embed)
        return
