"""Bracket generation service."""
from __future__ import annotations

import random
from typing import Any, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models import (
    Bracket,
    BracketMatch,
    Registration,
    Team,
    TeamManualMember,
    Tournament,
    TournamentManualEntry,
)
from bot.models.tournament import parse_format_players
from bot.services.rl_api import RLAPIService
import config


async def get_registrations_with_mmr(
    session: AsyncSession,
    tournament_id: int,
    mmr_playlist: str,
    rl_service: RLAPIService,
) -> List[Tuple[int, int, bool]]:
    """Get (entity_id, mmr, is_team) sorted by MMR descending."""
    result = await session.execute(
        select(Registration)
        .where(Registration.tournament_id == tournament_id)
        .options(selectinload(Registration.player), selectinload(Registration.team))
    )
    regs = result.scalars().all()
    t = await session.get(Tournament, tournament_id)
    if not t:
        return []

    mmr_list: List[Tuple[int, int, bool]] = []
    seen_teams = set()
    for reg in regs:
        if t.format == "1v1":
            player_data = await rl_service.get_player_data(
                epic_id=reg.player.epic_id, epic_username=reg.player.epic_username
            )
            if player_data:
                info = rl_service.get_playlist_mmr(player_data, mmr_playlist)
                if info:
                    mmr_list.append((reg.player_id, info[0], False))
                else:
                    mmr_list.append((reg.player_id, 0, False))  # No MMR data, seed last
            else:
                mmr_list.append((reg.player_id, 0, False))  # No Epic linked, seed last
        else:
            if reg.team_id and reg.team_id not in seen_teams:
                seen_teams.add(reg.team_id)
                team = await session.get(Team, reg.team_id)
                if team:
                    team_mmrs = []
                    for m in team.members:
                        player_data = await rl_service.get_player_data(
                            epic_id=m.player.epic_id, epic_username=m.player.epic_username
                        )
                        if player_data:
                            info = rl_service.get_playlist_mmr(player_data, mmr_playlist)
                            if info:
                                team_mmrs.append(info[0])
                    if team_mmrs:
                        avg_mmr = sum(team_mmrs) // len(team_mmrs)
                        mmr_list.append((reg.team_id, avg_mmr, True))
                    else:
                        mmr_list.append((reg.team_id, 0, True))  # No MMR, seed last

    mmr_list.sort(key=lambda x: x[1], reverse=True)
    return mmr_list


def next_power_of_2(n: int) -> int:
    """Round up to next power of 2."""
    p = 1
    while p < n:
        p *= 2
    return p


def preview_bracket_structure(
    names: List[str], bracket_type: str = "single_elim"
) -> dict:
    """Return bracket structure for preview (no DB). Same shape as get_bracket API.
    names = ordered participant/team names."""
    n = len(names)
    if n < 2:
        return {"rounds": {}, "bracket_type": bracket_type}

    def m(s1: str, s2: str, r: int, num: int, section: str = "winners") -> dict:
        return {
            "id": f"preview-{r}-{num}",
            "round_num": r,
            "match_num": num,
            "bracket_section": section,
            "team1_name": s1,
            "team2_name": s2,
            "player1_name": s1,
            "player2_name": s2,
        }

    if bracket_type == "single_elim":
        round_size = (n + 1) // 2
        rounds = {}
        rounds[1] = []
        for i in range(round_size):
            s1 = names[i] if i < n else "TBD"
            opp_idx = n - 1 - i
            s2 = names[opp_idx] if opp_idx > i and opp_idx < n else "TBD"
            rounds[1].append(m(s1, s2, 1, i + 1))
        prev_size = round_size
        r = 2
        while prev_size > 1:
            curr_size = (prev_size + 1) // 2
            rounds[r] = [m("TBD", "TBD", r, i + 1) for i in range(curr_size)]
            prev_size = curr_size
            r += 1
        return {"rounds": {str(k): v for k, v in rounds.items()}, "bracket_type": "single_elim"}

    if bracket_type == "round_robin":
        pairings = _round_robin_pairings(n)
        rounds = {}
        match_num = 1
        for round_num, pairs in pairings:
            rounds[round_num] = []
            for idx_a, idx_b in pairs:
                s1 = names[idx_a] if idx_a is not None else "BYE"
                s2 = names[idx_b] if idx_b is not None else "BYE"
                if idx_a is None:
                    s1, s2 = s2, s1  # Put BYE in slot 2 for display
                rounds[round_num].append(m(s1, s2, round_num, match_num))
                match_num += 1
        return {"rounds": {str(k): v for k, v in rounds.items()}, "bracket_type": "round_robin"}

    # Double elim preview - fall back to single elim for small brackets (< 8)
    size = next_power_of_2(n)
    if size < 8:
        return preview_bracket_structure(names, "single_elim")

    # Double elim preview - same rounds structure as real bracket
    w_r1_size = size // 2
    rounds = {}
    rounds[1] = []
    for i in range(w_r1_size):
        s1 = names[i] if i < n else "TBD"
        opp = size - 1 - i
        s2 = names[opp] if opp < n else "TBD"
        rounds[1].append(m(s1, s2, 1, i + 1, "winners"))
    prev_size = w_r1_size
    r = 2
    while prev_size > 1:
        curr_size = prev_size // 2
        rounds[r] = [m("TBD", "TBD", r, i + 1) for i in range(curr_size)]
        prev_size = curr_size
        r += 1
    l_r1_size = w_r1_size // 2
    l_round_sizes = [l_r1_size, l_r1_size]
    s = l_r1_size // 2
    while s >= 1:
        l_round_sizes.append(s)
        s = s // 2
    l_round_sizes.append(1)
    for lr, l_size in enumerate(l_round_sizes, start=1):
        rnum = 10 + lr
        rounds[rnum] = [m("TBD", "TBD", rnum, i + 1, "losers") for i in range(l_size)]
    rounds[21] = [m("TBD", "TBD", 21, 1, "grand_finals")]
    return {"rounds": {str(k): v for k, v in rounds.items()}, "bracket_type": "double_elim"}


def _round_robin_pairings(n: int) -> List[Tuple[int, List[Tuple[Optional[int], Optional[int]]]]]:
    """Circle method: returns [(round_num, [(idx_a, idx_b), ...]), ...]. idx is None for bye."""
    if n < 2:
        return []
    # For odd N: add bye (None). Rotating list has N+1 elements.
    if n % 2 == 1:
        rotating = list(range(1, n)) + [None]
        num_rounds = n
    else:
        rotating = list(range(1, n))
        num_rounds = n - 1
    n_slots = len(rotating) + 1  # +1 for fixed element at index 0

    result: List[Tuple[int, List[Tuple[Optional[int], Optional[int]]]]] = []
    for r in range(num_rounds):
        fixed_list = [0] + rotating
        pairs: List[Tuple[Optional[int], Optional[int]]] = []
        for i in range(n_slots // 2):
            a, b = fixed_list[i], fixed_list[n_slots - 1 - i]
            pairs.append((a, b))
        result.append((r + 1, pairs))
        # Rotate: last element moves to front (of rotating part)
        rotating = [rotating[-1]] + rotating[:-1]
    return result


async def create_single_elim_bracket(
    session: AsyncSession,
    tournament_id: int,
    rl_service: RLAPIService,
) -> Optional[Bracket]:
    """Create single-elimination bracket from tournament registrations."""
    t = await session.get(Tournament, tournament_id)
    if not t:
        return None

    mmr_list = await get_registrations_with_mmr(session, tournament_id, t.mmr_playlist, rl_service)
    if not mmr_list:
        return None

    seeded = [(x[0], x[2]) for x in mmr_list]
    is_team = t.format != "1v1"
    bracket = Bracket(tournament_id=tournament_id, bracket_type="single_elim")
    session.add(bracket)
    await session.flush()

    n = len(seeded)
    size = next_power_of_2(n)
    round_size = size // 2

    round_num = 1
    match_num = 0
    for i in range(round_size):
        match_num += 1
        high_seed = seeded[i][0] if i < n else None
        low_seed = seeded[size - 1 - i][0] if (size - 1 - i) < n else None
        m = BracketMatch(
            bracket_id=bracket.id,
            round_num=round_num,
            match_num=match_num,
        )
        if is_team:
            m.team1_id = high_seed
            m.team2_id = low_seed
        else:
            m.player1_id = high_seed
            m.player2_id = low_seed
        session.add(m)

    await session.commit()
    await session.refresh(bracket)
    return bracket


async def create_manual_bracket(
    session: AsyncSession,
    tournament_id: int,
    request: Optional[Any] = None,
) -> Optional[Bracket]:
    """Create bracket from manual participants. Supports single_elim and double_elim."""
    t = await session.get(Tournament, tournament_id)
    if not t:
        return None

    req = request or {}
    bracket_type = req.get("bracket_type", "single_elim")
    use_manual_order = req.get("use_manual_order", True)
    participant_entry_ids = req.get("participant_entry_ids")
    team_assignments = req.get("team_assignments")  # {"Team A": [entry_id, ...], ...}

    is_team = t.format != "1v1"
    players_per_team = parse_format_players(t.format)

    if is_team and team_assignments:
        # Create teams from team_assignments
        teams = []
        for team_name, entry_ids in team_assignments.items():
            team = Team(tournament_id=tournament_id, name=team_name)
            session.add(team)
            await session.flush()
            for i, eid in enumerate(entry_ids):
                session.add(
                    TeamManualMember(team_id=team.id, manual_entry_id=eid, sort_order=i)
                )
            teams.append(team)
        seeded = [(team.id, True) for team in teams]
    elif is_team:
        # Use existing teams, or auto-create from manual participants
        result = await session.execute(
            select(Team)
            .where(Team.tournament_id == tournament_id)
            .options(selectinload(Team.members), selectinload(Team.manual_members))
            .order_by(Team.id)
        )
        teams = result.scalars().all()
        if not teams:
            # Auto-create teams from manual participants
            entries_result = await session.execute(
                select(TournamentManualEntry)
                .where(
                    TournamentManualEntry.tournament_id == tournament_id,
                    TournamentManualEntry.list_type == "participant",
                )
                .order_by(TournamentManualEntry.sort_order, TournamentManualEntry.id)
            )
            entries = entries_result.scalars().all()
            if len(entries) < players_per_team:
                return None
            team_num = 0
            for i in range(0, len(entries), players_per_team):
                chunk = entries[i : i + players_per_team]
                if len(chunk) < players_per_team:
                    break
                team = Team(
                    tournament_id=tournament_id,
                    name=f"Team {team_num + 1}",
                )
                session.add(team)
                await session.flush()
                for j, entry in enumerate(chunk):
                    session.add(
                        TeamManualMember(team_id=team.id, manual_entry_id=entry.id, sort_order=j)
                    )
                teams.append(team)
                team_num += 1
            if not teams:
                return None
        seeded = [(team.id, True) for team in teams]
    else:
        # 1v1: manual entries + Discord registrations
        entities = []  # (id, is_team=False, is_manual=True/False)
        if participant_entry_ids:
            for eid in participant_entry_ids:
                entry = await session.get(TournamentManualEntry, eid)
                if entry and entry.tournament_id == tournament_id and entry.list_type == "participant":
                    entities.append((("manual", eid), False, True))
        else:
            result = await session.execute(
                select(TournamentManualEntry)
                .where(
                    TournamentManualEntry.tournament_id == tournament_id,
                    TournamentManualEntry.list_type == "participant",
                )
                .order_by(TournamentManualEntry.sort_order, TournamentManualEntry.id)
            )
            for entry in result.scalars().all():
                entities.append((("manual", entry.id), False, True))
            # Add Discord registrations without team
            regs_result = await session.execute(
                select(Registration)
                .where(
                    Registration.tournament_id == tournament_id,
                    Registration.team_id.is_(None),
                )
                .options(selectinload(Registration.player))
            )
            for reg in regs_result.scalars().all():
                entities.append((reg.player_id, False, False))
        if not entities:
            return None
        seeded = entities

    if bracket_type == "double_elim":
        if len(seeded) < 8:
            raise ValueError("Double elimination requires 8+ teams or participants")
        return await _create_double_elim_matches(
            session, tournament_id, seeded, is_team
        )
    if bracket_type == "round_robin":
        return await _create_round_robin_matches(
            session, tournament_id, seeded, is_team
        )
    return await _create_single_elim_matches(
        session, tournament_id, seeded, is_team
    )


def _match_had_bye(m: BracketMatch) -> bool:
    """True if this match had a bye (slot 2 was empty)."""
    return (
        not (m.team2_id or m.player2_id or m.manual_entry2_id)
        and (m.team1_id or m.player1_id or m.manual_entry1_id)
    )


def _get_winner_entity(m: BracketMatch, is_team: bool) -> Optional[Tuple]:
    """Get (entity, is_team) tuple for the match winner, or None."""
    if m.winner_team_id:
        return (m.winner_team_id, True)
    if m.winner_manual_entry_id:
        return (("manual", m.winner_manual_entry_id), False, True)
    if m.winner_player_id:
        return (m.winner_player_id, False, False)
    return None


def _get_loser_entity(m: BracketMatch, is_team: bool) -> Optional[Tuple]:
    """Get (entity, ...) tuple for the match loser, or None. Returns None for dropouts (one slot empty)."""
    winner_entity = _get_winner_entity(m, is_team)
    if not winner_entity:
        return None
    # Determine winner slot
    if is_team:
        winner_slot = 1 if m.winner_team_id == m.team1_id else 2
    elif m.winner_manual_entry_id:
        winner_slot = 1 if m.winner_manual_entry_id == m.manual_entry1_id else 2
    else:
        winner_slot = 1 if m.winner_player_id == m.player1_id else 2
    loser_slot = 3 - winner_slot
    return _get_entity_from_slot(m, loser_slot, is_team)


async def advance_winner_to_parent(
    session: AsyncSession, match: BracketMatch, is_team: bool
) -> None:
    """When a match has a winner and parent_match_id, assign winner to parent. Used for double elim."""
    if not match.parent_match_id or not (
        match.winner_team_id or match.winner_player_id or match.winner_manual_entry_id
    ):
        return
    parent = await session.get(BracketMatch, match.parent_match_id)
    if not parent:
        return
    entity = (
        (match.winner_team_id, True) if match.winner_team_id else
        (("manual", match.winner_manual_entry_id), False, True) if match.winner_manual_entry_id else
        (match.winner_player_id, False, False)
    )
    _assign_entity_to_match(parent, match.parent_match_slot, entity, is_team)
    # Do NOT auto-advance parent when only one slot is filled. The other slot is
    # waiting for another match; parent winner is set when both slots are filled.

    # Seed losers bracket: when a winners match has a loser (both slots filled),
    # assign the loser to the losers bracket match.
    if match.loser_advances_to_match_id:
        loser_entity = _get_loser_entity(match, is_team)
        if loser_entity:
            loser_match = await session.get(BracketMatch, match.loser_advances_to_match_id)
            if loser_match:
                _assign_entity_to_match(
                    loser_match, match.loser_advances_to_slot, loser_entity, is_team
                )
                await session.flush()  # Ensure loser assignment is persisted


async def advance_round_when_complete(
    session: AsyncSession, bracket_id: int, round_num: int, is_team: bool
) -> bool:
    """
    When all matches in a round have winners, advance them to the next round.
    Randomize who gets the bye slot, excluding any team that had a bye in this round.
    Only runs for single_elim; no-op if round incomplete or no next round.
    Returns True if the round was advanced, False otherwise.
    """
    result = await session.execute(
        select(BracketMatch)
        .where(
            BracketMatch.bracket_id == bracket_id,
            BracketMatch.round_num == round_num,
            BracketMatch.bracket_section.is_(None),
        )
        .order_by(BracketMatch.match_num)
    )
    round_matches = list(result.scalars().all())
    if not round_matches:
        return False

    # Check all have winners (bye matches count as won by the team in the filled slot)
    winners = []
    for m in round_matches:
        entity = _get_winner_entity(m, is_team)
        had_bye = _match_had_bye(m)
        if not entity and had_bye:
            entity = _get_entity_from_slot(m, 1, is_team)
            if entity:
                _assign_winner_from_entity(m, entity, is_team)
                await session.flush()
        if not entity:
            return False  # Round not complete
        winners.append((m, entity, had_bye))

    # Get next round matches
    next_result = await session.execute(
        select(BracketMatch)
        .where(
            BracketMatch.bracket_id == bracket_id,
            BracketMatch.round_num == round_num + 1,
            BracketMatch.bracket_section.is_(None),
        )
        .order_by(BracketMatch.match_num)
    )
    next_matches = list(next_result.scalars().all())
    if not next_matches:
        return False

    # Build slots: (parent_match_id, parent_slot) for each advancing winner
    all_slots = []
    for i in range(len(round_matches)):
        parent_idx = i // 2
        parent_slot = (i % 2) + 1
        all_slots.append((next_matches[parent_idx].id, parent_slot))

    num_adv = len(round_matches)
    num_next_slots = len(next_matches) * 2
    bye_slot_idx = num_adv - 1 if num_next_slots > num_adv else -1

    if bye_slot_idx >= 0:
        bye_slot = all_slots[bye_slot_idx]
        non_bye_slots = [s for i, s in enumerate(all_slots) if i != bye_slot_idx]
        bye_winners = [(m, e) for m, e, hb in winners if hb]
        other_winners = [(m, e) for m, e, hb in winners if not hb]
        if bye_winners and non_bye_slots:
            random.shuffle(non_bye_slots)
            bye_winners[0][0].parent_match_id, bye_winners[0][0].parent_match_slot = non_bye_slots[0]
            remaining = non_bye_slots[1:] + [bye_slot]
            random.shuffle(remaining)
            needed = len(other_winners) + max(0, len(bye_winners) - 1)
            if len(remaining) < needed:
                raise ValueError(
                    f"Bye assignment: need {needed} slots for {len(other_winners)} non-bye + {len(bye_winners)} bye winners, have {len(remaining)}"
                )
            for j, (m, _) in enumerate(other_winners):
                m.parent_match_id, m.parent_match_slot = remaining[j]
            for j, (m, _) in enumerate(bye_winners[1:], len(other_winners)):
                m.parent_match_id, m.parent_match_slot = remaining[j]
        else:
            random.shuffle(all_slots)
            for i, winner in enumerate(winners):
                m = winner[0]
                m.parent_match_id, m.parent_match_slot = all_slots[i]
    else:
        random.shuffle(all_slots)
        for i, winner in enumerate(winners):
            m = winner[0]
            m.parent_match_id, m.parent_match_slot = all_slots[i]

    # Advance each winner to their assigned slot
    structural_bye = set()
    if bye_slot_idx >= 0:
        pid, pslot = all_slots[bye_slot_idx]
        other = 2 if pslot == 1 else 1
        structural_bye.add((pid, other))

    for winner in winners:
        m, entity = winner[0], winner[1]
        parent = await session.get(BracketMatch, m.parent_match_id)
        if not parent:
            continue
        _assign_entity_to_match(parent, m.parent_match_slot, entity, is_team)
        has_s1 = bool(parent.team1_id or parent.player1_id or parent.manual_entry1_id)
        has_s2 = bool(parent.team2_id or parent.player2_id or parent.manual_entry2_id)
        other_slot = 2 if m.parent_match_slot == 1 else 1
        is_struct_bye = (parent.id, other_slot) in structural_bye
        if has_s1 and not has_s2 and is_struct_bye:
            if is_team:
                parent.winner_team_id = parent.team1_id
            elif parent.manual_entry1_id:
                parent.winner_manual_entry_id = parent.manual_entry1_id
            else:
                parent.winner_player_id = parent.player1_id
            await advance_round_when_complete(session, bracket_id, round_num + 1, is_team)
        elif has_s2 and not has_s1 and is_struct_bye:
            if is_team:
                parent.winner_team_id = parent.team2_id
            elif parent.manual_entry2_id:
                parent.winner_manual_entry_id = parent.manual_entry2_id
            else:
                parent.winner_player_id = parent.player2_id
            await advance_round_when_complete(session, bracket_id, round_num + 1, is_team)
    return True


async def advance_rounds_until_incomplete(
    session: AsyncSession, bracket_id: int, start_round: int, is_team: bool
) -> bool:
    """Advance start_round, then keep advancing subsequent rounds until one is incomplete.
    Returns True if at least one round was advanced, False otherwise."""
    r = start_round
    any_advanced = False
    while True:
        advanced = await advance_round_when_complete(session, bracket_id, r, is_team)
        any_advanced = any_advanced or advanced
        await session.flush()
        next_result = await session.execute(
            select(BracketMatch)
            .where(
                BracketMatch.bracket_id == bracket_id,
                BracketMatch.round_num == r + 1,
                BracketMatch.bracket_section.is_(None),
            )
        )
        next_matches = list(next_result.scalars().all())
        if not next_matches:
            break
        all_complete = True
        for m in next_matches:
            entity = _get_winner_entity(m, is_team)
            if not entity and _match_had_bye(m):
                entity = _get_entity_from_slot(m, 1, is_team)
            if not entity:
                all_complete = False
                break
        if not all_complete:
            break
        r += 1
    return any_advanced


async def round_just_completed(
    session: AsyncSession,
    bracket_id: int,
    bracket_type: str,
    match_round_num: int,
    match_section: str | None,
    is_team: bool,
) -> bool:
    """True if all matches in the given (round, section) have winners. Used for round_robin and double_elim Discord posting."""
    if bracket_type not in ("round_robin", "double_elim"):
        return False

    if match_section is None:
        section_filter = BracketMatch.bracket_section.is_(None)
    else:
        section_filter = BracketMatch.bracket_section == match_section

    result = await session.execute(
        select(BracketMatch)
        .where(
            BracketMatch.bracket_id == bracket_id,
            BracketMatch.round_num == match_round_num,
            section_filter,
        )
    )
    round_matches = list(result.scalars().all())
    if not round_matches:
        return False

    for m in round_matches:
        entity = _get_winner_entity(m, is_team)
        had_bye = _match_had_bye(m)
        if not entity and had_bye:
            entity = _get_entity_from_slot(m, 1, is_team)
        if not entity:
            return False
    return True


def _assign_winner_from_entity(m: BracketMatch, entity: Tuple, is_team: bool) -> None:
    """Set winner on match from entity tuple (team_id, True) or (player_id, False, False) or (('manual', id), False, True)."""
    m.winner_team_id = None
    m.winner_player_id = None
    m.winner_manual_entry_id = None
    if entity[1] is True and len(entity) == 2:  # team
        m.winner_team_id = entity[0]
    elif len(entity) == 3 and entity[2] is True:  # manual
        m.winner_manual_entry_id = entity[0][1]
    else:  # player
        m.winner_player_id = entity[0]


def _get_entity_from_slot(m: BracketMatch, slot: int, is_team: bool) -> Optional[Tuple]:
    """Get (entity, is_team) tuple for the entity in slot 1 or 2."""
    if slot == 1:
        if m.team1_id:
            return (m.team1_id, True)
        if m.manual_entry1_id:
            return (("manual", m.manual_entry1_id), False, True)
        if m.player1_id:
            return (m.player1_id, False, False)
    else:
        if m.team2_id:
            return (m.team2_id, True)
        if m.manual_entry2_id:
            return (("manual", m.manual_entry2_id), False, True)
        if m.player2_id:
            return (m.player2_id, False, False)
    return None


async def _clear_winner_and_ancestors(
    session: AsyncSession, match: BracketMatch, is_team: bool
) -> None:
    """Clear winner for match and recursively for all ancestor matches."""
    match.winner_team_id = None
    match.winner_player_id = None
    match.winner_manual_entry_id = None
    if match.parent_match_id:
        parent = await session.get(BracketMatch, match.parent_match_id)
        if parent:
            await _clear_winner_and_ancestors(session, parent, is_team)


def _clear_slot(m: BracketMatch, slot: int, is_team: bool) -> None:
    """Clear entity from match slot."""
    if is_team:
        if slot == 1:
            m.team1_id = None
        else:
            m.team2_id = None
    else:
        if slot == 1:
            m.manual_entry1_id = None
            m.player1_id = None
        else:
            m.manual_entry2_id = None
            m.player2_id = None


async def clear_match_winner(
    session: AsyncSession, match_id: int, tournament_id: int
) -> None:
    """Clear the winner of a match and remove from parent/loser slots. Cascades to clear downstream."""
    match = await session.get(BracketMatch, match_id)
    if not match:
        raise ValueError("Match not found")
    bracket = await session.get(Bracket, match.bracket_id)
    if not bracket or bracket.tournament_id != tournament_id:
        raise ValueError("Match not found")
    t = await session.get(Tournament, bracket.tournament_id)
    is_team = t and t.format != "1v1"

    if not (match.winner_team_id or match.winner_player_id or match.winner_manual_entry_id):
        return

    match.winner_team_id = None
    match.winner_player_id = None
    match.winner_manual_entry_id = None

    if match.parent_match_id:
        parent = await session.get(BracketMatch, match.parent_match_id)
        if parent:
            _clear_slot(parent, match.parent_match_slot, is_team)
            await _clear_winner_and_ancestors(session, parent, is_team)

    if match.loser_advances_to_match_id:
        loser_match = await session.get(BracketMatch, match.loser_advances_to_match_id)
        if loser_match:
            _clear_slot(loser_match, match.loser_advances_to_slot, is_team)
            await _clear_winner_and_ancestors(session, loser_match, is_team)


async def swap_slots(
    session: AsyncSession,
    tournament_id: int,
    from_match_id: int,
    from_slot: int,
    to_match_id: int,
    to_slot: int,
) -> None:
    """Swap or move entities between two bracket slots. Clears winners for affected matches."""
    if from_match_id == to_match_id and from_slot == to_slot:
        return
    from_match = await session.get(BracketMatch, from_match_id)
    to_match = await session.get(BracketMatch, to_match_id)
    if not from_match or not to_match:
        raise ValueError("Match not found")
    b = await session.get(Bracket, from_match.bracket_id)
    if not b or b.tournament_id != tournament_id:
        raise ValueError("Match not found")
    to_b = await session.get(Bracket, to_match.bracket_id)
    if not to_b or to_b.tournament_id != tournament_id:
        raise ValueError("Match not found")
    t = await session.get(Tournament, b.tournament_id)
    is_team = t and t.format != "1v1"

    from_entity = _get_entity_from_slot(from_match, from_slot, is_team)
    to_entity = _get_entity_from_slot(to_match, to_slot, is_team)

    if not from_entity:
        raise ValueError("Source slot is empty")

    _assign_entity_to_match(to_match, to_slot, from_entity, is_team)
    _assign_entity_to_match(from_match, from_slot, to_entity, is_team)

    is_advancing_to_parent = (
        from_match.parent_match_id == to_match_id and from_match.parent_match_slot == to_slot
    )
    if not is_advancing_to_parent:
        await _clear_winner_and_ancestors(session, from_match, is_team)
    if from_match_id != to_match_id and not is_advancing_to_parent:
        await _clear_winner_and_ancestors(session, to_match, is_team)

    # When advancing to parent (drag winner to next round), set winner and trigger round advance
    if is_advancing_to_parent and b.bracket_type == "single_elim":
        _assign_winner_from_entity(from_match, from_entity, is_team)
        await session.flush()
        await advance_rounds_until_incomplete(session, b.id, from_match.round_num, is_team)


async def swap_match_winner(
    session: AsyncSession, match_id: int, tournament_id: int
) -> None:
    """Swap the winner of a match to the other team. Updates parent slot and clears downstream winners."""
    match = await session.get(BracketMatch, match_id)
    if not match:
        raise ValueError("Match not found")
    bracket = await session.get(Bracket, match.bracket_id)
    if not bracket or bracket.tournament_id != tournament_id:
        raise ValueError("Match not found")
    t = await session.get(Tournament, bracket.tournament_id)
    is_team = t and t.format != "1v1"

    winner_entity = _get_winner_entity(match, is_team)
    if not winner_entity:
        raise ValueError("Match has no winner to swap")
    if is_team:
        winner_slot = 1 if match.winner_team_id == match.team1_id else 2
    else:
        if match.winner_manual_entry_id:
            winner_slot = 1 if match.winner_manual_entry_id == match.manual_entry1_id else 2
        else:
            winner_slot = 1 if match.winner_player_id == match.player1_id else 2
    loser_slot = 3 - winner_slot
    loser_entity = _get_entity_from_slot(match, loser_slot, is_team)
    if not loser_entity:
        raise ValueError("Other slot is empty; cannot swap")

    new_winner = loser_entity
    if is_team:
        match.winner_team_id = new_winner[0]
        match.winner_player_id = None
        match.winner_manual_entry_id = None
    else:
        match.winner_team_id = None
        if len(new_winner) == 3 and new_winner[2]:
            match.winner_manual_entry_id = new_winner[0][1]
            match.winner_player_id = None
        else:
            match.winner_player_id = new_winner[0]
            match.winner_manual_entry_id = None

    if match.parent_match_id:
        parent = await session.get(BracketMatch, match.parent_match_id)
        if parent:
            _assign_entity_to_match(parent, match.parent_match_slot, new_winner, is_team)
            await _clear_winner_and_ancestors(session, parent, is_team)

    if match.loser_advances_to_match_id:
        loser_match = await session.get(BracketMatch, match.loser_advances_to_match_id)
        if loser_match:
            old_loser = winner_entity
            if is_team:
                old_loser_entity = (old_loser[0], True)
            else:
                old_loser_entity = old_loser
            _assign_entity_to_match(loser_match, match.loser_advances_to_slot, old_loser_entity, is_team)
            await _clear_winner_and_ancestors(session, loser_match, is_team)


async def _create_round_robin_matches(
    session: AsyncSession,
    tournament_id: int,
    seeded: List,
    is_team: bool,
) -> Optional[Bracket]:
    """Create round-robin matches. Everyone plays everyone once. Odd N: each gets exactly one bye."""
    n = len(seeded)
    if n < 2:
        return None

    bracket = Bracket(tournament_id=tournament_id, bracket_type="round_robin")
    session.add(bracket)
    await session.flush()

    pairings = _round_robin_pairings(n)
    match_num = 1
    for round_num, pairs in pairings:
        for idx_a, idx_b in pairs:
            # Bye: put real entity in slot 1, slot 2 empty (convention)
            if idx_a is None:
                entity1 = seeded[idx_b]
                entity2 = None
            elif idx_b is None:
                entity1 = seeded[idx_a]
                entity2 = None
            else:
                entity1 = seeded[idx_a]
                entity2 = seeded[idx_b]
            m = BracketMatch(
                bracket_id=bracket.id,
                round_num=round_num,
                match_num=match_num,
            )
            _assign_entity_to_match(m, 1, entity1, is_team)
            _assign_entity_to_match(m, 2, entity2, is_team)
            if entity2 is None and entity1 is not None:
                # Bye: entity1 auto-wins
                if is_team:
                    m.winner_team_id = entity1[0]
                else:
                    if entity1[2]:  # is_manual
                        m.winner_manual_entry_id = entity1[0][1]
                    else:
                        m.winner_player_id = entity1[0]
            session.add(m)
            match_num += 1

    await session.commit()
    await session.refresh(bracket)
    return bracket


def _assign_entity_to_match(
    m: BracketMatch, slot: int, entity: Optional[Tuple], is_team: bool
) -> None:
    """Assign entity to match slot (1 or 2)."""
    if not entity:
        return
    if is_team:
        if slot == 1:
            m.team1_id = entity[0]
        else:
            m.team2_id = entity[0]
    else:
        is_manual = entity[2]
        eid = entity[0][1] if is_manual else entity[0]
        if slot == 1:
            if is_manual:
                m.manual_entry1_id = eid
            else:
                m.player1_id = eid
        else:
            if is_manual:
                m.manual_entry2_id = eid
            else:
                m.player2_id = eid


async def _create_single_elim_matches(
    session: AsyncSession,
    tournament_id: int,
    seeded: List,
    is_team: bool,
) -> Optional[Bracket]:
    """Create single-elimination matches. Uses compact pairing: 1v2, 3v4, 5vbye, etc."""
    bracket = Bracket(tournament_id=tournament_id, bracket_type="single_elim")
    session.add(bracket)
    await session.flush()

    n = len(seeded)
    round_size = (n + 1) // 2
    match_num = 1

    # Build rounds: list of lists of matches
    rounds: List[List[BracketMatch]] = []

    # Round 1: compact pairing (2i vs 2i+1), bye when odd team count
    r1_matches = []
    for i in range(round_size):
        slot1 = seeded[2 * i] if 2 * i < n else None
        slot2 = seeded[2 * i + 1] if 2 * i + 1 < n else None
        m = BracketMatch(bracket_id=bracket.id, round_num=1, match_num=match_num)
        _assign_entity_to_match(m, 1, slot1, is_team)
        _assign_entity_to_match(m, 2, slot2, is_team)
        if slot2 is None and slot1 is not None:
            # Bye: team/player auto-advances
            if is_team:
                m.winner_team_id = slot1[0]
            else:
                if slot1[2]:  # is_manual
                    m.winner_manual_entry_id = slot1[0][1]
                else:
                    m.winner_player_id = slot1[0]
        session.add(m)
        r1_matches.append(m)
        match_num += 1
    rounds.append(r1_matches)

    # Rounds 2+: placeholder matches for bracket structure
    prev_size = round_size
    r = 2
    while prev_size > 1:
        curr_size = (prev_size + 1) // 2
        curr_matches = []
        for i in range(curr_size):
            m = BracketMatch(bracket_id=bracket.id, round_num=r, match_num=match_num)
            session.add(m)
            curr_matches.append(m)
            match_num += 1
        rounds.append(curr_matches)
        prev_size = curr_size
        r += 1

    await session.flush()

    # Don't set parent_match_id or advance at creation. Advancement happens when round is
    # complete (all matches have winners), via advance_round_when_complete in the API.
    await session.commit()
    await session.refresh(bracket)
    return bracket


async def _create_double_elim_matches(
    session: AsyncSession,
    tournament_id: int,
    seeded: List,
    is_team: bool,
) -> Optional[Bracket]:
    """Create double-elimination bracket: winners, losers, grand finals."""
    n = len(seeded)
    size = next_power_of_2(n)
    if size < 8:
        return await _create_single_elim_matches(
            session, tournament_id, seeded, is_team
        )

    bracket = Bracket(tournament_id=tournament_id, bracket_type="double_elim")
    session.add(bracket)
    await session.flush()

    # Winners bracket: round 1 (double elim requires power-of-2 structure)
    size = next_power_of_2(n)
    w_r1_size = size // 2
    matches: List[BracketMatch] = []
    match_num = 1

    # Winners R1 - standard seeding: 1vs8, 2vs7, 3vs6, 4vs5
    for i in range(w_r1_size):
        high = seeded[i] if i < n else None
        low = seeded[size - 1 - i] if (size - 1 - i) < n else None
        m = BracketMatch(
            bracket_id=bracket.id,
            round_num=1,
            match_num=match_num,
            bracket_section="winners",
        )
        _assign_entity_to_match(m, 1, high, is_team)
        _assign_entity_to_match(m, 2, low, is_team)
        session.add(m)
        matches.append(m)
        match_num += 1

    # Winners R2, R3, ... up to final
    w_round = 2
    prev_round_size = w_r1_size
    while prev_round_size > 1:
        curr_size = prev_round_size // 2
        for _ in range(curr_size):
            m = BracketMatch(
                bracket_id=bracket.id,
                round_num=w_round,
                match_num=match_num,
                bracket_section="winners",
            )
            session.add(m)
            matches.append(m)
            match_num += 1
        prev_round_size = curr_size
        w_round += 1

    # Losers bracket: L1 = W1 losers pair off, L2 = L1 winners vs W2 losers (same size)
    # Then L3, L4... halve until losers final (L winner vs W final loser)
    l_r1_size = w_r1_size // 2
    l_round_sizes = [l_r1_size, l_r1_size]
    s = l_r1_size // 2
    while s >= 1:
        l_round_sizes.append(s)
        s = s // 2
    l_round_sizes.append(1)  # Losers final
    for l_round, l_size in enumerate(l_round_sizes, start=1):
        for _ in range(l_size):
            m = BracketMatch(
                bracket_id=bracket.id,
                round_num=10 + l_round,
                match_num=match_num,
                bracket_section="losers",
            )
            session.add(m)
            matches.append(m)
            match_num += 1

    # Grand finals
    gf = BracketMatch(
        bracket_id=bracket.id,
        round_num=21,
        match_num=match_num,
        bracket_section="grand_finals",
    )
    session.add(gf)
    matches.append(gf)

    await session.flush()

    w_matches = [m for m in matches if m.bracket_section == "winners"]
    l_matches = [m for m in matches if m.bracket_section == "losers"]
    gf_match = matches[-1]
    w_final = w_matches[-1]
    l_final = l_matches[-1]

    # Winners bracket: link each round to next
    idx = 0
    r_size = w_r1_size
    while idx + r_size < len(w_matches):
        for i in range(r_size):
            m = w_matches[idx + i]
            next_m = w_matches[idx + r_size + (i // 2)]
            m.parent_match_id = next_m.id
            m.parent_match_slot = (i % 2) + 1
        idx += r_size
        r_size //= 2

    # W R1 losers -> L R1 (pair off: M0,M1 losers -> L0; M2,M3 losers -> L1)
    for i in range(l_r1_size):
        w_matches[i * 2].loser_advances_to_match_id = l_matches[i].id
        w_matches[i * 2].loser_advances_to_slot = 1
        w_matches[i * 2 + 1].loser_advances_to_match_id = l_matches[i].id
        w_matches[i * 2 + 1].loser_advances_to_slot = 2

    # W R2 losers -> L R2 slot 2; L R1 winners -> L R2 slot 1
    w_r2_start = w_r1_size
    l_r2_start = l_r1_size
    for i in range(l_r1_size):
        w_m = w_matches[w_r2_start + i]
        l_m = l_matches[l_r2_start + i]
        w_m.loser_advances_to_match_id = l_m.id
        w_m.loser_advances_to_slot = 2
        l_matches[i].parent_match_id = l_m.id
        l_matches[i].parent_match_slot = 1

    # L bracket internal: L2 winners -> L3, L3 winners -> L4, etc. (up to losers final)
    l_idx = l_r2_start
    l_r_size = l_r1_size
    while l_idx + l_r_size < len(l_matches) and l_r_size >= 1:
        for i in range(l_r_size):
            l_m = l_matches[l_idx + i]
            next_l = l_matches[l_idx + l_r_size + (i // 2)]
            l_m.parent_match_id = next_l.id
            l_m.parent_match_slot = (i % 2) + 1
        l_idx += l_r_size
        l_r_size //= 2

    # W final loser -> L final slot 2; L final winner -> GF slot 2
    w_final.loser_advances_to_match_id = l_final.id
    w_final.loser_advances_to_slot = 2
    w_final.parent_match_id = gf_match.id
    w_final.parent_match_slot = 1
    l_final.parent_match_id = gf_match.id
    l_final.parent_match_slot = 2

    await session.commit()
    await session.refresh(bracket)
    return bracket
