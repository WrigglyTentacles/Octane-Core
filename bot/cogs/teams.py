"""Teams cog - /team add, remove, update, list (Moderator+ for add/remove/update)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import discord
from discord import app_commands

from bot.checks import mod_or_higher
from bot.models import Player, Registration, Team, Tournament, init_db
from bot.models.base import get_async_session


async def get_tournament(session: AsyncSession, tournament_id: int, guild_id: int):
    result = await session.execute(
        select(Tournament).where(
            Tournament.id == tournament_id,
            Tournament.guild_id == guild_id,
        )
    )
    return result.scalar_one_or_none()


async def get_player(session: AsyncSession, discord_id: int):
    result = await session.execute(select(Player).where(Player.discord_id == discord_id))
    return result.scalar_one_or_none()


team_group = app_commands.Group(name="team", description="Team management for 2v2/3v3")


@team_group.command(name="list", description="List teams for a tournament")
@app_commands.describe(tournament_id="Tournament ID")
async def list_cmd(interaction: discord.Interaction, tournament_id: int) -> None:
    """List teams."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    await interaction.response.defer()

    async for session in get_async_session():
        await init_db()
        t = await get_tournament(session, tournament_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.")
            return
        result = await session.execute(
            select(Team).where(Team.tournament_id == tournament_id).options(selectinload(Team.members).selectinload(Registration.player))
        )
        teams = result.scalars().all()
        if not teams:
            await interaction.followup.send("No teams yet. Use `/team add` to create teams.")
            return
        lines = []
        for team in teams:
            members = [reg.player.display_name or str(reg.player.discord_id) for reg in team.members]
            lines.append(f"**{team.name}**: {', '.join(members) or '—'}")
        embed = discord.Embed(title=f"Teams — {t.name}", description="\n".join(lines), color=discord.Color.green())
        await interaction.followup.send(embed=embed)
        return


@team_group.command(name="add", description="Add a player to a team (Moderator+)")
@app_commands.describe(
    tournament_id="Tournament ID",
    team_name="Team name",
    player="Player to add",
)
@mod_or_higher()
async def add(
    interaction: discord.Interaction,
    tournament_id: int,
    team_name: str,
    player: discord.Member,
) -> None:
    """Add player to team."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        await init_db()
        t = await get_tournament(session, tournament_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        p = await get_player(session, player.id)
        if not p:
            await interaction.followup.send(f"{player.mention} hasn't registered yet. Use `/register` first.", ephemeral=True)
            return
        result = await session.execute(
            select(Team).where(
                Team.tournament_id == tournament_id,
                Team.name == team_name,
            )
        )
        team = result.scalar_one_or_none()
        if not team:
            team = Team(tournament_id=tournament_id, name=team_name)
            session.add(team)
            await session.flush()
        reg = await session.execute(
            select(Registration).where(
                Registration.tournament_id == tournament_id,
                Registration.player_id == player.id,
            )
        )
        reg = reg.scalar_one_or_none()
        if not reg:
            reg = Registration(tournament_id=tournament_id, player_id=player.id, team_id=team.id)
            session.add(reg)
        else:
            reg.team_id = team.id
        await session.commit()
        await interaction.followup.send(f"Added {player.display_name} to **{team_name}**.", ephemeral=True)
        return


@team_group.command(name="remove", description="Remove a player from a team (Moderator+)")
@app_commands.describe(
    tournament_id="Tournament ID",
    team_name="Team name",
    player="Player to remove",
)
@mod_or_higher()
async def remove(
    interaction: discord.Interaction,
    tournament_id: int,
    team_name: str,
    player: discord.Member,
) -> None:
    """Remove player from team."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        t = await get_tournament(session, tournament_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        result = await session.execute(
            select(Team).where(
                Team.tournament_id == tournament_id,
                Team.name == team_name,
            )
        )
        team = result.scalar_one_or_none()
        if not team:
            await interaction.followup.send("Team not found.", ephemeral=True)
            return
        reg = await session.execute(
            select(Registration).where(
                Registration.tournament_id == tournament_id,
                Registration.player_id == player.id,
                Registration.team_id == team.id,
            )
        )
        reg = reg.scalar_one_or_none()
        if not reg:
            await interaction.followup.send(f"{player.display_name} is not in that team.", ephemeral=True)
            return
        reg.team_id = None
        await session.commit()
        await interaction.followup.send(f"Removed {player.display_name} from **{team_name}**.", ephemeral=True)
        return


@team_group.command(name="update", description="Substitute a player (Moderator+)")
@app_commands.describe(
    tournament_id="Tournament ID",
    team_name="Team name",
    player="Player to replace",
    replacement="Replacement player",
)
@mod_or_higher()
async def update(
    interaction: discord.Interaction,
    tournament_id: int,
    team_name: str,
    player: discord.Member,
    replacement: discord.Member,
) -> None:
    """Substitute player."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        t = await get_tournament(session, tournament_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        rep = await get_player(session, replacement.id)
        if not rep:
            await interaction.followup.send(f"{replacement.mention} hasn't registered an Epic ID.", ephemeral=True)
            return
        result = await session.execute(
            select(Team).where(
                Team.tournament_id == tournament_id,
                Team.name == team_name,
            )
        )
        team = result.scalar_one_or_none()
        if not team:
            await interaction.followup.send("Team not found.", ephemeral=True)
            return
        reg = await session.execute(
            select(Registration).where(
                Registration.tournament_id == tournament_id,
                Registration.player_id == player.id,
                Registration.team_id == team.id,
            )
        )
        reg = reg.scalar_one_or_none()
        if not reg:
            await interaction.followup.send(f"{player.display_name} is not in that team.", ephemeral=True)
            return
        reg.player_id = replacement.id
        await session.commit()
        await interaction.followup.send(f"Replaced {player.display_name} with {replacement.display_name} in **{team_name}**.", ephemeral=True)
        return
