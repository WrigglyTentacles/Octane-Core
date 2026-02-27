"""FastAPI bracket API - serves bracket data and built web UI."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models import Bracket, BracketMatch, Player, Registration, Team, TeamManualMember, Tournament, TournamentManualEntry
from bot.models.base import async_session_factory, init_db

from web.api.routes import router as api_router, _refresh_player_names_from_discord
from web.api.utils import player_display_name
from web.api.auth_routes import router as auth_router
from web.api.settings_routes import router as settings_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Octane-Core Bracket API", lifespan=lifespan)

# SPA fallback: serve index.html for non-API 404s so client-side routes work
_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"


class SPAFallbackMiddleware(BaseHTTPMiddleware):
    """Serve index.html for 404s on non-API paths (enables /login, /settings, etc.)."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if response.status_code == 404 and not request.url.path.startswith("/api"):
            index_path = _frontend_dist / "index.html"
            if index_path.exists():
                return FileResponse(str(index_path), media_type="text/html")
        return response


if _frontend_dist.exists():
    app.add_middleware(SPAFallbackMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)
app.include_router(auth_router)
app.include_router(settings_router)


@app.get("/api/tournaments/{tournament_id}/bracket")
async def get_bracket(tournament_id: int):
    """Get bracket data for a tournament."""
    async with async_session_factory() as session:
        t = await session.get(Tournament, tournament_id)
        if not t:
            return {"error": "Tournament not found"}
        result = await session.execute(select(Bracket).where(Bracket.tournament_id == tournament_id))
        bracket = result.scalar_one_or_none()
        if not bracket:
            return {"error": "No bracket generated"}
        matches_result = await session.execute(
            select(BracketMatch)
            .where(BracketMatch.bracket_id == bracket.id)
            .order_by(BracketMatch.round_num, BracketMatch.match_num)
        )
        matches = matches_result.scalars().all()
        is_team = t.format != "1v1"
        # Refresh Discord display names for 1v1 bracket (bot fetches from Discord API)
        if not is_team:
            player_ids = []
            for m in matches:
                if m.player1_id:
                    player_ids.append(m.player1_id)
                if m.player2_id:
                    player_ids.append(m.player2_id)
                if m.winner_player_id:
                    player_ids.append(m.winner_player_id)
            await _refresh_player_names_from_discord(list(set(player_ids)))
        rounds = {}
        for m in matches:
            r = m.round_num
            if r not in rounds:
                rounds[r] = []
            # Return Discord player IDs as strings so JS preserves precision (snowflakes > 2^53)
            def _id_for_json(v):
                if v is None:
                    return None
                return str(v) if v > 9007199254740991 else v

            match_data = {
                "id": m.id,
                "match_num": m.match_num,
                "round_num": m.round_num,
                "bracket_section": m.bracket_section or "winners",
                "parent_match_id": m.parent_match_id,
                "parent_match_slot": m.parent_match_slot,
                "team1_id": m.team1_id,
                "team2_id": m.team2_id,
                "player1_id": _id_for_json(m.player1_id),
                "player2_id": _id_for_json(m.player2_id),
                "manual_entry1_id": m.manual_entry1_id,
                "manual_entry2_id": m.manual_entry2_id,
                "winner_team_id": m.winner_team_id,
                "winner_player_id": _id_for_json(m.winner_player_id),
                "winner_manual_entry_id": m.winner_manual_entry_id,
            }
            if is_team and m.team1_id:
                team = await session.get(Team, m.team1_id)
                if team:
                    match_data["team1_name"] = team.name
            if is_team and m.team2_id:
                team = await session.get(Team, m.team2_id)
                if team:
                    match_data["team2_name"] = team.name
            if not is_team and m.player1_id:
                player = await session.get(Player, m.player1_id)
                match_data["player1_name"] = player_display_name(player, m.player1_id)
            if not is_team and m.player2_id:
                player = await session.get(Player, m.player2_id)
                match_data["player2_name"] = player_display_name(player, m.player2_id)
            if not is_team and m.manual_entry1_id:
                entry = await session.get(TournamentManualEntry, m.manual_entry1_id)
                if entry:
                    match_data["player1_name"] = entry.display_name
            if not is_team and m.manual_entry2_id:
                entry = await session.get(TournamentManualEntry, m.manual_entry2_id)
                if entry:
                    match_data["player2_name"] = entry.display_name
            # Empty slot 2 with filled slot 1 = bye (opponent advances automatically)
            if not (m.team2_id or m.player2_id or m.manual_entry2_id) and (m.team1_id or m.player1_id or m.manual_entry1_id):
                match_data["team2_name" if is_team else "player2_name"] = "BYE"
            if m.winner_team_id:
                team = await session.get(Team, m.winner_team_id)
                if team:
                    match_data["winner_name"] = team.name
            elif m.winner_player_id:
                player = await session.get(Player, m.winner_player_id)
                match_data["winner_name"] = player_display_name(player, m.winner_player_id)
            elif m.winner_manual_entry_id:
                entry = await session.get(TournamentManualEntry, m.winner_manual_entry_id)
                if entry:
                    match_data["winner_name"] = entry.display_name
            rounds[r].append(match_data)
        return {
            "tournament": {"id": t.id, "name": t.name, "format": t.format},
            "bracket_type": bracket.bracket_type,
            "rounds": {str(k): v for k, v in sorted(rounds.items())},
        }


@app.get("/api/tournaments/{tournament_id}/bracket/summary")
async def get_bracket_summary(tournament_id: int):
    """Get compact summary: current round, win leader, participant credentials (champion/finalist in other tournaments)."""
    async with async_session_factory() as session:
        t = await session.get(Tournament, tournament_id)
        if not t:
            return {"error": "Tournament not found"}
        result = await session.execute(select(Bracket).where(Bracket.tournament_id == tournament_id))
        bracket = result.scalar_one_or_none()
        if not bracket:
            return {"error": "No bracket generated"}
        matches_result = await session.execute(
            select(BracketMatch)
            .where(BracketMatch.bracket_id == bracket.id)
            .order_by(BracketMatch.round_num, BracketMatch.match_num)
        )
        matches = list(matches_result.scalars().all())
        is_team = t.format != "1v1"

        # Current round: first unplayed round (same logic as build_round_lineup_embed)
        unplayed = [m for m in matches if not (m.winner_team_id or m.winner_player_id or m.winner_manual_entry_id)]
        current_round = None
        if unplayed:
            by_round = {}
            for m in unplayed:
                key = (m.bracket_section or "main", m.round_num)
                if key not in by_round:
                    by_round[key] = []
                by_round[key].append(m)
            section_order = {"main": 0, "winners": 0, "losers": 1, "grand_finals": 2}
            sorted_keys = sorted(by_round.keys(), key=lambda k: (section_order.get(k[0], 0), k[1]))
            section, round_num = sorted_keys[0]
            if section == "grand_finals":
                display_label = "Grand Finals"
            elif section == "winners":
                display_label = f"Primary Round {round_num}"
            elif section == "losers":
                display_round = round_num - 10 if round_num >= 10 else round_num
                display_label = f"Secondary Round {display_round}"
            else:
                display_label = f"Round {round_num}"
            current_round = {"section": section, "round_num": round_num, "display_label": display_label}
        else:
            current_round = {"section": None, "round_num": None, "display_label": "Complete"}

        # Win counts per entity
        win_counts = {}
        entity_names = {}
        for m in matches:
            if m.winner_team_id:
                eid = ("team", m.winner_team_id)
                win_counts[eid] = win_counts.get(eid, 0) + 1
                if eid not in entity_names:
                    team = await session.get(Team, m.winner_team_id)
                    entity_names[eid] = team.name if team else f"Team {m.winner_team_id}"
            elif m.winner_player_id:
                eid = ("player", m.winner_player_id)
                win_counts[eid] = win_counts.get(eid, 0) + 1
                if eid not in entity_names:
                    player = await session.get(Player, m.winner_player_id)
                    entity_names[eid] = player_display_name(player, m.winner_player_id) if player else str(m.winner_player_id)
            elif m.winner_manual_entry_id:
                eid = ("manual", m.winner_manual_entry_id)
                win_counts[eid] = win_counts.get(eid, 0) + 1
                if eid not in entity_names:
                    entry = await session.get(TournamentManualEntry, m.winner_manual_entry_id)
                    entity_names[eid] = entry.display_name if entry else str(m.winner_manual_entry_id)
        win_leader = None
        if win_counts:
            leader_eid = max(win_counts, key=win_counts.get)
            wins = win_counts[leader_eid]
            name = entity_names.get(leader_eid, "Unknown")
            entity_type = "team" if leader_eid[0] == "team" else "player"
            win_leader = {"name": name, "wins": wins, "entity_type": entity_type}

        # Participant credentials: match bracket entities to past champions/finalists
        past_winners = await _fetch_winners_with_ids(session)
        entities_in_bracket = set()
        for m in matches:
            if is_team:
                if m.team1_id:
                    entities_in_bracket.add(("team", m.team1_id))
                if m.team2_id:
                    entities_in_bracket.add(("team", m.team2_id))
            else:
                if m.player1_id:
                    entities_in_bracket.add(("player", m.player1_id))
                if m.player2_id:
                    entities_in_bracket.add(("player", m.player2_id))
                if m.manual_entry1_id:
                    entities_in_bracket.add(("manual", m.manual_entry1_id))
                if m.manual_entry2_id:
                    entities_in_bracket.add(("manual", m.manual_entry2_id))
        participant_credentials = []
        for eid in entities_in_bracket:
            etype, ekey = eid
            display_name = None
            if etype == "team":
                team = await session.get(Team, ekey)
                display_name = team.name if team else None
            elif etype == "player":
                player = await session.get(Player, ekey)
                display_name = player_display_name(player, ekey) if player else None
            else:
                entry = await session.get(TournamentManualEntry, ekey)
                display_name = entry.display_name if entry else None
            if not display_name:
                continue
            past_champion = []
            past_finalist = []
            for w in past_winners:
                if w["tournament_id"] == tournament_id:
                    continue
                if etype == "team":
                    team = await session.get(Team, ekey)
                    if not team:
                        continue
                    player_ids = [r.player_id for r in team.members if r.player_id]
                    if w.get("winner_player_ids") and set(player_ids) == set(w["winner_player_ids"]):
                        past_champion.append(w["tournament_name"])
                    if w.get("finalist_player_ids") and set(player_ids) == set(w["finalist_player_ids"]):
                        past_finalist.append(w["tournament_name"])
                elif etype == "player":
                    if w.get("winner_player_id") == ekey:
                        past_champion.append(w["tournament_name"])
                    if w.get("finalist_player_id") == ekey:
                        past_finalist.append(w["tournament_name"])
                else:
                    if (w.get("winner_display_name") or "").lower() == (display_name or "").lower():
                        past_champion.append(w["tournament_name"])
                    if (w.get("finalist_display_name") or "").lower() == (display_name or "").lower():
                        past_finalist.append(w["tournament_name"])
            if past_champion or past_finalist:
                participant_credentials.append({
                    "entity_id": ekey,
                    "entity_type": etype,
                    "display_name": display_name,
                    "past_champion": past_champion,
                    "past_finalist": past_finalist,
                })

        # Round robin: standings = all participants with win counts, sorted by wins desc
        standings = None
        if bracket.bracket_type == "round_robin":
            standings = []
            for eid in entities_in_bracket:
                etype, ekey = eid
                display_name = None
                if etype == "team":
                    team = await session.get(Team, ekey)
                    display_name = team.name if team else None
                elif etype == "player":
                    player = await session.get(Player, ekey)
                    display_name = player_display_name(player, ekey) if player else None
                else:
                    entry = await session.get(TournamentManualEntry, ekey)
                    display_name = entry.display_name if entry else None
                if display_name is None:
                    display_name = f"Unknown ({ekey})"
                wins = win_counts.get(eid, 0)
                standings.append({
                    "name": display_name,
                    "wins": wins,
                    "entity_type": "team" if etype == "team" else "player",
                    "entity_id": ekey,
                })
            standings.sort(key=lambda x: (-x["wins"], x["name"].lower()))

        return {
            "current_round": current_round,
            "win_leader": win_leader,
            "participant_credentials": participant_credentials,
            "standings": standings,
        }


async def _fetch_winners_with_ids(session: AsyncSession):
    """Fetch past tournament winners and finalists with entity IDs for matching."""
    result = await session.execute(
        select(Tournament)
        .where(or_(Tournament.status == "completed", Tournament.status == "closed", Tournament.archived == True))
        .order_by(Tournament.id.desc())
        .limit(100)
    )
    tournaments = result.scalars().all()
    winners = []
    for t in tournaments:
        bracket_result = await session.execute(
            select(Bracket).where(Bracket.tournament_id == t.id).order_by(Bracket.id.desc()).limit(1)
        )
        bracket = bracket_result.scalar_one_or_none()
        if not bracket:
            continue
        matches_result = await session.execute(
            select(BracketMatch)
            .where(BracketMatch.bracket_id == bracket.id)
            .where(or_(
                BracketMatch.winner_team_id != None,
                BracketMatch.winner_player_id != None,
                BracketMatch.winner_manual_entry_id != None,
            ))
        )
        champ_matches = matches_result.scalars().all()
        champ_match = next((m for m in champ_matches if m.bracket_section == "grand_finals"), None)
        if not champ_match and champ_matches:
            champ_match = max(champ_matches, key=lambda x: (x.round_num, x.match_num))
        if not champ_match:
            continue
        row = {"tournament_id": t.id, "tournament_name": t.name}
        if champ_match.winner_team_id:
            team = await session.get(Team, champ_match.winner_team_id)
            if team:
                row["winner_player_ids"] = [r.player_id for r in team.members if r.player_id]
        elif champ_match.winner_player_id:
            row["winner_player_id"] = champ_match.winner_player_id
        elif champ_match.winner_manual_entry_id:
            entry = await session.get(TournamentManualEntry, champ_match.winner_manual_entry_id)
            row["winner_display_name"] = entry.display_name if entry else None
        if champ_match.winner_team_id:
            fid = champ_match.team2_id if champ_match.winner_team_id == champ_match.team1_id else champ_match.team1_id
            if fid:
                ft = await session.get(Team, fid)
                if ft:
                    row["finalist_player_ids"] = [r.player_id for r in ft.members if r.player_id]
        elif champ_match.winner_player_id:
            row["finalist_player_id"] = champ_match.player2_id if champ_match.winner_player_id == champ_match.player1_id else champ_match.player1_id
            if not row.get("finalist_player_id") and (champ_match.manual_entry1_id or champ_match.manual_entry2_id):
                fe_id = champ_match.manual_entry2_id if champ_match.winner_player_id == champ_match.player1_id else champ_match.manual_entry1_id
                if fe_id:
                    fe = await session.get(TournamentManualEntry, fe_id)
                    row["finalist_display_name"] = fe.display_name if fe else None
        elif champ_match.winner_manual_entry_id:
            fe_id = champ_match.manual_entry1_id if champ_match.winner_manual_entry_id == champ_match.manual_entry2_id else champ_match.manual_entry2_id
            if fe_id:
                fe = await session.get(TournamentManualEntry, fe_id)
                row["finalist_display_name"] = fe.display_name if fe else None
        winners.append(row)
    return winners


@app.get("/api/tournaments/{tournament_id}/bracket/preview")
async def get_bracket_preview(tournament_id: int, bracket_type: str = "single_elim"):
    """Preview bracket structure before generating. Uses current participants/teams."""
    from bot.services.bracket_gen import preview_bracket_structure

    async with async_session_factory() as session:
        t = await session.get(Tournament, tournament_id)
        if not t:
            return {"error": "Tournament not found"}
        is_team = t.format != "1v1"
        names = []
        if is_team:
            result = await session.execute(
                select(Team)
                .where(Team.tournament_id == tournament_id)
                .order_by(Team.id)
                .options(selectinload(Team.manual_members).selectinload(TeamManualMember.manual_entry))
            )
            teams = result.scalars().all()
            names = [team.name for team in teams]
        else:
            result = await session.execute(
                select(TournamentManualEntry)
                .where(
                    TournamentManualEntry.tournament_id == tournament_id,
                    TournamentManualEntry.list_type == "participant",
                )
                .order_by(TournamentManualEntry.sort_order, TournamentManualEntry.id)
            )
            entries = result.scalars().all()
            names = [e.display_name for e in entries]
            # Add Discord registrations for 1v1
            regs_result = await session.execute(
                select(Registration)
                .where(
                    Registration.tournament_id == tournament_id,
                    Registration.team_id.is_(None),
                )
                .options(selectinload(Registration.player))
            )
            for reg in regs_result.scalars().all():
                names.append(player_display_name(reg.player, reg.player_id))
        if len(names) < 2:
            return {"error": "Add at least 2 participants or teams", "rounds": {}}
        preview = preview_bracket_structure(names, bracket_type)
        teams_data = []
        if is_team:
            teams_data = [
                {"id": team.id, "name": team.name, "members": [{"id": m.manual_entry.id, "display_name": m.manual_entry.display_name} for m in sorted(team.manual_members, key=lambda x: x.sort_order)]}
                for team in teams
            ]
        return {
            "tournament": {"id": t.id, "name": t.name, "format": t.format},
            "bracket_type": preview["bracket_type"],
            "rounds": preview["rounds"],
            "teams": teams_data,
            "preview": True,
        }


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Serve built frontend (SPA fallback handled by SPAFallbackMiddleware above)
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
