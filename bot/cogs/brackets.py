"""Brackets cog - /bracket generate, view, update (Moderator+ for generate/update)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import discord
from discord import app_commands

from bot.checks import mod_or_higher
from bot.models import Bracket, BracketMatch, Player, Registration, Team, Tournament
from bot.models.base import get_async_session
from bot.services.bracket_gen import create_single_elim_bracket
from bot.services.rl_api import RLAPIService
import config


async def get_tournament(session: AsyncSession, tournament_id: int, guild_id: int):
    result = await session.execute(
        select(Tournament).where(
            Tournament.id == tournament_id,
            Tournament.guild_id == guild_id,
        )
    )
    return result.scalar_one_or_none()


async def resolve_entity(session: AsyncSession, entity_id: int, is_team: bool) -> str:
    """Resolve player or team ID to display name."""
    if is_team:
        result = await session.execute(
            select(Team).where(Team.id == entity_id).options(selectinload(Team.members).selectinload(Registration.player))
        )
        team = result.scalar_one_or_none()
        if team:
            members = [m.player.display_name or str(m.player.discord_id) for m in team.members]
            return team.name + " (" + ", ".join(members) + ")"
        return f"Team #{entity_id}"
    else:
        player = await session.get(Player, entity_id)
        if player:
            return player.display_name or str(player.discord_id)
        return f"Player #{entity_id}"


bracket_group = app_commands.Group(name="bracket", description="Bracket management")


@bracket_group.command(name="generate", description="Generate bracket from registrations (Moderator+)")
@app_commands.describe(tournament_id="Tournament ID")
@mod_or_higher()
async def generate(interaction: discord.Interaction, tournament_id: int) -> None:
    """Generate bracket."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    rl_service = RLAPIService(config.RLAPI_CLIENT_ID, config.RLAPI_CLIENT_SECRET)
    try:
        async for session in get_async_session():
            t = await get_tournament(session, tournament_id, interaction.guild_id)
            if not t:
                await interaction.followup.send("Tournament not found.", ephemeral=True)
                return
            existing = await session.execute(
                select(Bracket).where(Bracket.tournament_id == tournament_id)
            )
            if existing.scalar_one_or_none():
                await interaction.followup.send("Bracket already exists for this tournament.", ephemeral=True)
                return
            bracket = await create_single_elim_bracket(session, tournament_id, rl_service)
            if not bracket:
                await interaction.followup.send(
                    "Could not generate bracket. Ensure players/teams are registered and have MMR data.",
                    ephemeral=True,
                )
                return
            await interaction.followup.send(
                f"Generated bracket for **{t.name}** with {len(bracket.matches)} matches.",
                ephemeral=True,
            )
            return
    finally:
        await rl_service.close()


@bracket_group.command(name="view", description="View bracket")
@app_commands.describe(tournament_id="Tournament ID")
async def view(interaction: discord.Interaction, tournament_id: int) -> None:
    """View bracket."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    await interaction.response.defer()

    async for session in get_async_session():
        t = await get_tournament(session, tournament_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.")
            return
        result = await session.execute(
            select(Bracket).where(Bracket.tournament_id == tournament_id)
        )
        bracket = result.scalar_one_or_none()
        if not bracket:
            await interaction.followup.send("No bracket generated yet. Use `/bracket generate`.")
            return
        matches_result = await session.execute(
            select(BracketMatch)
            .where(BracketMatch.bracket_id == bracket.id)
            .order_by(BracketMatch.round_num, BracketMatch.match_num)
        )
        matches = matches_result.scalars().all()
        is_team = t.format != "1v1"
        by_round = {}
        for m in matches:
            r = m.round_num
            if r not in by_round:
                by_round[r] = []
            if is_team:
                t1 = await resolve_entity(session, m.team1_id, True) if m.team1_id else "TBD"
                t2 = await resolve_entity(session, m.team2_id, True) if m.team2_id else "TBD"
            else:
                t1 = await resolve_entity(session, m.player1_id, False) if m.player1_id else "TBD"
                t2 = await resolve_entity(session, m.player2_id, False) if m.player2_id else "TBD"
            winner = ""
            if m.winner_team_id:
                winner = " → " + (await resolve_entity(session, m.winner_team_id, True))
            elif m.winner_player_id:
                winner = " → " + (await resolve_entity(session, m.winner_player_id, False))
            by_round[r].append(f"[{m.id}] Match {m.match_num}: {t1} vs {t2}{winner}")
        embed = discord.Embed(title=f"Bracket — {t.name}", color=discord.Color.purple())
        for r in sorted(by_round.keys()):
            embed.add_field(name=f"Round {r}", value="\n".join(by_round[r]), inline=False)
        await interaction.followup.send(embed=embed)
        return


@bracket_group.command(name="update", description="Record match winner (Moderator+)")
@app_commands.describe(
    match_id="Match ID (from bracket view)",
    winner_slot="1 or 2 for team1/player1 or team2/player2",
)
@mod_or_higher()
async def update(
    interaction: discord.Interaction,
    match_id: int,
    winner_slot: int,
) -> None:
    """Record match winner."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    if winner_slot not in (1, 2):
        await interaction.response.send_message("winner_slot must be 1 or 2.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        match = await session.get(BracketMatch, match_id)
        if not match:
            await interaction.followup.send("Match not found.", ephemeral=True)
            return
        bracket = await session.get(Bracket, match.bracket_id)
        if not bracket:
            await interaction.followup.send("Bracket not found.", ephemeral=True)
            return
        t = await get_tournament(session, bracket.tournament_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        is_team = t.format != "1v1"
        if winner_slot == 1:
            match.winner_team_id = match.team1_id if is_team else None
            match.winner_player_id = match.player1_id if not is_team else None
        else:
            match.winner_team_id = match.team2_id if is_team else None
            match.winner_player_id = match.player2_id if not is_team else None
        await session.commit()
        winner_name = await resolve_entity(
            session,
            match.winner_team_id or match.winner_player_id,
            is_team,
        )
        await interaction.followup.send(f"Recorded winner: **{winner_name}**", ephemeral=True)
        return
