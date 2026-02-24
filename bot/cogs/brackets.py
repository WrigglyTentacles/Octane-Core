"""Brackets cog - /bracket generate, view, update (Moderator+ for generate/update)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import discord
from discord import app_commands

from bot.checks import mod_or_higher
from bot.models import Bracket, BracketMatch, Player, Registration, Team, TeamManualMember, Tournament, TournamentManualEntry
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
    t = result.scalar_one_or_none()
    if t:
        return t
    # Also allow web-created tournaments (guild_id=0)
    result = await session.execute(
        select(Tournament).where(
            Tournament.id == tournament_id,
            Tournament.guild_id == 0,
        )
    )
    return result.scalar_one_or_none()


async def resolve_entity(session: AsyncSession, entity_id: int, is_team: bool) -> str:
    """Resolve player or team ID to display name. For teams, includes all members (Discord + manual)."""
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
            members = [m.player.display_name or str(m.player.discord_id) for m in team.members]
            members += [m.manual_entry.display_name for m in sorted(team.manual_members, key=lambda x: x.sort_order)]
            return team.name + " (" + ", ".join(members) + ")" if members else team.name
        return f"Team #{entity_id}"
    else:
        player = await session.get(Player, entity_id)
        if player:
            return player.display_name or str(player.discord_id)
        return f"Player #{entity_id}"


async def resolve_match_slot(
    session: AsyncSession,
    match: BracketMatch,
    slot: int,
    is_team: bool,
) -> str:
    """Resolve slot 1 or 2 of a match to display name (handles player, team, or manual entry)."""
    if is_team:
        tid = match.team1_id if slot == 1 else match.team2_id
        return await resolve_entity(session, tid, True) if tid else "TBD"
    if slot == 1:
        if match.player1_id:
            return await resolve_entity(session, match.player1_id, False)
        if match.manual_entry1_id:
            entry = await session.get(TournamentManualEntry, match.manual_entry1_id)
            return entry.display_name if entry else "TBD"
    else:
        if match.player2_id:
            return await resolve_entity(session, match.player2_id, False)
        if match.manual_entry2_id:
            entry = await session.get(TournamentManualEntry, match.manual_entry2_id)
            return entry.display_name if entry else "TBD"
    return "TBD"


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


@bracket_group.command(name="next", description="Find out who you play next in a tournament")
@app_commands.describe(tournament_id="Tournament ID (optional — uses most recent if omitted)")
async def next_match(interaction: discord.Interaction, tournament_id: int | None = None) -> None:
    """Show your current or next match in the bracket."""
    if not interaction.guild_id or not interaction.user:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    user_id = interaction.user.id
    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        # Resolve tournament
        if tournament_id:
            t = await get_tournament(session, tournament_id, interaction.guild_id)
            if not t:
                await interaction.followup.send("Tournament not found.", ephemeral=True)
                return
            # Verify user is registered
            reg_check = await session.execute(
                select(Registration).where(
                    Registration.tournament_id == t.id,
                    Registration.player_id == user_id,
                )
            )
            if not reg_check.scalar_one_or_none():
                await interaction.followup.send(
                    f"You're not registered for **{t.name}**. Use `/tournament register` to sign up.",
                    ephemeral=True,
                )
                return
        else:
            # Find most recent active (open/in_progress) tournament in this guild where user is registered
            reg_result = await session.execute(
                select(Registration, Tournament)
                .join(Tournament, Tournament.id == Registration.tournament_id)
                .where(
                    Registration.player_id == user_id,
                    (Tournament.guild_id == interaction.guild_id) | (Tournament.guild_id == 0),
                    Tournament.status.in_(["open", "in_progress"]),
                )
                .order_by(Tournament.id.desc())
                .limit(1)
            )
            row = reg_result.first()
            if not row:
                await interaction.followup.send(
                    "You're not registered for any active tournament in this server. Use `/tournament list` to see tournaments.",
                    ephemeral=True,
                )
                return
            t = row[1]

        bracket_result = await session.execute(
            select(Bracket).where(Bracket.tournament_id == t.id)
        )
        bracket = bracket_result.scalar_one_or_none()
        if not bracket:
            await interaction.followup.send(
                f"No bracket generated yet for **{t.name}**. Wait for a moderator to generate it.",
                ephemeral=True,
            )
            return

        is_team = t.format != "1v1"
        my_entity_id = None  # team_id or player_id
        my_slot_in_match = None

        if is_team:
            # Find user's team
            reg_result = await session.execute(
                select(Registration)
                .where(
                    Registration.tournament_id == t.id,
                    Registration.player_id == user_id,
                    Registration.team_id.isnot(None),
                )
            )
            reg = reg_result.scalar_one_or_none()
            if not reg:
                await interaction.followup.send(
                    f"You're not on a team in **{t.name}**. Use `/team list` to see teams.",
                    ephemeral=True,
                )
                return
            my_entity_id = reg.team_id
        else:
            # 1v1: user must be in a match as player1_id or player2_id (Discord user)
            my_entity_id = user_id

        # Find current match (user/team in match, no winner yet)
        matches_result = await session.execute(
            select(BracketMatch)
            .where(BracketMatch.bracket_id == bracket.id)
            .order_by(BracketMatch.round_num, BracketMatch.match_num)
        )
        all_matches = {m.id: m for m in matches_result.scalars().all()}

        current_match = None
        next_match = None

        for m in all_matches.values():
            in_slot1 = (is_team and m.team1_id == my_entity_id) or (not is_team and m.player1_id == my_entity_id)
            in_slot2 = (is_team and m.team2_id == my_entity_id) or (not is_team and m.player2_id == my_entity_id)
            if not (in_slot1 or in_slot2):
                continue
            my_slot = 1 if in_slot1 else 2
            opp_slot = 2 if in_slot1 else 1
            has_winner = bool(m.winner_team_id or m.winner_player_id or m.winner_manual_entry_id)
            i_won = (
                (is_team and m.winner_team_id == my_entity_id)
                or (not is_team and m.winner_player_id == my_entity_id)
            )
            if not has_winner:
                current_match = (m, my_slot, opp_slot)
                break
            if i_won and m.parent_match_id:
                parent = all_matches.get(m.parent_match_id)
                if parent:
                    next_match = (parent, m.parent_match_slot, 2 if m.parent_match_slot == 1 else 1)
                break

        if current_match:
            m, my_slot, opp_slot = current_match
            opp_name = await resolve_match_slot(session, m, opp_slot, is_team)
            embed = discord.Embed(
                title=f"Your current match — {t.name}",
                description=f"**Round {m.round_num}**, Match {m.match_num}",
                color=discord.Color.green(),
            )
            embed.add_field(name="Your opponent", value=opp_name, inline=False)
            embed.set_footer(text=f"Match ID: {m.id}")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        if next_match:
            m, my_slot, opp_slot = next_match
            opp_name = await resolve_match_slot(session, m, opp_slot, is_team)
            embed = discord.Embed(
                title=f"Your next match — {t.name}",
                description=f"**Round {m.round_num}**, Match {m.match_num}",
                color=discord.Color.blue(),
            )
            embed.add_field(name="Your opponent", value=opp_name, inline=False)
            embed.set_footer(text=f"Match ID: {m.id}")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Check if they lost and might have a losers bracket match (double elim)
        for m in all_matches.values():
            in_slot1 = (is_team and m.team1_id == my_entity_id) or (not is_team and m.player1_id == my_entity_id)
            in_slot2 = (is_team and m.team2_id == my_entity_id) or (not is_team and m.player2_id == my_entity_id)
            if not (in_slot1 or in_slot2):
                continue
            has_winner = bool(m.winner_team_id or m.winner_player_id or m.winner_manual_entry_id)
            i_won = (
                (is_team and m.winner_team_id == my_entity_id)
                or (not is_team and m.winner_player_id == my_entity_id)
            )
            if has_winner and not i_won and m.loser_advances_to_match_id:
                loser_match = all_matches.get(m.loser_advances_to_match_id)
                if loser_match:
                    next_match = (loser_match, m.loser_advances_to_slot, 2 if m.loser_advances_to_slot == 1 else 1)
                    m, my_slot, opp_slot = next_match
                    opp_name = await resolve_match_slot(session, m, opp_slot, is_team)
                    embed = discord.Embed(
                        title=f"Your next match (losers) — {t.name}",
                        description=f"**Round {m.round_num}**, Match {m.match_num}",
                        color=discord.Color.orange(),
                    )
                    embed.add_field(name="Your opponent", value=opp_name, inline=False)
                    embed.set_footer(text=f"Match ID: {m.id}")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

        await interaction.followup.send(
            f"You don't have an active or upcoming match in **{t.name}**. You may have been eliminated, or the bracket is still in progress.",
            ephemeral=True,
        )
        return


@bracket_group.command(name="status", description="Full bracket status: previous, current, and upcoming matches")
@app_commands.describe(tournament_id="Tournament ID (optional — uses most recent if omitted)")
async def bracket_status(interaction: discord.Interaction, tournament_id: int | None = None) -> None:
    """Show your complete bracket status including past, current, and future matches."""
    if not interaction.guild_id or not interaction.user:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    user_id = interaction.user.id
    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        # Resolve tournament (same logic as next)
        if tournament_id:
            t = await get_tournament(session, tournament_id, interaction.guild_id)
            if not t:
                await interaction.followup.send("Tournament not found.", ephemeral=True)
                return
            reg_check = await session.execute(
                select(Registration).where(
                    Registration.tournament_id == t.id,
                    Registration.player_id == user_id,
                )
            )
            if not reg_check.scalar_one_or_none():
                await interaction.followup.send(
                    f"You're not registered for **{t.name}**. Use `/tournament register` to sign up.",
                    ephemeral=True,
                )
                return
        else:
            reg_result = await session.execute(
                select(Registration, Tournament)
                .join(Tournament, Tournament.id == Registration.tournament_id)
                .where(
                    Registration.player_id == user_id,
                    (Tournament.guild_id == interaction.guild_id) | (Tournament.guild_id == 0),
                    Tournament.status.in_(["open", "in_progress"]),
                )
                .order_by(Tournament.id.desc())
                .limit(1)
            )
            row = reg_result.first()
            if not row:
                await interaction.followup.send(
                    "You're not registered for any active tournament in this server.",
                    ephemeral=True,
                )
                return
            t = row[1]

        bracket_result = await session.execute(
            select(Bracket).where(Bracket.tournament_id == t.id)
        )
        bracket = bracket_result.scalar_one_or_none()
        if not bracket:
            await interaction.followup.send(
                f"No bracket generated yet for **{t.name}**.",
                ephemeral=True,
            )
            return

        is_team = t.format != "1v1"
        if is_team:
            reg_result = await session.execute(
                select(Registration).where(
                    Registration.tournament_id == t.id,
                    Registration.player_id == user_id,
                    Registration.team_id.isnot(None),
                )
            )
            reg = reg_result.scalar_one_or_none()
            if not reg:
                await interaction.followup.send(
                    f"You're not on a team in **{t.name}**.",
                    ephemeral=True,
                )
                return
            my_entity_id = reg.team_id
        else:
            my_entity_id = user_id

        matches_result = await session.execute(
            select(BracketMatch)
            .where(BracketMatch.bracket_id == bracket.id)
            .order_by(BracketMatch.round_num, BracketMatch.match_num)
        )
        all_matches = {m.id: m for m in matches_result.scalars().all()}

        def is_in_match(m):
            return (
                (is_team and (m.team1_id == my_entity_id or m.team2_id == my_entity_id))
                or (not is_team and (m.player1_id == my_entity_id or m.player2_id == my_entity_id))
            )

        def i_won(m):
            return (
                (is_team and m.winner_team_id == my_entity_id)
                or (not is_team and m.winner_player_id == my_entity_id)
            )

        # Categorize matches (iterate in round order: winners first, then losers, then grand_finals)
        def match_sort_key(m):
            section_order = {"winners": 0, "losers": 1, "grand_finals": 2}
            return (section_order.get(m.bracket_section) if m.bracket_section else 0, m.round_num, m.match_num)

        previous = []
        current_match = None
        next_matches = []

        for m in sorted(all_matches.values(), key=match_sort_key):
            if not is_in_match(m):
                continue
            has_winner = bool(m.winner_team_id or m.winner_player_id or m.winner_manual_entry_id)
            my_slot = 1 if ((is_team and m.team1_id == my_entity_id) or (not is_team and m.player1_id == my_entity_id)) else 2
            slot1_name = await resolve_match_slot(session, m, 1, is_team)
            slot2_name = await resolve_match_slot(session, m, 2, is_team)
            match_display = f"{slot1_name} vs {slot2_name}"
            section = m.bracket_section or ""

            if has_winner:
                result = "W" if i_won(m) else "L"
                previous.append((m, match_display, result, section))
            else:
                current_match = (m, match_display, section)
                break

        # Sort previous by round
        previous.sort(key=lambda x: (x[0].round_num, x[0].match_num))

        # Find next matches: from last completed win (parent) or from loss (loser_advances)
        async def match_both_slots(session, m, is_team):
            s1 = await resolve_match_slot(session, m, 1, is_team)
            s2 = await resolve_match_slot(session, m, 2, is_team)
            return f"{s1} vs {s2}"

        if not current_match and previous:
            last_prev = previous[-1]
            m_prev, _, result, _ = last_prev
            if result == "W" and m_prev.parent_match_id:
                parent = all_matches.get(m_prev.parent_match_id)
                if parent:
                    disp = await match_both_slots(session, parent, is_team)
                    next_matches.append((parent, disp, "winners", m_prev.parent_match_slot))
            elif result == "L" and m_prev.loser_advances_to_match_id:
                loser_m = all_matches.get(m_prev.loser_advances_to_match_id)
                if loser_m:
                    disp = await match_both_slots(session, loser_m, is_team)
                    next_matches.append((loser_m, disp, "losers", m_prev.loser_advances_to_slot))
        elif current_match:
            m_cur, _, _ = current_match
            if m_cur.parent_match_id:
                parent = all_matches.get(m_cur.parent_match_id)
                if parent:
                    disp = await match_both_slots(session, parent, is_team)
                    next_matches.append((parent, disp, "winners", m_cur.parent_match_slot))
            if m_cur.loser_advances_to_match_id:
                loser_m = all_matches.get(m_cur.loser_advances_to_match_id)
                if loser_m:
                    disp = await match_both_slots(session, loser_m, is_team)
                    next_matches.append((loser_m, disp, "losers", m_cur.loser_advances_to_slot))

        # Build future chain (if they keep winning)
        future_chain = []
        seen = set()
        for m, _, section, _ in next_matches:
            if section == "winners" and m.id not in seen:
                seen.add(m.id)
                while m and m.parent_match_id:
                    parent = all_matches.get(m.parent_match_id)
                    if not parent or parent.id in seen:
                        break
                    seen.add(parent.id)
                    future_chain.append(parent)
                    m = parent

        # Build embed
        embed = discord.Embed(
            title=f"Bracket — {t.name}",
            description="Your match status",
            color=discord.Color.purple(),
        )

        if previous:
            lines = []
            for m, match_disp, result, _ in previous:
                badge = "✅" if result == "W" else "❌"
                lines.append(f"{badge}**R{m.round_num} M{m.match_num}**: {match_disp} — **{result}**")
            embed.add_field(name="Previous matches", value="\n".join(lines) or "—", inline=False)

        if current_match:
            m, match_disp, section = current_match
            sect = f" ({section})" if section else ""
            embed.add_field(
                name="Current match",
                value=f"**R{m.round_num} M{m.match_num}**{sect}: {match_disp}",
                inline=False,
            )

        if next_matches:
            lines = []
            for m, match_disp, section, _ in next_matches:
                # Only show "if you win/lose" when we have a current match (outcome not decided yet)
                label = ""
                if current_match:
                    label = " (if you win)" if section == "winners" else " (if you lose)" if section == "losers" else ""
                lines.append(f"**R{m.round_num} M{m.match_num}**{label}: {match_disp}")
            embed.add_field(name="Next match" + ("es" if len(lines) > 1 else ""), value="\n".join(lines), inline=False)

        if future_chain:
            lines = []
            for m in future_chain:
                s1 = await resolve_match_slot(session, m, 1, is_team)
                s2 = await resolve_match_slot(session, m, 2, is_team)
                lines.append(f"**R{m.round_num} M{m.match_num}**: {s1} vs {s2}")
            embed.add_field(name="Road ahead (if you keep winning)", value="\n".join(lines), inline=False)

        if not previous and not current_match and not next_matches:
            embed.add_field(
                name="No matches",
                value="You don't have any matches yet. The bracket may still be in progress.",
                inline=False,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)
        return


@bracket_group.command(name="post", description="Post current round lineup to channel (Moderator+)")
@app_commands.describe(tournament_id="Tournament ID (optional — uses most recent active if omitted)")
@mod_or_higher()
async def bracket_post(interaction: discord.Interaction, tournament_id: int | None = None) -> None:
    """Post the current round lineup for the whole channel — all matches that need to be played this round."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        if tournament_id:
            t = await get_tournament(session, tournament_id, interaction.guild_id)
            if not t:
                await interaction.followup.send("Tournament not found.", ephemeral=True)
                return
        else:
            # Most recent active (open/in_progress) tournament with bracket in this guild
            result = await session.execute(
                select(Tournament)
                .join(Bracket, Bracket.tournament_id == Tournament.id)
                .where(
                    (Tournament.guild_id == interaction.guild_id) | (Tournament.guild_id == 0),
                    Tournament.status.in_(["open", "in_progress"]),
                    Tournament.archived == False,  # noqa: E712
                )
                .order_by(Tournament.id.desc())
                .limit(1)
            )
            t = result.scalar_one_or_none()
            if not t:
                await interaction.followup.send(
                    "No active tournament with a bracket found. Use `/bracket generate` first.",
                    ephemeral=True,
                )
                return

        bracket_result = await session.execute(
            select(Bracket).where(Bracket.tournament_id == t.id)
        )
        bracket = bracket_result.scalar_one_or_none()
        if not bracket:
            await interaction.followup.send(
                f"No bracket generated yet for **{t.name}**. Use `/bracket generate`.",
                ephemeral=True,
            )
            return

        is_team = t.format != "1v1"
        matches_result = await session.execute(
            select(BracketMatch)
            .where(BracketMatch.bracket_id == bracket.id)
            .order_by(BracketMatch.round_num, BracketMatch.match_num)
        )
        all_matches = list(matches_result.scalars().all())

        # Find matches without winners, grouped by (section, round)
        unplayed = [
            m for m in all_matches
            if not (m.winner_team_id or m.winner_player_id or m.winner_manual_entry_id)
        ]
        if not unplayed:
            await interaction.followup.send(
                f"All matches in **{t.name}** are complete. Tournament is finished!",
                ephemeral=True,
            )
            return

        # Group by (section, round_num), take only the earliest round with unplayed matches
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
        # Show only the current round (earliest with unplayed matches)
        current_round_key = sorted_keys[0]
        current_round_matches = by_round[current_round_key]

        section, round_num = current_round_key
        round_label = f"Round {round_num} ({section})" if section != "main" else f"Round {round_num}"

        embed = discord.Embed(
            title=f"Current round — {t.name}",
            description=f"**{round_label}** — Tournament ID: `{t.id}`\nUse `/bracket next` or `/bracket status` for your match",
            color=discord.Color.blue(),
        )

        lines = []
        for m in sorted(current_round_matches, key=lambda x: x.match_num):
            s1 = await resolve_match_slot(session, m, 1, is_team)
            s2 = await resolve_match_slot(session, m, 2, is_team)
            lines.append(f"**M{m.id}** — {s1} vs {s2}")
        embed.add_field(name="Matches", value="\n".join(lines), inline=False)

        await interaction.followup.send(embed=embed, ephemeral=False)
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
