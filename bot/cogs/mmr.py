"""MMR cog - /mmr, /leaderboard."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import discord
from discord import app_commands

from bot.models import Player, Registration, Tournament
from bot.models.base import get_async_session
from bot.services.rl_api import RLAPIService
import config

RLAPI_ERROR_MSG = "MMR lookup is unavailable. Check RLAPI_CLIENT_ID and RLAPI_CLIENT_SECRET in .env (Epic Developer Portal)."

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


@app_commands.command(description="Show MMR for a linked user (use /mmrcheck for any Epic username)")
@app_commands.describe(
    user="User to check (must have Epic linked)",
    playlist="Playlist to show MMR for (default: doubles)",
)
async def mmr(
    interaction: discord.Interaction,
    user: Optional[discord.Member] = None,
    playlist: str = "doubles",
) -> None:
    """Show MMR for a user with Epic linked. Use /mmrcheck [username] to look up any Epic username."""
    await interaction.response.defer()

    target = user or interaction.user
    async for session in get_async_session():
        player = await get_player(session, target.id)
        if not player:
            await interaction.followup.send(
                f"{target.mention} hasn't registered yet." if user else "You haven't registered. Use `/register` first.",
                ephemeral=not user,
            )
            return
        if not player.epic_id and not player.epic_username:
            await interaction.followup.send(
                f"{target.mention} doesn't have Epic linked. Use `/mmrcheck [username]` to look up any player.",
                ephemeral=not user,
            )
            return
        break

    rl_service = RLAPIService(config.RLAPI_CLIENT_ID, config.RLAPI_CLIENT_SECRET)
    try:
        player_data = await rl_service.get_player_data(
            epic_id=player.epic_id, epic_username=player.epic_username
        )
        if not player_data:
            await interaction.followup.send("Could not fetch player data. The Epic account may have changed.")
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
    embed.add_field(name="Epic", value=player_data.user_name or "—", inline=False)
    embed.add_field(name="Playlist", value=playlist.replace("_", " ").title(), inline=True)
    embed.add_field(name="Rank", value=rank_str, inline=True)
    embed.add_field(name="MMR", value=str(skill), inline=True)
    await interaction.followup.send(embed=embed)


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
        mmr_list: list[tuple[Player, int | None]] = []
        try:
            for reg in regs:
                try:
                    player_data = await rl_service.get_player_data(
                        epic_id=reg.player.epic_id, epic_username=reg.player.epic_username
                    )
                    if player_data:
                        info = rl_service.get_playlist_mmr(player_data, t.mmr_playlist)
                        mmr_list.append((reg.player, info[0] if info else None))
                    else:
                        mmr_list.append((reg.player, None))
                except (Exception, KeyError):
                    mmr_list.append((reg.player, None))  # Skip MMR for this player
        finally:
            await rl_service.close()

        mmr_list.sort(key=lambda x: (x[1] is None, -(x[1] or 0)))  # None last, then by MMR desc

        lines = []
        for i, (p, skill) in enumerate(mmr_list, 1):
            name = p.display_name or str(p.discord_id)
            mmr_str = f"{skill} MMR" if skill is not None else "—"
            lines.append(f"{i}. **{name}** — {mmr_str}")

        embed = discord.Embed(
            title=f"Leaderboard — {t.name}",
            description="\n".join(lines[:20]) or "No MMR data",
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"Playlist: {t.mmr_playlist}")
        await interaction.followup.send(embed=embed)
        return
