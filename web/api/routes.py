"""API routes for tournament configuration and bracket management."""
from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException

import config
from pydantic import BaseModel, ConfigDict, field_validator

from bot.models import User
from web.auth import require_moderator_user
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models import (
    Bracket,
    BracketMatch,
    Player,
    Registration,
    SiteSettings,
    Team,
    TeamManualMember,
    Tournament,
    TournamentManualEntry,
)
from bot.models.base import async_session_factory

from web.api.utils import player_display_name
from bot.models.tournament import parse_format_players

router = APIRouter(prefix="/api", tags=["tournaments"])


async def _refresh_player_names_from_discord(player_ids: list[int]) -> None:
    """Ask the bot to refresh display_name from Discord for these player_ids. No-op if bot unreachable."""
    if not player_ids or not config.INTERNAL_API_SECRET:
        return
    url = f"{config.BOT_INTERNAL_URL.rstrip('/')}/internal/refresh-players"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                url,
                json={"player_ids": player_ids},
                headers={"Authorization": f"Bearer {config.INTERNAL_API_SECRET}"},
            )
    except Exception:
        pass  # Best-effort; don't fail the request


# --- Pydantic schemas ---


class ManualEntryCreate(BaseModel):
    display_name: str
    epic_id: Optional[str] = None


class ManualEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    epic_id: Optional[str]
    list_type: str
    original_list_type: Optional[str] = None  # never changes; for standby recognition
    sort_order: int
    source: str = "manual"


class DiscordRegistrationResponse(BaseModel):
    """Discord signup (reaction or /tournament register). Shown in participants with source=discord."""

    id: str  # "discord:{player_id}"
    display_name: str
    player_id: int  # Discord user ID
    source: str = "discord"


class ManualEntryReorder(BaseModel):
    entry_ids: list[int]


class ManualEntryMove(BaseModel):
    list_type: str  # "participant" | "standby"


def _coerce_id(v):
    """Coerce int or str to int (handles Discord IDs sent as string for JS precision)."""
    if v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            return None
    return None


class BracketMatchUpdate(BaseModel):
    team1_id: Optional[int] = None
    team2_id: Optional[int] = None
    player1_id: Optional[int] = None
    player2_id: Optional[int] = None
    manual_entry1_id: Optional[int] = None
    manual_entry2_id: Optional[int] = None
    winner_team_id: Optional[int] = None
    winner_player_id: Optional[int] = None
    winner_manual_entry_id: Optional[int] = None

    @field_validator("player1_id", "player2_id", "winner_player_id", mode="before")
    @classmethod
    def coerce_player_id(cls, v):
        return _coerce_id(v)


class GenerateBracketRequest(BaseModel):
    use_manual_order: bool = True  # Use manual list order; if False, use MMR if available
    bracket_type: str = "single_elim"  # single_elim or double_elim
    participant_entry_ids: Optional[list[int]] = None  # Specific manual entries to use (in order)
    team_assignments: Optional[dict[str, list[int]]] = None  # team_name -> [player_ids or entry_ids]


class SubstituteRequest(BaseModel):
    team_id: int
    member_entry_id: int  # Participant leaving (manual entry id)
    standby_entry_id: int  # Standby joining


class TeamUpdate(BaseModel):
    name: str
    member_ids: list[int | str]  # Manual entry IDs (int) or "discord:player_id" (str) for Discord signups


class TeamsBulkUpdate(BaseModel):
    teams: list[TeamUpdate]


# --- Participants ---


@router.get("/tournaments/{tournament_id}/participants")
async def list_participants(tournament_id: int):
    """List participants: manual entries first, then Discord signups (reaction or /tournament register). Includes all Discord users for team format so they appear in Players/Teams view."""
    async with async_session_factory() as session:
        t = await session.get(Tournament, tournament_id)
        if not t:
            raise HTTPException(404, "Tournament not found")
        # Refresh Discord display names before loading (bot fetches from Discord API)
        regs_query = select(Registration.player_id).where(Registration.tournament_id == tournament_id)
        if t.format == "1v1":
            regs_query = regs_query.where(Registration.team_id.is_(None))
        regs_pre = await session.execute(regs_query)
        player_ids = list({r[0] for r in regs_pre.fetchall()})
        await _refresh_player_names_from_discord(player_ids)
        # Manual participants
        result = await session.execute(
            select(TournamentManualEntry)
            .where(
                TournamentManualEntry.tournament_id == tournament_id,
                TournamentManualEntry.list_type == "participant",
            )
            .order_by(TournamentManualEntry.sort_order, TournamentManualEntry.id)
        )
        manual = [ManualEntryResponse.model_validate(e) for e in result.scalars().all()]
        # Discord registrations (all of them for team format; unassigned only for 1v1)
        discord_list = []
        regs_query = select(Registration).where(Registration.tournament_id == tournament_id)
        if t.format == "1v1":
            regs_query = regs_query.where(Registration.team_id.is_(None))
        regs_result = await session.execute(
            regs_query.options(selectinload(Registration.player))
        )
        for reg in regs_result.scalars().all():
            discord_list.append(
                DiscordRegistrationResponse(
                    id=f"discord:{reg.player_id}",
                    display_name=player_display_name(reg.player, reg.player_id),
                    player_id=reg.player_id,
                )
            )
        # Manual first, then Discord
        return manual + discord_list


@router.post("/tournaments/{tournament_id}/participants")
async def add_participant(tournament_id: int, body: ManualEntryCreate, user: User = Depends(require_moderator_user)):
    """Add a manual participant."""
    async with async_session_factory() as session:
        t = await session.get(Tournament, tournament_id)
        if not t:
            raise HTTPException(404, "Tournament not found")
        result = await session.execute(
            select(TournamentManualEntry)
            .where(
                TournamentManualEntry.tournament_id == tournament_id,
                TournamentManualEntry.list_type == "participant",
            )
        )
        max_order = max((e.sort_order for e in result.scalars().all()), default=-1)
        entry = TournamentManualEntry(
            tournament_id=tournament_id,
            display_name=body.display_name,
            epic_id=body.epic_id,
            list_type="participant",
            original_list_type="participant",
            sort_order=max_order + 1,
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        return ManualEntryResponse.model_validate(entry)


@router.patch("/tournaments/{tournament_id}/participants/{entry_id}")
async def rename_participant(tournament_id: int, entry_id: int, body: ManualEntryCreate, user: User = Depends(require_moderator_user)):
    """Rename a manual participant."""
    async with async_session_factory() as session:
        entry = await session.get(TournamentManualEntry, entry_id)
        if not entry or entry.tournament_id != tournament_id or entry.list_type != "participant":
            raise HTTPException(404, "Participant not found")
        entry.display_name = body.display_name.strip() or entry.display_name
        await session.commit()
        await session.refresh(entry)
        return ManualEntryResponse.model_validate(entry)


@router.delete("/tournaments/{tournament_id}/participants/{entry_id}")
async def remove_participant(tournament_id: int, entry_id: int, user: User = Depends(require_moderator_user)):
    """Remove a manual participant."""
    async with async_session_factory() as session:
        entry = await session.get(TournamentManualEntry, entry_id)
        if not entry or entry.tournament_id != tournament_id or entry.list_type != "participant":
            raise HTTPException(404, "Participant not found")
        await session.delete(entry)
        await session.commit()
        return {"ok": True}


@router.patch("/tournaments/{tournament_id}/participants/reorder")
async def reorder_participants(tournament_id: int, body: ManualEntryReorder, user: User = Depends(require_moderator_user)):
    """Reorder participants by ID list (manual entries only)."""
    async with async_session_factory() as session:
        for i, eid in enumerate(body.entry_ids):
            if not isinstance(eid, int):
                continue
            entry = await session.get(TournamentManualEntry, eid)
            if entry and entry.tournament_id == tournament_id and entry.list_type == "participant":
                entry.sort_order = i
        await session.commit()
        return {"ok": True}


@router.delete("/tournaments/{tournament_id}/registrations/{player_id}")
async def remove_registration(tournament_id: int, player_id: int, user: User = Depends(require_moderator_user)):
    """Remove a Discord registration. If on a team, unassigns to participants; otherwise fully removes."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(Registration).where(
                Registration.tournament_id == tournament_id,
                Registration.player_id == player_id,
            )
        )
        reg = result.scalar_one_or_none()
        if not reg:
            raise HTTPException(404, "Registration not found")
        if reg.team_id:
            reg.team_id = None
        else:
            await session.delete(reg)
        await session.commit()
        return {"ok": True}


# --- Standby ---


@router.get("/tournaments/{tournament_id}/standby")
async def list_standby(tournament_id: int):
    """List standby/seat filler entries. Includes those originally standby (even if now substituted in)."""
    async with async_session_factory() as session:
        t = await session.get(Tournament, tournament_id)
        if not t:
            raise HTTPException(404, "Tournament not found")
        result = await session.execute(
            select(TournamentManualEntry)
            .where(
                TournamentManualEntry.tournament_id == tournament_id,
                # Show everyone originally standby (coalesce for migrated rows)
                (TournamentManualEntry.original_list_type == "standby")
                | ((TournamentManualEntry.original_list_type.is_(None)) & (TournamentManualEntry.list_type == "standby")),
            )
            .order_by(TournamentManualEntry.sort_order, TournamentManualEntry.id)
        )
        entries = result.scalars().all()
        return [ManualEntryResponse.model_validate(e) for e in entries]


@router.post("/tournaments/{tournament_id}/standby")
async def add_standby(tournament_id: int, body: ManualEntryCreate, user: User = Depends(require_moderator_user)):
    """Add a standby entry."""
    async with async_session_factory() as session:
        t = await session.get(Tournament, tournament_id)
        if not t:
            raise HTTPException(404, "Tournament not found")
        result = await session.execute(
            select(TournamentManualEntry)
            .where(
                TournamentManualEntry.tournament_id == tournament_id,
                TournamentManualEntry.list_type == "standby",
            )
        )
        max_order = max((e.sort_order for e in result.scalars().all()), default=-1)
        entry = TournamentManualEntry(
            tournament_id=tournament_id,
            display_name=body.display_name,
            epic_id=body.epic_id,
            list_type="standby",
            original_list_type="standby",
            sort_order=max_order + 1,
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        return ManualEntryResponse.model_validate(entry)


@router.patch("/tournaments/{tournament_id}/standby/{entry_id}")
async def rename_standby(tournament_id: int, entry_id: int, body: ManualEntryCreate, user: User = Depends(require_moderator_user)):
    """Rename a standby entry (including those substituted in)."""
    async with async_session_factory() as session:
        entry = await session.get(TournamentManualEntry, entry_id)
        if not entry or entry.tournament_id != tournament_id:
            raise HTTPException(404, "Standby entry not found")
        is_standby = (
            entry.original_list_type == "standby"
            or (entry.original_list_type is None and entry.list_type == "standby")
        )
        if not is_standby:
            raise HTTPException(404, "Standby entry not found")
        entry.display_name = body.display_name.strip() or entry.display_name
        await session.commit()
        await session.refresh(entry)
        return ManualEntryResponse.model_validate(entry)


@router.delete("/tournaments/{tournament_id}/standby/{entry_id}")
async def remove_standby(tournament_id: int, entry_id: int, user: User = Depends(require_moderator_user)):
    """Remove a standby entry."""
    async with async_session_factory() as session:
        entry = await session.get(TournamentManualEntry, entry_id)
        if not entry or entry.tournament_id != tournament_id or entry.list_type != "standby":
            raise HTTPException(404, "Standby entry not found")
        await session.delete(entry)
        await session.commit()
        return {"ok": True}


@router.patch("/tournaments/{tournament_id}/manual-entries/{entry_id}/move")
async def move_manual_entry(
    tournament_id: int, entry_id: int, body: ManualEntryMove, user: User = Depends(require_moderator_user)
):
    """Move a manual entry between participants and standby."""
    if body.list_type not in ("participant", "standby"):
        raise HTTPException(400, "list_type must be 'participant' or 'standby'")
    async with async_session_factory() as session:
        entry = await session.get(TournamentManualEntry, entry_id)
        if not entry or entry.tournament_id != tournament_id:
            raise HTTPException(404, "Entry not found")
        if entry.list_type == body.list_type:
            await session.refresh(entry)
            return ManualEntryResponse.model_validate(entry)
        result = await session.execute(
            select(TournamentManualEntry)
            .where(
                TournamentManualEntry.tournament_id == tournament_id,
                TournamentManualEntry.list_type == body.list_type,
            )
        )
        max_order = max((e.sort_order for e in result.scalars().all()), default=-1)
        entry.list_type = body.list_type
        entry.original_list_type = body.list_type
        entry.sort_order = max_order + 1
        if body.list_type == "standby":
            await session.execute(delete(TeamManualMember).where(TeamManualMember.manual_entry_id == entry_id))
        await session.commit()
        await session.refresh(entry)
        return ManualEntryResponse.model_validate(entry)


@router.patch("/tournaments/{tournament_id}/standby/reorder")
async def reorder_standby(tournament_id: int, body: ManualEntryReorder, user: User = Depends(require_moderator_user)):
    """Reorder standby entries."""
    async with async_session_factory() as session:
        for i, eid in enumerate(body.entry_ids):
            entry = await session.get(TournamentManualEntry, eid)
            if entry and entry.tournament_id == tournament_id and entry.list_type == "standby":
                entry.sort_order = i
        await session.commit()
        return {"ok": True}


# --- Teams (for 2v2, 3v3, 4v4) ---


@router.put("/tournaments/{tournament_id}/teams")
async def update_teams(tournament_id: int, body: TeamsBulkUpdate, user: User = Depends(require_moderator_user)):
    """Replace all teams with the given structure. Removes existing bracket. Use for drag-drop editing."""
    async with async_session_factory() as session:
        t = await session.get(Tournament, tournament_id)
        if not t or t.format == "1v1":
            raise HTTPException(404, "Tournament not found or not a team format")
        players_per_team = parse_format_players(t.format)
        for team_data in body.teams:
            if len(team_data.member_ids) > players_per_team:
                raise HTTPException(400, f"Team '{team_data.name}' has too many members for {t.format}")
        await session.execute(update(Registration).where(Registration.tournament_id == tournament_id).values(team_id=None))
        existing_teams = await session.execute(select(Team).where(Team.tournament_id == tournament_id))
        for team in existing_teams.scalars().all():
            await session.delete(team)
        existing_bracket = await session.execute(select(Bracket).where(Bracket.tournament_id == tournament_id))
        bracket = existing_bracket.scalar_one_or_none()
        if bracket:
            await session.delete(bracket)
        await session.flush()
        created = []
        for team_data in body.teams:
            team = Team(tournament_id=tournament_id, name=team_data.name or "Unnamed")
            session.add(team)
            await session.flush()
            for i, member_ref in enumerate(team_data.member_ids):
                if member_ref is None:
                    continue
                if isinstance(member_ref, str) and member_ref.startswith("discord:"):
                    try:
                        player_id = int(member_ref.replace("discord:", ""))
                    except ValueError:
                        continue
                    reg_result = await session.execute(
                        select(Registration).where(
                            Registration.tournament_id == tournament_id,
                            Registration.player_id == player_id,
                        )
                    )
                    reg = reg_result.scalar_one_or_none()
                    if reg:
                        reg.team_id = team.id
                else:
                    eid = int(member_ref) if not isinstance(member_ref, int) else member_ref
                    entry = await session.get(TournamentManualEntry, eid)
                    if entry and entry.tournament_id == tournament_id:
                        session.add(TeamManualMember(team_id=team.id, manual_entry_id=eid, sort_order=i))
            created.append({"id": team.id, "name": team.name})
        await session.commit()
        return {"ok": True, "teams": created}


@router.get("/tournaments/{tournament_id}/teams")
async def list_teams(tournament_id: int):
    """List teams with their members (for team-format tournaments)."""
    async with async_session_factory() as session:
        t = await session.get(Tournament, tournament_id)
        if not t:
            raise HTTPException(404, "Tournament not found")
        if t.format == "1v1":
            return []
        # Refresh Discord display names before loading (bot fetches from Discord API)
        regs_pre = await session.execute(
            select(Registration.player_id).where(Registration.tournament_id == tournament_id)
        )
        player_ids = list({r[0] for r in regs_pre.fetchall()})
        await _refresh_player_names_from_discord(player_ids)
        result = await session.execute(
            select(Team)
            .where(Team.tournament_id == tournament_id)
            .options(
                selectinload(Team.manual_members).selectinload(TeamManualMember.manual_entry),
                selectinload(Team.members).selectinload(Registration.player),
            )
        )
        teams = result.scalars().all()
        members_by_team: dict[int, list[dict]] = {}
        for team in teams:
            manual = [
                {"id": m.manual_entry.id, "display_name": m.manual_entry.display_name}
                for m in sorted(team.manual_members, key=lambda x: x.sort_order)
            ]
            discord = [
                {"id": f"discord:{r.player_id}", "display_name": player_display_name(r.player, r.player_id)}
                for r in team.members
            ]
            members_by_team[team.id] = manual + discord
        return [
            {"id": team.id, "name": team.name, "members": members_by_team.get(team.id, [])}
            for team in teams
        ]


@router.post("/tournaments/{tournament_id}/teams/substitute")
async def substitute_standby(tournament_id: int, body: SubstituteRequest):
    """Replace a team member (who left) with a standby player."""
    async with async_session_factory() as session:
        t = await session.get(Tournament, tournament_id)
        if not t or t.format == "1v1":
            raise HTTPException(404, "Tournament not found or not a team format")
        team = await session.get(Team, body.team_id)
        if not team or team.tournament_id != tournament_id:
            raise HTTPException(404, "Team not found")
        member_entry = await session.get(TournamentManualEntry, body.member_entry_id)
        standby_entry = await session.get(TournamentManualEntry, body.standby_entry_id)
        if not member_entry or member_entry.tournament_id != tournament_id:
            raise HTTPException(404, "Member not found")
        if not standby_entry or standby_entry.tournament_id != tournament_id or standby_entry.list_type != "standby":
            raise HTTPException(404, "Standby entry not found")
        tmm = await session.execute(
            select(TeamManualMember).where(
                TeamManualMember.team_id == body.team_id,
                TeamManualMember.manual_entry_id == body.member_entry_id,
            )
        )
        tmm = tmm.scalar_one_or_none()
        if not tmm:
            raise HTTPException(404, "Member not in this team")
        tmm.manual_entry_id = body.standby_entry_id
        standby_entry.list_type = "participant"
        await session.commit()
        return {"ok": True}


@router.post("/tournaments/{tournament_id}/teams/regenerate")
async def regenerate_teams(tournament_id: int, user: User = Depends(require_moderator_user)):
    """Regenerate teams from participants + standby (manual and Discord), then regenerate bracket. Use when players leave and you need to rebalance."""
    from bot.services.bracket_gen import create_manual_bracket

    async with async_session_factory() as session:
        t = await session.get(Tournament, tournament_id)
        if not t or t.format == "1v1":
            raise HTTPException(404, "Tournament not found or not a team format")
        players_per_team = parse_format_players(t.format)

        # Build pool: participants first, then Discord, then standby (standby used last)
        participants_result = await session.execute(
            select(TournamentManualEntry)
            .where(
                TournamentManualEntry.tournament_id == tournament_id,
                TournamentManualEntry.list_type == "participant",
            )
            .order_by(TournamentManualEntry.sort_order, TournamentManualEntry.id)
        )
        manual_participants = list(participants_result.scalars().all())

        regs_result = await session.execute(
            select(Registration)
            .where(Registration.tournament_id == tournament_id)
            .options(selectinload(Registration.player))
        )
        discord_regs = list(regs_result.scalars().all())

        standby_result = await session.execute(
            select(TournamentManualEntry)
            .where(
                TournamentManualEntry.tournament_id == tournament_id,
                TournamentManualEntry.list_type == "standby",
            )
            .order_by(TournamentManualEntry.sort_order, TournamentManualEntry.id)
        )
        manual_standby = list(standby_result.scalars().all())
        # Do NOT change list_type to "participant" - that would create duplicates (standby
        # would appear in both participants and standby lists, breaking subsequent regenerations)

        # Pool order: participants, Discord, standby (standby used last when filling)
        pool: list[tuple[str, object]] = [(e, "manual") for e in manual_participants]
        pool += [(r, "discord") for r in discord_regs]
        pool += [(e, "manual") for e in manual_standby]
        random.shuffle(pool)

        if len(pool) < players_per_team:
            raise HTTPException(400, f"Need at least {players_per_team} players to form teams")

        # Clear team assignments before deleting teams (keeps Discord users in participants list)
        await session.execute(update(Registration).where(Registration.tournament_id == tournament_id).values(team_id=None))
        await session.flush()  # Ensure update is applied before delete (avoids FK/cascade issues)
        existing_teams = await session.execute(select(Team).where(Team.tournament_id == tournament_id))
        for team in existing_teams.scalars().all():
            await session.delete(team)
        existing_bracket = await session.execute(select(Bracket).where(Bracket.tournament_id == tournament_id))
        bracket = existing_bracket.scalar_one_or_none()
        if bracket:
            await session.delete(bracket)
        await session.flush()

        team_num = 0
        for i in range(0, len(pool), players_per_team):
            chunk = pool[i : i + players_per_team]
            if len(chunk) < players_per_team:
                break
            team = Team(tournament_id=tournament_id, name=f"Team {team_num + 1}")
            session.add(team)
            await session.flush()
            for j, (item, kind) in enumerate(chunk):
                if kind == "manual":
                    session.add(TeamManualMember(team_id=team.id, manual_entry_id=item.id, sort_order=j))
                else:
                    # Re-query Registration after teams were deleted (like update_teams)
                    reg_result = await session.execute(
                        select(Registration).where(
                            Registration.tournament_id == tournament_id,
                            Registration.player_id == item.player_id,
                        )
                    )
                    reg = reg_result.scalar_one_or_none()
                    if reg:
                        reg.team_id = team.id
            team_num += 1
        bracket = await create_manual_bracket(session, tournament_id, {})
        await session.commit()
        return {"ok": True, "teams_created": team_num}


# --- Tournaments ---


class TournamentCreate(BaseModel):
    name: str
    format: str = "1v1"  # 1v1, 2v2, 3v3, 4v4, custom
    guild_id: Optional[int] = None  # Optional; 0 for web-only
    registration_deadline: Optional[str] = None  # ISO datetime, e.g. 2026-02-24T18:00:00


def _mmr_for_format(fmt: str) -> str:
    if fmt == "1v1":
        return "solo_duel"
    if fmt == "2v2":
        return "doubles"
    return "standard"


def _parse_deadline(s: Optional[str]):
    """Parse ISO datetime string to UTC datetime."""
    if not s or not s.strip():
        return None
    s = s.strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


@router.post("/tournaments")
async def create_tournament(body: TournamentCreate):
    """Create a tournament (for web UI; guild_id=0 for non-Discord use)."""
    reg_deadline = _parse_deadline(body.registration_deadline)
    async with async_session_factory() as session:
        t = Tournament(
            guild_id=body.guild_id or 0,
            name=body.name,
            format=body.format,
            mmr_playlist=_mmr_for_format(body.format),
            status="open",
            registration_deadline=reg_deadline,
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)
        return {"id": t.id, "name": t.name, "format": t.format, "registration_deadline": t.registration_deadline.isoformat() if t.registration_deadline else None}


@router.get("/winners")
async def list_winners():
    """List all-time tournament champions (completed, closed, or archived tournaments with a bracket winner)."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(Tournament)
            .where(
                or_(
                    Tournament.status == "completed",
                    Tournament.status == "closed",
                    Tournament.archived == True,  # noqa: E712
                )
            )
            .order_by(Tournament.id.desc())
            .limit(100)
        )
        tournaments = result.scalars().all()
        winners = []
        for t in tournaments:
            bracket_result = await session.execute(
                select(Bracket)
                .where(Bracket.tournament_id == t.id)
                .order_by(Bracket.id.desc())
                .limit(1)
            )
            bracket = bracket_result.scalar_one_or_none()
            if not bracket:
                continue
            # Find champion: grand_finals match (double elim) or highest round (single elim)
            matches_result = await session.execute(
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
            champ_matches = matches_result.scalars().all()
            champ_match = None
            for m in champ_matches:
                if m.bracket_section == "grand_finals":
                    champ_match = m
                    break
            if not champ_match and champ_matches:
                # Single elim: final has highest round_num (and typically highest match_num in that round)
                champ_match = max(champ_matches, key=lambda x: (x.round_num, x.match_num))
            if not champ_match:
                continue
            winner_name = None
            winner_players = None  # List of player names for team formats
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
                    winner_name = team.name
                    player_names = []
                    for reg in team.members:
                        if reg.player:
                            player_names.append(player_display_name(reg.player, reg.player_id))
                    for tmm in sorted(team.manual_members, key=lambda x: x.sort_order):
                        if tmm.manual_entry:
                            player_names.append(tmm.manual_entry.display_name)
                    if player_names:
                        winner_players = player_names
            elif champ_match.winner_player_id:
                player = await session.get(Player, champ_match.winner_player_id)
                winner_name = player_display_name(player, champ_match.winner_player_id) if player else None
            elif champ_match.winner_manual_entry_id:
                entry = await session.get(TournamentManualEntry, champ_match.winner_manual_entry_id)
                winner_name = entry.display_name if entry else None
            if winner_name:
                row = {
                    "tournament_id": t.id,
                    "tournament_name": t.name,
                    "format": t.format,
                    "winner_name": winner_name,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                if winner_players is not None:
                    row["winner_players"] = winner_players
                winners.append(row)
        return winners


@router.get("/tournaments")
async def list_tournaments(include_archived: bool = False):
    """List tournaments. By default excludes archived. Use ?include_archived=1 to include them."""
    async with async_session_factory() as session:
        q = select(Tournament).order_by(Tournament.id.desc()).limit(50)
        if not include_archived:
            q = q.where(Tournament.archived == False)  # noqa: E712
        result = await session.execute(q)
        tournaments = result.scalars().all()
        return [
            {
                "id": t.id,
                "name": t.name,
                "format": t.format,
                "status": t.status,
                "archived": t.archived,
                "registration_deadline": t.registration_deadline.isoformat() if t.registration_deadline else None,
            }
            for t in tournaments
        ]


class TournamentUpdate(BaseModel):
    name: Optional[str] = None
    format: Optional[str] = None
    status: Optional[str] = None
    archived: Optional[bool] = None
    registration_deadline: Optional[str] = None  # ISO datetime; empty string to clear


@router.patch("/tournaments/{tournament_id}")
async def update_tournament(tournament_id: int, body: TournamentUpdate, user: User = Depends(require_moderator_user)):
    """Rename or update a tournament. Format change clears teams/bracket when switching to 1v1."""
    async with async_session_factory() as session:
        t = await session.get(Tournament, tournament_id)
        if not t:
            raise HTTPException(404, "Tournament not found")
        if body.name is not None:
            t.name = body.name
        if body.format is not None:
            old_format = t.format
            t.format = body.format
            t.mmr_playlist = _mmr_for_format(body.format)
            if old_format != body.format:
                if body.format == "1v1":
                    for team in (await session.execute(select(Team).where(Team.tournament_id == tournament_id))).scalars().all():
                        await session.delete(team)
                    bracket = (await session.execute(select(Bracket).where(Bracket.tournament_id == tournament_id))).scalar_one_or_none()
                    if bracket:
                        await session.delete(bracket)
                elif old_format == "1v1":
                    for team in (await session.execute(select(Team).where(Team.tournament_id == tournament_id))).scalars().all():
                        await session.delete(team)
                    bracket = (await session.execute(select(Bracket).where(Bracket.tournament_id == tournament_id))).scalar_one_or_none()
                    if bracket:
                        await session.delete(bracket)
        if body.status is not None:
            t.status = body.status
        if body.archived is not None:
            t.archived = body.archived
        if body.registration_deadline is not None:
            t.registration_deadline = _parse_deadline(body.registration_deadline)
        await session.commit()
        await session.refresh(t)
        return {
            "id": t.id,
            "name": t.name,
            "format": t.format,
            "status": t.status,
            "registration_deadline": t.registration_deadline.isoformat() if t.registration_deadline else None,
        }


class CloneTournamentRequest(BaseModel):
    name: Optional[str] = None  # Default: "{original} (copy)"
    format: Optional[str] = None  # Default: same as source


@router.post("/tournaments/{tournament_id}/clone")
async def clone_tournament(
    tournament_id: int,
    body: Optional[CloneTournamentRequest] = None,
    user: User = Depends(require_moderator_user),
):
    """Clone a tournament with its participants and standby. Optionally set new name/format."""
    async with async_session_factory() as session:
        src = await session.get(Tournament, tournament_id)
        if not src:
            raise HTTPException(404, "Tournament not found")
        req = body.model_dump() if body else {}
        name = req.get("name") or f"{src.name} (copy)"
        fmt = req.get("format") or src.format
        t = Tournament(
            guild_id=src.guild_id,
            name=name,
            format=fmt,
            mmr_playlist=_mmr_for_format(fmt),
            status="open",
            archived=False,
        )
        session.add(t)
        await session.flush()
        result = await session.execute(
            select(TournamentManualEntry)
            .where(TournamentManualEntry.tournament_id == tournament_id)
            .order_by(TournamentManualEntry.list_type, TournamentManualEntry.sort_order, TournamentManualEntry.id)
        )
        entries = result.scalars().all()
        for e in entries:
            new_entry = TournamentManualEntry(
                tournament_id=t.id,
                display_name=e.display_name,
                epic_id=e.epic_id,
                list_type=e.list_type,
                original_list_type=e.original_list_type or e.list_type,
                sort_order=e.sort_order,
            )
            session.add(new_entry)
        await session.commit()
        await session.refresh(t)
        return {"id": t.id, "name": t.name, "format": t.format}


class PostSignupRequest(BaseModel):
    channel_id: Optional[int] = None
    guild_id: Optional[int] = None


@router.post("/tournaments/{tournament_id}/post-signup")
async def post_signup_to_discord(
    tournament_id: int,
    body: Optional[PostSignupRequest] = None,
    user: User = Depends(require_moderator_user),
):
    """Trigger the bot to post the signup message to Discord. Requires Discord settings configured in Settings."""
    if not config.INTERNAL_API_SECRET:
        raise HTTPException(503, "INTERNAL_API_SECRET not configured. Set it in .env to enable web-triggered signup.")
    async with async_session_factory() as session:
        t = await session.get(Tournament, tournament_id)
        if not t:
            raise HTTPException(404, "Tournament not found")
        if t.status != "open":
            raise HTTPException(400, f"Tournament is {t.status}. Set status to 'open' before posting signup.")
        # Get guild_id and channel_id from body or site settings
        guild_id = body.guild_id if body and body.guild_id else None
        channel_id = body.channel_id if body and body.channel_id else None
        if not guild_id or not channel_id:
            result = await session.execute(
                select(SiteSettings).where(
                    SiteSettings.key.in_(["discord_guild_id", "discord_signup_channel_id"])
                )
            )
            settings = {row.key: row.value for row in result.scalars().all()}
            try:
                guild_id = guild_id or (int(settings["discord_guild_id"]) if settings.get("discord_guild_id") else None)
                channel_id = channel_id or (int(settings["discord_signup_channel_id"]) if settings.get("discord_signup_channel_id") else None)
            except (ValueError, TypeError):
                guild_id = guild_id or None
                channel_id = channel_id or None
        if not guild_id or not channel_id:
            raise HTTPException(
                400,
                "Configure Discord guild and channel in Settings (Discord signup) first, or pass channel_id and guild_id in the request body.",
            )
    url = f"{config.BOT_INTERNAL_URL.rstrip('/')}/internal/post-signup"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                url,
                json={"tournament_id": tournament_id, "channel_id": channel_id, "guild_id": guild_id},
                headers={"Authorization": f"Bearer {config.INTERNAL_API_SECRET}"},
            )
    except httpx.ConnectError as e:
        logging.getLogger("octane").warning("Failed to reach bot for post-signup: %s", e)
        raise HTTPException(503, "Could not reach the Discord bot. Ensure it is running and BOT_INTERNAL_URL is correct.")
    except Exception as e:
        logging.getLogger("octane").exception("post-signup request failed")
        raise HTTPException(503, str(e))
    if r.status_code != 200:
        try:
            err = r.json()
            msg = err.get("error", r.text)
        except Exception:
            msg = r.text
        raise HTTPException(r.status_code if r.status_code < 500 else 503, msg)
    return r.json()


@router.delete("/tournaments/{tournament_id}")
async def delete_tournament(tournament_id: int, user: User = Depends(require_moderator_user)):
    """Delete a tournament and all its data."""
    async with async_session_factory() as session:
        t = await session.get(Tournament, tournament_id)
        if not t:
            raise HTTPException(404, "Tournament not found")
        name = t.name
        await session.delete(t)
        await session.commit()
        return {"ok": True, "deleted": name}


# --- Bracket generation (manual) ---


@router.post("/tournaments/{tournament_id}/bracket/generate")
async def generate_bracket(tournament_id: int, body: Optional[GenerateBracketRequest] = None, user: User = Depends(require_moderator_user)):
    """Generate bracket from manual participants (and optionally Discord registrations)."""
    from bot.services.bracket_gen import create_manual_bracket

    req = body.model_dump() if body else {}
    async with async_session_factory() as session:
        t = await session.get(Tournament, tournament_id)
        if not t:
            raise HTTPException(404, "Tournament not found")
        existing = await session.execute(
            select(Bracket).where(Bracket.tournament_id == tournament_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(400, "Bracket already exists")
        try:
            bracket = await create_manual_bracket(session, tournament_id, req)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not bracket:
            raise HTTPException(400, "Could not generate bracket. Add participants first.")
        return {"ok": True, "bracket_id": bracket.id}


@router.post("/tournaments/{tournament_id}/bracket/regenerate")
async def regenerate_bracket(tournament_id: int, body: Optional[GenerateBracketRequest] = None, user: User = Depends(require_moderator_user)):
    """Delete existing bracket and generate a new one from current participants/teams."""
    from bot.services.bracket_gen import create_manual_bracket

    req = body.model_dump() if body else {}
    async with async_session_factory() as session:
        t = await session.get(Tournament, tournament_id)
        if not t:
            raise HTTPException(404, "Tournament not found")
        existing = await session.execute(
            select(Bracket).where(Bracket.tournament_id == tournament_id)
        )
        bracket = existing.scalar_one_or_none()
        if bracket:
            await session.delete(bracket)
            await session.flush()
        try:
            bracket = await create_manual_bracket(session, tournament_id, req)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not bracket:
            raise HTTPException(400, "Could not generate bracket. Add participants first.")
        return {"ok": True, "bracket_id": bracket.id}


# --- Bracket match updates (for drag-drop) ---


class SwapSlotsRequest(BaseModel):
    from_match_id: int
    from_slot: int
    to_match_id: int
    to_slot: int


@router.post("/tournaments/{tournament_id}/bracket/matches/swap-slots")
async def swap_slots_route(
    tournament_id: int, body: SwapSlotsRequest, user: User = Depends(require_moderator_user)
):
    """Swap or move entities between two bracket slots. Clears winners for affected matches."""
    from bot.services.bracket_gen import swap_slots

    async with async_session_factory() as session:
        try:
            await swap_slots(
                session,
                tournament_id,
                body.from_match_id,
                body.from_slot,
                body.to_match_id,
                body.to_slot,
            )
            await session.commit()
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}


@router.post("/tournaments/{tournament_id}/bracket/matches/{match_id}/clear-winner")
async def clear_match_winner_route(
    tournament_id: int, match_id: int, user: User = Depends(require_moderator_user)
):
    """Clear the winner of a match. Use when a result was set incorrectly and you need to undo."""
    from bot.services.bracket_gen import clear_match_winner

    async with async_session_factory() as session:
        try:
            await clear_match_winner(session, match_id, tournament_id)
            await session.commit()
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}


@router.post("/tournaments/{tournament_id}/bracket/matches/{match_id}/swap-winner")
async def swap_match_winner_route(
    tournament_id: int, match_id: int, user: User = Depends(require_moderator_user)
):
    """Swap the winner of a match to the other team. Use when a result was reported incorrectly."""
    from bot.services.bracket_gen import swap_match_winner

    async with async_session_factory() as session:
        try:
            await swap_match_winner(session, match_id, tournament_id)
            await session.commit()
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}


def _champion_match_has_winner(matches_with_winners: list, bracket_type: str) -> bool:
    """True if the champion (final) match among these has a winner set."""
    if not matches_with_winners:
        return False
    if bracket_type == "double_elim":
        for m in matches_with_winners:
            if m.bracket_section == "grand_finals":
                return True
        return False
    # Single elim: final has highest round_num among matches with bracket_section None
    single_elim_matches = [m for m in matches_with_winners if m.bracket_section is None]
    if not single_elim_matches:
        return False
    max_round = max(m.round_num for m in single_elim_matches)
    return any(m.round_num == max_round for m in single_elim_matches)


@router.patch("/tournaments/{tournament_id}/bracket/matches/{match_id}")
async def update_match(
    tournament_id: int,
    match_id: int,
    body: BracketMatchUpdate,
    user: User = Depends(require_moderator_user),
):
    """Update a bracket match (assign teams/players, set winner). Single elim: advance when round complete (randomize bye, exclude teams that had bye). Double elim: advance immediately. Auto-sets tournament to completed when champion is declared."""
    from bot.services.bracket_gen import advance_round_when_complete, advance_winner_to_parent

    async with async_session_factory() as session:
        match = await session.get(BracketMatch, match_id)
        if not match:
            raise HTTPException(404, "Match not found")
        bracket = await session.get(Bracket, match.bracket_id)
        if not bracket or bracket.tournament_id != tournament_id:
            raise HTTPException(404, "Match not found")
        t = await session.get(Tournament, bracket.tournament_id)
        is_team = t and t.format != "1v1"
        # Use exclude_unset to allow explicit null (e.g. clear slot when team drops out)
        updates = body.model_dump(exclude_unset=True)
        winner_updated = any(k in updates for k in ("winner_team_id", "winner_player_id", "winner_manual_entry_id"))
        if winner_updated:
            # When setting a winner, clear the other winner fields to avoid conflicting data
            if "winner_team_id" not in updates:
                match.winner_team_id = None
            if "winner_player_id" not in updates:
                match.winner_player_id = None
            if "winner_manual_entry_id" not in updates:
                match.winner_manual_entry_id = None
        for key, value in updates.items():
            if hasattr(match, key):
                setattr(match, key, value)
        try:
            if winner_updated:
                await session.flush()  # Ensure winner is visible to advancement queries
                if bracket.bracket_type == "single_elim":
                    await advance_round_when_complete(session, bracket.id, match.round_num, is_team)
                else:
                    await advance_winner_to_parent(session, match, is_team)
                # Auto-complete tournament when champion is declared (direct or via advancement)
                champ_matches_result = await session.execute(
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
                champ_matches = champ_matches_result.scalars().all()
                if _champion_match_has_winner(champ_matches, bracket.bracket_type):
                    t.status = "completed"
            await session.commit()
        except Exception as e:
            await session.rollback()
            detail = str(e)
            import logging
            logging.exception("update_match failed")
            # Use 400 so nginx passes through; 500 often gets replaced with HTML error page
            raise HTTPException(400, f"Failed to update match: {detail}")
        return {"ok": True}
