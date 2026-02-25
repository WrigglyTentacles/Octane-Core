"""Shared Discord embed-building and entity resolution for bracket displays."""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import discord

from bot.models import (
    BracketMatch,
    Player,
    Registration,
    Team,
    TeamManualMember,
    TournamentManualEntry,
)


async def resolve_entity(
    session: AsyncSession,
    entity_id: int,
    is_team: bool,
    guild: discord.Guild | None = None,
    client: discord.Client | None = None,
) -> str:
    """Resolve player or team ID to display name. When guild/client provided, fetches from Discord if DB has none."""

    async def _fetch_discord_name(uid: int) -> str | None:
        """Try guild fetch first, then global fetch. Returns display name or None."""
        if guild:
            try:
                mem = await guild.fetch_member(uid)
                if mem:
                    return mem.display_name or mem.name
            except (discord.NotFound, discord.HTTPException):
                pass
        if client:
            try:
                user = await client.fetch_user(uid)
                if user:
                    return user.display_name or user.name
            except (discord.NotFound, discord.HTTPException):
                pass
        return None

    if is_team:
        result = await session.execute(
            select(Team)
            .where(Team.id == entity_id)
            .options(
                selectinload(Team.members).selectinload(Registration.player),
                selectinload(Team.manual_members).selectinload(TeamManualMember.manual_entry),
            )
        )
        team = result.scalar_one_or_none()
        if team:
            member_names = []
            for m in team.members:
                if m.player:
                    n = m.player.display_name or None
                    if not n:
                        n = await _fetch_discord_name(m.player.discord_id)
                    member_names.append(n or str(m.player.discord_id))
                else:
                    n = await _fetch_discord_name(m.player_id) if (guild or client) else None
                    member_names.append(n or str(m.player_id))
            member_names += [
                m.manual_entry.display_name
                for m in sorted(team.manual_members, key=lambda x: x.sort_order)
                if m.manual_entry
            ]
            return team.name + " (" + ", ".join(member_names) + ")" if member_names else team.name
        return f"Team #{entity_id}"
    else:
        player = await session.get(Player, entity_id)
        if player:
            name = player.display_name or None
            if not name:
                name = await _fetch_discord_name(entity_id)
            return name or str(player.discord_id)
        name = await _fetch_discord_name(entity_id) if (guild or client) else None
        return name or f"Player #{entity_id}"


async def resolve_match_slot(
    session: AsyncSession,
    match: BracketMatch,
    slot: int,
    is_team: bool,
    guild: discord.Guild | None = None,
    client: discord.Client | None = None,
) -> str:
    """Resolve slot 1 or 2 of a match to display name (handles player, team, or manual entry)."""
    if is_team:
        tid = match.team1_id if slot == 1 else match.team2_id
        return await resolve_entity(session, tid, True, guild, client) if tid else "TBD"
    if slot == 1:
        if match.player1_id:
            return await resolve_entity(session, match.player1_id, False, guild, client)
        if match.manual_entry1_id:
            entry = await session.get(TournamentManualEntry, match.manual_entry1_id)
            return entry.display_name if entry else "TBD"
    else:
        if match.player2_id:
            return await resolve_entity(session, match.player2_id, False, guild, client)
        if match.manual_entry2_id:
            entry = await session.get(TournamentManualEntry, match.manual_entry2_id)
            return entry.display_name if entry else "TBD"
    return "TBD"


def champion_match_has_winner(
    matches_with_winners: list,
    bracket_type: str,
    max_round_single_elim: int | None = None,
) -> bool:
    """True if the champion (final) match has a winner set."""
    if not matches_with_winners:
        return False
    if bracket_type == "double_elim":
        return any(m.bracket_section == "grand_finals" for m in matches_with_winners)
    single_elim = [m for m in matches_with_winners if m.bracket_section is None]
    if not single_elim:
        return False
    final_round = (
        max_round_single_elim
        if max_round_single_elim is not None
        else max(m.round_num for m in single_elim)
    )
    return any(m.round_num == final_round for m in single_elim)


async def get_champion_info(
    session: AsyncSession,
    bracket,
    is_team: bool,
    guild: discord.Guild | None = None,
    client: discord.Client | None = None,
):
    """Get champion name and optional member list from the bracket. Returns (name, members_list or None)."""
    result = await session.execute(
        select(BracketMatch)
        .where(BracketMatch.bracket_id == bracket.id)
        .where(
            or_(
                BracketMatch.winner_team_id != None,  # noqa: E711
                BracketMatch.winner_player_id != None,  # noqa: E711
                BracketMatch.winner_manual_entry_id != None,  # noqa: E711
            )
        )
    )
    champ_matches = result.scalars().all()
    champ_match = None
    for m in champ_matches:
        if m.bracket_section == "grand_finals":
            champ_match = m
            break
    if not champ_match and champ_matches:
        champ_match = max(champ_matches, key=lambda x: (x.round_num, x.match_num))
    if not champ_match:
        return None, None
    if champ_match.winner_team_id:
        team_result = await session.execute(
            select(Team)
            .where(Team.id == champ_match.winner_team_id)
            .options(
                selectinload(Team.members).selectinload(Registration.player),
                selectinload(Team.manual_members).selectinload(TeamManualMember.manual_entry),
            )
        )
        team = team_result.scalar_one_or_none()
        if team:
            name = team.name
            members = []
            for reg in team.members:
                if reg.player:
                    members.append(
                        await resolve_entity(session, reg.player_id, False, guild, client)
                    )
            for tmm in sorted(team.manual_members, key=lambda x: x.sort_order):
                if tmm.manual_entry:
                    members.append(tmm.manual_entry.display_name)
            return name, members if members else None
    elif champ_match.winner_player_id:
        name = await resolve_entity(
            session, champ_match.winner_player_id, False, guild, client
        )
        return name, None
    elif champ_match.winner_manual_entry_id:
        entry = await session.get(
            TournamentManualEntry, champ_match.winner_manual_entry_id
        )
        return (entry.display_name if entry else "—"), None
    return None, None


async def build_teams_embed(
    session: AsyncSession,
    t,
    is_team: bool,
    guild: discord.Guild | None = None,
    client: discord.Client | None = None,
) -> discord.Embed:
    """Build Discord embed listing all teams (or participants for 1v1) with rosters."""
    if is_team:
        result = await session.execute(
            select(Team)
            .where(Team.tournament_id == t.id)
            .order_by(Team.id)
            .options(
                selectinload(Team.members).selectinload(Registration.player),
                selectinload(Team.manual_members).selectinload(TeamManualMember.manual_entry),
            )
        )
        teams = result.scalars().all()
        lines = []
        for team in teams:
            display = await resolve_entity(session, team.id, True, guild, client)
            lines.append(f"• {display}")
        title = f"Teams — {t.name}"
        field_name = "Teams"
    else:
        # 1v1: manual participants + Discord registrations
        entries_result = await session.execute(
            select(TournamentManualEntry)
            .where(
                TournamentManualEntry.tournament_id == t.id,
                TournamentManualEntry.list_type == "participant",
            )
            .order_by(TournamentManualEntry.sort_order, TournamentManualEntry.id)
        )
        entries = entries_result.scalars().all()
        regs_result = await session.execute(
            select(Registration)
            .where(
                Registration.tournament_id == t.id,
                Registration.team_id.is_(None),
            )
            .options(selectinload(Registration.player))
        )
        regs = regs_result.scalars().all()
        lines = []
        for e in entries:
            lines.append(f"• {e.display_name}")
        for reg in regs:
            name = await resolve_entity(session, reg.player_id, False, guild, client)
            lines.append(f"• {name}")
        title = f"Participants — {t.name}"
        field_name = "Participants"

    if not lines:
        lines = ["(none)"]

    embed = discord.Embed(
        title=title,
        description="Assemble before round 1. Use `/bracket next` or `/bracket status` for your match.",
        color=discord.Color.green(),
    )
    embed.add_field(name=field_name, value="\n".join(lines), inline=False)
    embed.set_footer(text=f"Tournament ID: {t.id}")
    embed.timestamp = discord.utils.utcnow()
    return embed


def build_results_embed(t, champion_name: str, champion_members: list | None = None) -> discord.Embed:
    """Build Discord embed for tournament results."""
    embed = discord.Embed(
        title=f"🏆 Tournament Complete — {t.name}",
        description=f"**{t.format}** • Champion declared",
        color=discord.Color.gold(),
    )
    embed.add_field(name="👑 Champion", value=champion_name or "—", inline=False)
    if champion_members:
        embed.add_field(name="Roster", value=", ".join(champion_members), inline=False)
    embed.set_footer(text=f"Tournament ID: {t.id}")
    embed.timestamp = discord.utils.utcnow()
    return embed


async def build_round_lineup_embed(
    session: AsyncSession,
    t,
    bracket,
    is_team: bool,
    guild: discord.Guild | None = None,
    client: discord.Client | None = None,
) -> discord.Embed | None:
    """Build Discord embed for current round lineup (same as /bracket post). Returns None if no unplayed matches."""
    matches_result = await session.execute(
        select(BracketMatch)
        .where(BracketMatch.bracket_id == bracket.id)
        .order_by(BracketMatch.round_num, BracketMatch.match_num)
    )
    all_matches = list(matches_result.scalars().all())

    unplayed = [
        m
        for m in all_matches
        if not (
            m.winner_team_id or m.winner_player_id or m.winner_manual_entry_id
        )
    ]
    if not unplayed:
        return None

    by_round = {}
    for m in unplayed:
        key = (m.bracket_section or "main", m.round_num)
        if key not in by_round:
            by_round[key] = []
        by_round[key].append(m)

    section_order = {"main": 0, "winners": 0, "losers": 1, "grand_finals": 2}
    sorted_keys = sorted(
        by_round.keys(),
        key=lambda k: (section_order.get(k[0], 0), k[1]),
    )
    current_round_key = sorted_keys[0]
    current_round_matches = by_round[current_round_key]

    section, round_num = current_round_key

    if section == "grand_finals":
        title = f"🏆 Grand Finals — {t.name}"
    elif section == "winners":
        title = f"🏆 Primary Round {round_num} — {t.name}"
    elif section == "losers":
        display_round = round_num - 10 if round_num >= 10 else round_num
        title = f"🏆 Secondary Round {display_round} — {t.name}"
    else:
        title = f"🏆 Round {round_num} — {t.name}"

    match_blocks = []
    for m in sorted(current_round_matches, key=lambda x: x.match_num):
        s1 = await resolve_match_slot(session, m, 1, is_team, guild, client)
        s2 = await resolve_match_slot(session, m, 2, is_team, guild, client)
        block = (
            f"**R{m.round_num} M{m.match_num}** (ID: {m.id})\n"
            f"Slot 1: {s1}\n"
            f"Slot 2: {s2}"
        )
        match_blocks.append(block)

    embed = discord.Embed(
        title=title,
        description=(
            f"**Current round lineup** — teams facing each other this round.\n\n"
            f"Use `/bracket next` or `/bracket status` for your match.\n"
            f"Moderators: use `/bracket update` with match ID and winner slot (1 or 2) to record results."
        ),
        color=discord.Color.blue(),
    )
    embed.add_field(name="Matches", value="\n\n".join(match_blocks), inline=False)
    embed.set_footer(text=f"Tournament ID: {t.id}")
    embed.timestamp = discord.utils.utcnow()
    return embed
