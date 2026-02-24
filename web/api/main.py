"""FastAPI bracket API - serves bracket data and built web UI."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import select
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
