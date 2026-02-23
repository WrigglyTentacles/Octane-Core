"""FastAPI bracket API - serves bracket data for web UI."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import Bracket, BracketMatch, Player, Team, Tournament
from bot.models.base import async_session_factory, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Octane-Core Bracket API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        rounds = {}
        for m in matches:
            r = m.round_num
            if r not in rounds:
                rounds[r] = []
            match_data = {
                "id": m.id,
                "match_num": m.match_num,
                "team1_id": m.team1_id,
                "team2_id": m.team2_id,
                "player1_id": m.player1_id,
                "player2_id": m.player2_id,
                "winner_team_id": m.winner_team_id,
                "winner_player_id": m.winner_player_id,
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
                if player:
                    match_data["player1_name"] = player.display_name or str(player.discord_id)
            if not is_team and m.player2_id:
                player = await session.get(Player, m.player2_id)
                if player:
                    match_data["player2_name"] = player.display_name or str(player.discord_id)
            rounds[r].append(match_data)
        return {
            "tournament": {"id": t.id, "name": t.name, "format": t.format},
            "bracket_type": bracket.bracket_type,
            "rounds": {str(k): v for k, v in sorted(rounds.items())},
        }


@app.get("/api/health")
async def health():
    return {"status": "ok"}
