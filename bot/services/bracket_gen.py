"""Bracket generation service."""
from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models import Bracket, BracketMatch, Registration, Team, Tournament
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
            player_data = await rl_service.get_player_by_epic_id(reg.player.epic_id)
            if player_data:
                info = rl_service.get_playlist_mmr(player_data, mmr_playlist)
                if info:
                    mmr_list.append((reg.player_id, info[0], False))
        else:
            if reg.team_id and reg.team_id not in seen_teams:
                seen_teams.add(reg.team_id)
                team = await session.get(Team, reg.team_id)
                if team:
                    team_mmrs = []
                    for m in team.members:
                        player_data = await rl_service.get_player_by_epic_id(m.player.epic_id)
                        if player_data:
                            info = rl_service.get_playlist_mmr(player_data, mmr_playlist)
                            if info:
                                team_mmrs.append(info[0])
                    if team_mmrs:
                        avg_mmr = sum(team_mmrs) // len(team_mmrs)
                        mmr_list.append((reg.team_id, avg_mmr, True))

    mmr_list.sort(key=lambda x: x[1], reverse=True)
    return mmr_list


def next_power_of_2(n: int) -> int:
    """Round up to next power of 2."""
    p = 1
    while p < n:
        p *= 2
    return p


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
