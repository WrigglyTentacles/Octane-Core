"""Tournaments cog - /tournament create, list, register, post, edit, delete."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import discord
from discord import app_commands

from bot.checks import admin_only, mod_or_higher
from bot.models import Player, Registration, Tournament, TournamentSignupMessage, init_db
from bot.models.base import get_async_session
from bot.services.rl_api import RLAPIService
import config

SIGNUP_EMOJI = "📝"  # React to sign up

FORMAT_CHOICES = [
    app_commands.Choice(name="1v1", value="1v1"),
    app_commands.Choice(name="2v2", value="2v2"),
    app_commands.Choice(name="3v3", value="3v3"),
    app_commands.Choice(name="4v4", value="4v4"),
    app_commands.Choice(name="Custom (e.g. 4v4)", value="custom"),
]

MMR_PLAYLIST_CHOICES = [
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
    result = await session.execute(select(Player).where(Player.discord_id == discord_id))
    return result.scalar_one_or_none()


async def get_tournament(session: AsyncSession, tournament_id: int, guild_id: int):
    result = await session.execute(
        select(Tournament).where(
            Tournament.id == tournament_id,
            Tournament.guild_id == guild_id,
        )
    )
    return result.scalar_one_or_none()


tournament_group = app_commands.Group(name="tournament", description="Tournament management")


@tournament_group.command(name="create", description="Create a new tournament (Moderator+)")
@app_commands.describe(
    name="Tournament name",
    format="1v1, 2v2, or 3v3",
    mmr_playlist="Playlist to use for MMR seeding",
)
@app_commands.choices(format=FORMAT_CHOICES, mmr_playlist=MMR_PLAYLIST_CHOICES)
@mod_or_higher()
async def create(
    interaction: discord.Interaction,
    name: str,
    format: str,
    mmr_playlist: str,
) -> None:
    """Create a tournament."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        await init_db()
        t = Tournament(
            guild_id=interaction.guild_id,
            name=name,
            format=format,
            mmr_playlist=mmr_playlist,
            status="open",
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)
        await interaction.followup.send(
            f"Created tournament **{name}** ({format}, MMR from {mmr_playlist}). ID: {t.id}",
            ephemeral=True,
        )
        return


@tournament_group.command(name="list", description="List tournaments in this server")
async def list_cmd(interaction: discord.Interaction) -> None:
    """List tournaments."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    await interaction.response.defer()

    async for session in get_async_session():
        result = await session.execute(
            select(Tournament).where(Tournament.guild_id == interaction.guild_id).order_by(Tournament.id.desc()).limit(10)
        )
        tournaments = result.scalars().all()
        if not tournaments:
            await interaction.followup.send("No tournaments found.")
            return
        lines = []
        for t in tournaments:
            lines.append(f"**{t.id}** — {t.name} ({t.format}, {t.mmr_playlist}) — {t.status}")
        embed = discord.Embed(title="Tournaments", description="\n".join(lines), color=discord.Color.blue())
        await interaction.followup.send(embed=embed)
        return


@tournament_group.command(name="register", description="Register for a tournament")
@app_commands.describe(tournament_id="Tournament ID to register for")
async def register_cmd(interaction: discord.Interaction, tournament_id: int) -> None:
    """Register for a tournament."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        await init_db()
        player = await get_player(session, interaction.user.id)
        if not player:
            await interaction.followup.send(
                "Register first with `/register`.",
                ephemeral=True,
            )
            return
        t = await get_tournament(session, tournament_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        if t.status != "open":
            await interaction.followup.send(f"Tournament is {t.status}, registration closed.", ephemeral=True)
            return
        existing = await session.execute(
            select(Registration).where(
                Registration.tournament_id == tournament_id,
                Registration.player_id == interaction.user.id,
            )
        )
        if existing.scalar_one_or_none():
            await interaction.followup.send("You're already registered.", ephemeral=True)
            return
        session.add(Registration(tournament_id=tournament_id, player_id=interaction.user.id))
        await session.commit()
        await interaction.followup.send(f"Registered for **{t.name}**!", ephemeral=True)
        return


@tournament_group.command(name="edit", description="Edit a tournament (Moderator+)")
@app_commands.describe(
    tournament_id="Tournament ID",
    name="New name (optional)",
    status="New status: open, closed, in_progress, completed",
)
@mod_or_higher()
async def edit(
    interaction: discord.Interaction,
    tournament_id: int,
    name: Optional[str] = None,
    status: Optional[str] = None,
) -> None:
    """Edit tournament."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        t = await get_tournament(session, tournament_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        if name:
            t.name = name
        if status:
            t.status = status
        await session.commit()
        await interaction.followup.send(f"Updated tournament **{t.name}**.", ephemeral=True)
        return


@tournament_group.command(name="delete", description="Delete a tournament (Admin only)")
@app_commands.describe(tournament_id="Tournament ID to delete")
@admin_only()
async def delete(interaction: discord.Interaction, tournament_id: int) -> None:
    """Delete tournament."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        t = await get_tournament(session, tournament_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        name = t.name
        await session.delete(t)
        await session.commit()
        await interaction.followup.send(f"Deleted tournament **{name}**.", ephemeral=True)
        return
