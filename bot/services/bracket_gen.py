"""Bracket generation service.

Double elimination (n >= 8): winners bracket uses the same W1 layout as single
elim — (n+1)//2 matches with adjacent seeding (2i vs 2i+1). When W1 has an odd
number of matches, the last W1 match's loser feeds only slot 1 of the last L1
match; slot 2 is a structural bye resolved at runtime by
apply_losers_bracket_structural_byes.
"""
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


def _double_elim_loser_round_sizes(
    l_r1_size: int, w_layer_sizes: List[int]
) -> List[int]:
    """
    Losers layer sizes follow L1/L2 = l_r1, then ceil-halving the survivor count.
    Whenever halving reaches width w and that matches winners layer W_{2+k} (k = shelf
    index), append a duplicate round of the same width so each match keeps slot 1 for
    an L child and slot 2 for the matching WB dropout wave.
    """
    if l_r1_size < 1:
        return [1, 1, 1]
    sizes = [l_r1_size, l_r1_size]
    n_w = len(w_layer_sizes)
    p = l_r1_size
    shelf_round = 0
    while p > 1:
        nxt = (p + 1) // 2
        sizes.append(nxt)
        w_idx = 2 + shelf_round
        if w_idx < n_w - 1 and nxt >= 2 and w_layer_sizes[w_idx] == nxt:
            sizes.append(nxt)
            shelf_round += 1
        p = nxt
    sizes.append(1)  # losers final (W final loser)
    return sizes


def _winners_layer_sizes(w_r1_match_count: int) -> List[int]:
    out: List[int] = []
    p = w_r1_match_count
    while p >= 1:
        out.append(p)
        if p == 1:
            break
        p = (p + 1) // 2
    return out


def _l_layer_starts(l_round_sizes: List[int]) -> List[int]:
    starts: List[int] = []
    acc = 0
    for sz in l_round_sizes:
        starts.append(acc)
        acc += sz
    return starts


def _losers_wb_injection_dest_layers(l_round_sizes: List[int]) -> List[int]:
    """
    Indices into l_round_sizes for rounds that receive winners-bracket dropout losers
    (W3..W_{n-2}). These are the *destination* layers of a parallel shelf edge
    (same width as previous layer, previous layer was wider — merge-then-WB wave).

    Shelves where width is 1 (e.g. L5→L6 before l_final) are excluded: that edge only
    forwards L survivors toward l_final; the WB finalist drops via w_final.loser_advances.

    Must match the same prev>cur && next==cur rule used when linking L matches.
    """
    out: List[int] = []
    for layer in range(1, len(l_round_sizes) - 1):
        cur_sz = l_round_sizes[layer]
        next_sz = l_round_sizes[layer + 1]
        prev_sz = l_round_sizes[layer - 1]
        if (
            next_sz == cur_sz
            and prev_sz > cur_sz
            and cur_sz >= 2
        ):
            out.append(layer + 1)
    return out


def _l_match_child_occupies_slot(
    l_matches: List[BracketMatch],
    l_starts: List[int],
    l_round_sizes: List[int],
    lb_ri: int,
    k: int,
    slot: int,
) -> bool:
    if lb_ri <= 0:
        return False
    lm = l_matches[l_starts[lb_ri] + k]
    ps = l_starts[lb_ri - 1]
    ns = l_round_sizes[lb_ri - 1]
    for i in range(ns):
        ch = l_matches[ps + i]
        if ch.parent_match_id == lm.id and ch.parent_match_slot == slot:
            return True
    return False


def _wire_all_wb_loser_drops(
    w_matches: List[BracketMatch],
    l_matches: List[BracketMatch],
    w_layer_sizes: List[int],
    l_round_sizes: List[int],
) -> None:
    """
    W1/W2 losers are wired elsewhere. For each winners match in W3..W_{n-2}, assign
    loser_advances_to_* on the losers *parallel shelf* for that wave only.

    Never scan earlier merge rounds: e.g. for 12 players L3 can have a match with
    only one L child on slot 1, leaving slot 2 "free" and wrongly stealing a W3
    loser from the real WB-drop round (L4).
    """
    l_starts = _l_layer_starts(l_round_sizes)
    n_w = len(w_layer_sizes)
    n_ll = len(l_round_sizes)
    inject_layers = _losers_wb_injection_dest_layers(l_round_sizes)
    claimed: set[tuple[int, int]] = set()
    for wm in w_matches:
        if wm.loser_advances_to_match_id and wm.loser_advances_to_slot:
            claimed.add((wm.loser_advances_to_match_id, wm.loser_advances_to_slot))

    num_wb_rounds = max(0, n_w - 3)
    if num_wb_rounds > len(inject_layers):
        raise ValueError(
            f"Double elim: need {num_wb_rounds} WB-drop losers layers "
            f"but l_round_sizes only has {len(inject_layers)} "
            f"(l_round_sizes={l_round_sizes})"
        )

    for w_li in range(2, n_w - 1):
        w_start = sum(w_layer_sizes[:w_li])
        n_wm = w_layer_sizes[w_li]
        lb_target = inject_layers[w_li - 2]

        for j in range(n_wm):
            w_m = w_matches[w_start + j]
            placed = False
            n_l_at = l_round_sizes[lb_target]
            l_base = l_starts[lb_target]
            for k in range(n_l_at):
                lm = l_matches[l_base + k]
                for slot_try in (2, 1):
                    if _l_match_child_occupies_slot(
                        l_matches, l_starts, l_round_sizes, lb_target, k, slot_try
                    ):
                        continue
                    if (lm.id, slot_try) in claimed:
                        continue
                    w_m.loser_advances_to_match_id = lm.id
                    w_m.loser_advances_to_slot = slot_try
                    claimed.add((lm.id, slot_try))
                    placed = True
                    break
                if placed:
                    break
            if not placed:
                raise ValueError(
                    f"Double elim: could not place WB layer {w_li} match {j} loser "
                    f"(lb_target={lb_target}, n_w={n_w}, n_ll={n_ll}, "
                    f"l_round_sizes={l_round_sizes})"
                )


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
    if n < 8:
        return preview_bracket_structure(names, "single_elim")

    # Double elim preview — mirror _create_double_elim_matches
    w_r1_match_count = (n + 1) // 2
    rounds = {}
    rounds[1] = []
    for i in range(w_r1_match_count):
        s1 = names[2 * i] if 2 * i < n else "TBD"
        s2 = names[2 * i + 1] if 2 * i + 1 < n else "TBD"
        rounds[1].append(m(s1, s2, 1, i + 1, "winners"))
    prev_size = w_r1_match_count
    r = 2
    while prev_size > 1:
        curr_size = (prev_size + 1) // 2
        rounds[r] = [m("TBD", "TBD", r, i + 1, "winners") for i in range(curr_size)]
        prev_size = curr_size
        r += 1
    l_r1_size = (w_r1_match_count + 1) // 2
    w_layers_preview = _winners_layer_sizes(w_r1_match_count)
    l_round_sizes = _double_elim_loser_round_sizes(l_r1_size, w_layers_preview)
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


def _winner_avoided_opponent(m: BracketMatch, is_team: bool) -> bool:
    """True if the recorded winner never faced an opponent in this match (R1 bye or structural bye)."""
    if not _get_winner_entity(m, is_team):
        return False
    if _match_had_bye(m):
        return True
    has_s1 = bool(m.team1_id or m.player1_id or m.manual_entry1_id)
    has_s2 = bool(m.team2_id or m.player2_id or m.manual_entry2_id)
    return not (has_s1 and has_s2)


def _winner_parent_slot(m: BracketMatch, is_team: bool) -> int:
    """Which parent slot (1 or 2) the winner occupies."""
    if is_team:
        return 1 if m.winner_team_id == m.team1_id else 2
    if m.winner_manual_entry_id:
        return 1 if m.winner_manual_entry_id == m.manual_entry1_id else 2
    return 1 if m.winner_player_id == m.player1_id else 2


async def count_prior_bye_wins_on_path(
    session: AsyncSession, m: BracketMatch, is_team: bool
) -> int:
    """Count how many times this competitor advanced without playing an opponent on the path to this match."""
    total = 0
    cur: Optional[BracketMatch] = m
    while cur is not None:
        if _winner_avoided_opponent(cur, is_team):
            total += 1
        if cur.round_num <= 1:
            break
        wslot = _winner_parent_slot(cur, is_team)
        result = await session.execute(
            select(BracketMatch).where(
                BracketMatch.bracket_id == cur.bracket_id,
                BracketMatch.parent_match_id == cur.id,
                BracketMatch.parent_match_slot == wslot,
            )
        )
        cur = result.scalar_one_or_none()
    return total


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


def _entity_key(ent: Optional[Tuple]) -> Optional[Tuple[str, int]]:
    if not ent:
        return None
    if ent[1] is True:
        return ("team", int(ent[0]))
    if len(ent) == 3 and ent[2]:
        return ("manual", int(ent[0][1]))
    return ("player", int(ent[0]))


def _entities_represent_same_competitor(
    a: Optional[Tuple], b: Optional[Tuple]
) -> bool:
    ka, kb = _entity_key(a), _entity_key(b)
    return ka is not None and ka == kb


async def resync_wb_losers_into_losers_bracket(
    session: AsyncSession, bracket_id: int, is_team: bool
) -> bool:
    """Re-apply WB loser_advances_* for decided matches (fixes missed drops / ordering)."""
    changed = False
    result = await session.execute(
        select(BracketMatch).where(
            BracketMatch.bracket_id == bracket_id,
            BracketMatch.bracket_section == "winners",
        )
    )
    for wm in result.scalars().all():
        if not (
            wm.winner_team_id or wm.winner_player_id or wm.winner_manual_entry_id
        ):
            continue
        if not wm.loser_advances_to_match_id or not wm.loser_advances_to_slot:
            continue
        loser_entity = _get_loser_entity(wm, is_team)
        if not loser_entity:
            continue
        lm = await session.get(BracketMatch, wm.loser_advances_to_match_id)
        if not lm:
            continue
        cur = _get_entity_from_slot(lm, wm.loser_advances_to_slot, is_team)
        if _entities_represent_same_competitor(cur, loser_entity):
            continue
        _assign_entity_to_match(lm, wm.loser_advances_to_slot, loser_entity, is_team)
        changed = True
    return changed


async def propagate_winners_to_parent_chain(
    session: AsyncSession, bracket_id: int, is_team: bool
) -> bool:
    """For every match with a winner and parent, advance if the parent slot is wrong or empty."""
    changed = False
    result = await session.execute(
        select(BracketMatch).where(BracketMatch.bracket_id == bracket_id)
    )
    for m in result.scalars().all():
        if not (
            m.winner_team_id or m.winner_player_id or m.winner_manual_entry_id
        ):
            continue
        if not m.parent_match_id:
            continue
        parent = await session.get(BracketMatch, m.parent_match_id)
        if not parent:
            continue
        entity = (
            (m.winner_team_id, True) if m.winner_team_id else
            (("manual", m.winner_manual_entry_id), False, True) if m.winner_manual_entry_id else
            (m.winner_player_id, False, False)
        )
        cur = _get_entity_from_slot(parent, m.parent_match_slot, is_team)
        if _entities_represent_same_competitor(cur, entity):
            continue
        await advance_winner_to_parent(session, m, is_team)
        changed = True
    return changed


async def _ensure_grand_finals_losers_champion_placed(
    session: AsyncSession, bracket_id: int, is_team: bool
) -> bool:
    """Put the losers-bracket champion on grand finals slot 2 when l_final has a winner.

    Uses the deepest losers match (max round_num) so GF still updates if parent_match_id
    is missing or points at the wrong match after manual edits or legacy data.
    """
    r_gf = await session.execute(
        select(BracketMatch).where(
            BracketMatch.bracket_id == bracket_id,
            BracketMatch.bracket_section == "grand_finals",
        )
    )
    gfs = list(r_gf.scalars().all())
    if len(gfs) != 1:
        return False
    gf = gfs[0]
    r_lf = await session.execute(
        select(BracketMatch)
        .where(
            BracketMatch.bracket_id == bracket_id,
            BracketMatch.bracket_section == "losers",
        )
        .order_by(BracketMatch.round_num.desc(), BracketMatch.match_num.desc())
        .limit(1)
    )
    l_final = r_lf.scalar_one_or_none()
    if not l_final:
        return False
    win_ent = _get_winner_entity(l_final, is_team)
    if not win_ent:
        return False
    cur = _get_entity_from_slot(gf, 2, is_team)
    if _entities_represent_same_competitor(cur, win_ent):
        return False
    if l_final.parent_match_id == gf.id and l_final.parent_match_slot == 2:
        await advance_winner_to_parent(session, l_final, is_team)
    else:
        _assign_entity_to_match(gf, 2, win_ent, is_team)
    return True


async def flush_double_elim_after_score_update(
    session: AsyncSession, bracket_id: int, is_team: bool
) -> None:
    """Cascade WB losers, parent slots, and structural byes until stable (one API/Discord update)."""
    for _ in range(64):
        a = await resync_wb_losers_into_losers_bracket(session, bracket_id, is_team)
        b = await propagate_winners_to_parent_chain(session, bracket_id, is_team)
        await session.flush()
        await apply_double_elim_structural_byes(session, bracket_id, is_team)
        await session.flush()
        c = await propagate_winners_to_parent_chain(session, bracket_id, is_team)
        await session.flush()
        d = await _ensure_grand_finals_losers_champion_placed(session, bracket_id, is_team)
        await session.flush()
        if not (a or b or c or d):
            break


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


async def apply_winners_bracket_structural_byes(
    session: AsyncSession, bracket_id: int, is_team: bool
) -> None:
    """
    Compact winners bracket (3→2 matches, etc.) can leave a parent with one feeder;
    the other slot is a structural bye and must auto-win like single_elim does inside
    advance_round_when_complete. Double elim does not call that function (it targets
    bracket_section IS NULL), so we resolve that here.

    Do NOT run this on losers matches: an empty slot there usually waits for a
    winners-bracket loser via loser_advances_to_match_id, not parent_match_id — the
    same "incoming child" query would miss that and falsely treat it as a bye.
    """
    while True:
        result = await session.execute(
            select(BracketMatch).where(
                BracketMatch.bracket_id == bracket_id,
                BracketMatch.bracket_section == "winners",
            )
        )
        changed = False
        for parent in result.scalars().all():
            if (
                parent.winner_team_id
                or parent.winner_player_id
                or parent.winner_manual_entry_id
            ):
                continue
            e1 = _get_entity_from_slot(parent, 1, is_team)
            e2 = _get_entity_from_slot(parent, 2, is_team)
            if e1 and e2:
                continue
            if not e1 and not e2:
                continue
            empty_slot = 2 if e1 else 1
            incoming = await session.execute(
                select(BracketMatch.id)
                .where(
                    BracketMatch.bracket_id == bracket_id,
                    BracketMatch.parent_match_id == parent.id,
                    BracketMatch.parent_match_slot == empty_slot,
                )
                .limit(1)
            )
            if incoming.scalar_one_or_none() is not None:
                continue
            entity = e1 or e2
            if not entity:
                continue
            _assign_winner_from_entity(parent, entity, is_team)
            await session.flush()
            await advance_winner_to_parent(session, parent, is_team)
            changed = True
        if not changed:
            break


async def apply_losers_bracket_structural_byes(
    session: AsyncSession, bracket_id: int, is_team: bool
) -> None:
    """
    Odd W1 → last L1 match can have only one WB loser (slot 1); slot 2 is a bye.
    Like apply_winners_bracket_structural_byes, empty slots that will never be
    filled via parent_match_id or loser_advances_to_* must auto-advance.
    """
    while True:
        result = await session.execute(
            select(BracketMatch).where(
                BracketMatch.bracket_id == bracket_id,
                BracketMatch.bracket_section == "losers",
            )
        )
        changed = False
        for parent in result.scalars().all():
            if (
                parent.winner_team_id
                or parent.winner_player_id
                or parent.winner_manual_entry_id
            ):
                continue
            e1 = _get_entity_from_slot(parent, 1, is_team)
            e2 = _get_entity_from_slot(parent, 2, is_team)
            if e1 and e2:
                continue
            if not e1 and not e2:
                continue
            empty_slot = 2 if e1 else 1
            incoming_child = await session.execute(
                select(BracketMatch.id)
                .where(
                    BracketMatch.bracket_id == bracket_id,
                    BracketMatch.parent_match_id == parent.id,
                    BracketMatch.parent_match_slot == empty_slot,
                )
                .limit(1)
            )
            if incoming_child.scalar_one_or_none() is not None:
                continue
            # Only wait on WB feeders that are still undecided. Resolved matches with
            # a bye (no real loser) must not block structural byes on this slot.
            incoming_wb = await session.execute(
                select(BracketMatch.id)
                .where(
                    BracketMatch.bracket_id == bracket_id,
                    BracketMatch.loser_advances_to_match_id == parent.id,
                    BracketMatch.loser_advances_to_slot == empty_slot,
                    BracketMatch.winner_team_id.is_(None),
                    BracketMatch.winner_player_id.is_(None),
                    BracketMatch.winner_manual_entry_id.is_(None),
                )
                .limit(1)
            )
            if incoming_wb.scalar_one_or_none() is not None:
                continue
            entity = e1 or e2
            if not entity:
                continue
            _assign_winner_from_entity(parent, entity, is_team)
            await session.flush()
            await advance_winner_to_parent(session, parent, is_team)
            changed = True
        if not changed:
            break


async def apply_double_elim_structural_byes(
    session: AsyncSession, bracket_id: int, is_team: bool
) -> None:
    """Run winners and losers structural bye passes; repeat once for cross-effects."""
    await apply_winners_bracket_structural_byes(session, bracket_id, is_team)
    await apply_losers_bracket_structural_byes(session, bracket_id, is_team)
    await apply_winners_bracket_structural_byes(session, bracket_id, is_team)
    await apply_losers_bracket_structural_byes(session, bracket_id, is_team)


async def advance_round_when_complete(
    session: AsyncSession, bracket_id: int, round_num: int, is_team: bool
) -> bool:
    """
    When all matches in a round have winners, advance them to the next round.
    When there is a structural bye, assign it to a path that has had the fewest prior
    bye advances (opening byes or earlier structural byes); ties are random.
    Remaining slots are shuffled. Only runs for single_elim; no-op if round incomplete.
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
        remaining_slots = [s for i, s in enumerate(all_slots) if i != bye_slot_idx]
        scores: list[tuple[int, BracketMatch]] = []
        for m, _, _ in winners:
            c = await count_prior_bye_wins_on_path(session, m, is_team)
            scores.append((c, m))
        min_score = min(s[0] for s in scores)
        candidates = [m for c, m in scores if c == min_score]
        chosen = random.choice(candidates)
        chosen.parent_match_id, chosen.parent_match_slot = bye_slot
        rest = [w[0] for w in winners if w[0] is not chosen]
        random.shuffle(remaining_slots)
        if len(rest) != len(remaining_slots):
            raise ValueError("Bye assignment: slot count mismatch")
        for m, slot in zip(rest, remaining_slots):
            m.parent_match_id, m.parent_match_slot = slot
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

    # Assign all advancing winners to the next round first. Structural-bye auto-wins
    # must run only after every slot is filled; otherwise we can recurse into the next
    # round before sibling matches receive their winners (skipping round posts).
    for winner in winners:
        m, entity = winner[0], winner[1]
        parent = await session.get(BracketMatch, m.parent_match_id)
        if not parent:
            continue
        _assign_entity_to_match(parent, m.parent_match_slot, entity, is_team)

    await session.flush()

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

    for parent in next_matches:
        has_s1 = bool(parent.team1_id or parent.player1_id or parent.manual_entry1_id)
        has_s2 = bool(parent.team2_id or parent.player2_id or parent.manual_entry2_id)
        if has_s1 and not has_s2 and (parent.id, 2) in structural_bye:
            if is_team:
                parent.winner_team_id = parent.team1_id
            elif parent.manual_entry1_id:
                parent.winner_manual_entry_id = parent.manual_entry1_id
            else:
                parent.winner_player_id = parent.player1_id
        elif has_s2 and not has_s1 and (parent.id, 1) in structural_bye:
            if is_team:
                parent.winner_team_id = parent.team2_id
            elif parent.manual_entry2_id:
                parent.winner_manual_entry_id = parent.manual_entry2_id
            else:
                parent.winner_player_id = parent.player2_id

    await session.flush()
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
    if n < 8:
        return await _create_single_elim_matches(
            session, tournament_id, seeded, is_team
        )

    bracket = Bracket(tournament_id=tournament_id, bracket_type="double_elim")
    session.add(bracket)
    await session.flush()

    matches: List[BracketMatch] = []
    match_num = 1
    w_r1_match_count = (n + 1) // 2
    w_layer_sizes = _winners_layer_sizes(w_r1_match_count)

    # Winners R1 — adjacent pairing (same as single elim R1)
    for i in range(w_r1_match_count):
        slot1 = seeded[2 * i] if 2 * i < n else None
        slot2 = seeded[2 * i + 1] if 2 * i + 1 < n else None
        m = BracketMatch(
            bracket_id=bracket.id,
            round_num=1,
            match_num=match_num,
            bracket_section="winners",
        )
        _assign_entity_to_match(m, 1, slot1, is_team)
        _assign_entity_to_match(m, 2, slot2, is_team)
        if slot2 is None and slot1 is not None:
            if is_team:
                m.winner_team_id = slot1[0]
            else:
                if slot1[2]:
                    m.winner_manual_entry_id = slot1[0][1]
                else:
                    m.winner_player_id = slot1[0]
        session.add(m)
        matches.append(m)
        match_num += 1

    w_round = 2
    for layer_sz in w_layer_sizes[1:]:
        for _ in range(layer_sz):
            m = BracketMatch(
                bracket_id=bracket.id,
                round_num=w_round,
                match_num=match_num,
                bracket_section="winners",
            )
            session.add(m)
            matches.append(m)
            match_num += 1
        w_round += 1

    # Losers bracket: L1 = ceil(W1/2) matches (W1 losers pair; odd W1 leaves one L1 bye path)
    l_r1_size = (w_r1_match_count + 1) // 2
    l_round_sizes = _double_elim_loser_round_sizes(l_r1_size, w_layer_sizes)
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

    # Winners bracket: link each round to next (ceil-halving tree)
    idx = 0
    for layer_idx in range(len(w_layer_sizes) - 1):
        r_sz = w_layer_sizes[layer_idx]
        for i in range(r_sz):
            m = w_matches[idx + i]
            next_m = w_matches[idx + r_sz + (i // 2)]
            m.parent_match_id = next_m.id
            m.parent_match_slot = (i % 2) + 1
        idx += r_sz

    # W R1 losers -> L R1 (pairs of W1 games); odd W1: last game loser -> L1[last] slot 1 only
    pairs = w_r1_match_count // 2
    for i in range(pairs):
        w_matches[i * 2].loser_advances_to_match_id = l_matches[i].id
        w_matches[i * 2].loser_advances_to_slot = 1
        w_matches[i * 2 + 1].loser_advances_to_match_id = l_matches[i].id
        w_matches[i * 2 + 1].loser_advances_to_slot = 2
    if w_r1_match_count % 2 == 1:
        w_matches[w_r1_match_count - 1].loser_advances_to_match_id = l_matches[
            l_r1_size - 1
        ].id
        w_matches[w_r1_match_count - 1].loser_advances_to_slot = 1

    # W R2 losers -> L R2 slot 2; L R1 winners -> L R2 slot 1
    w_r2_start = w_r1_match_count
    l_r2_start = l_r1_size
    for i in range(l_r1_size):
        w_m = w_matches[w_r2_start + i]
        l_m = l_matches[l_r2_start + i]
        w_m.loser_advances_to_match_id = l_m.id
        w_m.loser_advances_to_slot = 2
        l_matches[i].parent_match_id = l_m.id
        l_matches[i].parent_match_slot = 1

    # L bracket internal: L2 -> L3 -> … using layer sizes (ceil-halving rounds).
    l_starts = _l_layer_starts(l_round_sizes)
    for layer in range(1, len(l_round_sizes) - 1):
        cur_sz = l_round_sizes[layer]
        next_sz = l_round_sizes[layer + 1]
        prev_sz = l_round_sizes[layer - 1]
        next_start = l_starts[layer + 1]
        cur_start = l_starts[layer]
        # Parallel (WB-drop) round only immediately after a merge-down (prev wider than cur).
        # If prev == cur == next, two same-width layers in a row must merge into one row of
        # matches, not another parallel split — otherwise half the bracket never feeds forward.
        if next_sz == cur_sz and prev_sz > cur_sz:
            for i in range(cur_sz):
                l_m = l_matches[cur_start + i]
                next_l = l_matches[next_start + i]
                l_m.parent_match_id = next_l.id
                l_m.parent_match_slot = 1
        else:
            for i in range(cur_sz):
                l_m = l_matches[cur_start + i]
                next_l = l_matches[next_start + (i // 2)]
                l_m.parent_match_id = next_l.id
                l_m.parent_match_slot = (i % 2) + 1

    _wire_all_wb_loser_drops(w_matches, l_matches, w_layer_sizes, l_round_sizes)

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
