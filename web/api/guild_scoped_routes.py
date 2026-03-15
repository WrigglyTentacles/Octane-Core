"""Guild-scoped API routes: /api/s/{guild_id_or_slug}/..."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import (
    GuildConfig,
    RegistrationToken,
    Tournament,
    User,
)
from bot.models.base import async_session_factory
from web.auth import (
    claim_guild_moderator,
    create_access_token,
    require_moderator_for_guild,
    require_user,
)
from web.api.guild_resolver import resolve_guild

router = APIRouter(tags=["guild-scoped"])


def _parse_deadline(s: Optional[str]):
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


# --- Tournaments (guild-scoped) ---


@router.get("/tournaments")
async def list_tournaments(
    guild_id: int = Depends(resolve_guild),
    include_archived: bool = False,
):
    """List tournaments for this guild (or web-only guild_id=0)."""
    async with async_session_factory() as session:
        q = (
            select(Tournament)
            .where(
                or_(Tournament.guild_id == guild_id, Tournament.guild_id == 0)
            )
            .order_by(Tournament.id.desc())
            .limit(50)
        )
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


@router.get("/tournaments/current")
async def get_current_tournament(
    guild_id: int = Depends(resolve_guild),
    tournament_id: Optional[int] = None,
):
    """Get open tournaments for this guild."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(Tournament)
            .where(
                or_(Tournament.guild_id == guild_id, Tournament.guild_id == 0),
                Tournament.archived == False,  # noqa: E712
                Tournament.status.in_(["open", "in_progress"]),
            )
            .order_by(Tournament.id.desc())
            .limit(50)
        )
        tournaments = result.scalars().all()
        if not tournaments:
            return {"tournaments": [], "default_id": None}
        default_id = tournaments[0].id
        list_data = [
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
        if tournament_id and any(t.id == tournament_id for t in tournaments):
            return {"tournaments": list_data, "default_id": default_id, "selected_id": tournament_id}
        return {"tournaments": list_data, "default_id": default_id}


# --- Winners (guild-scoped) ---


@router.get("/winners")
async def list_winners(guild_id: int = Depends(resolve_guild)):
    """List tournament champions for this guild."""
    from web.api.routes import _fetch_winners_with_ids

    async with async_session_factory() as session:
        result = await session.execute(
            select(Tournament)
            .where(
                or_(Tournament.guild_id == guild_id, Tournament.guild_id == 0),
                or_(
                    Tournament.status == "completed",
                    Tournament.status == "closed",
                    Tournament.archived == True,
                ),
            )
            .order_by(Tournament.id.desc())
            .limit(100)
        )
        tournaments = result.scalars().all()
        tournament_ids = {t.id for t in tournaments}
        winners_raw = await _fetch_winners_with_ids(session)
        winners = [w for w in winners_raw if w["tournament_id"] in tournament_ids]
        return winners


# --- Registration (magic link) ---


class RegisterRequest(BaseModel):
    token: str


@router.post("/register")
async def register_with_token(
    guild_id: int = Depends(resolve_guild),
    body: Optional[RegisterRequest] = None,
    token_query: Optional[str] = None,
):
    """Exchange magic link token for JWT. Token from body or query param."""
    token = None
    if body and body.token:
        token = body.token
    elif token_query:
        token = token_query
    if not token:
        raise HTTPException(400, "token required (body or query)")

    async with async_session_factory() as session:
        result = await session.execute(
            select(RegistrationToken).where(
                RegistrationToken.token == token,
                RegistrationToken.guild_id == guild_id,
            )
        )
        rt = result.scalar_one_or_none()
        if not rt:
            raise HTTPException(400, "Invalid or expired token")
        if rt.expires_at < datetime.now(timezone.utc):
            await session.delete(rt)
            await session.commit()
            raise HTTPException(400, "Token expired")
        discord_user_id = rt.discord_user_id
        await session.delete(rt)
        await session.commit()

    user = await claim_guild_moderator(discord_user_id, guild_id)
    jwt_token = create_access_token(user.username, user.role)
    return {
        "access_token": jwt_token,
        "token_type": "bearer",
        "username": user.username,
        "role": user.role,
    }


@router.get("/register")
async def register_with_token_get(
    guild_id: int = Depends(resolve_guild),
    token: Optional[str] = None,
):
    """Exchange magic link token for JWT (GET for redirect from magic link)."""
    if not token:
        raise HTTPException(400, "token required (query param)")
    # Reuse POST logic
    async with async_session_factory() as session:
        result = await session.execute(
            select(RegistrationToken).where(
                RegistrationToken.token == token,
                RegistrationToken.guild_id == guild_id,
            )
        )
        rt = result.scalar_one_or_none()
        if not rt:
            raise HTTPException(400, "Invalid or expired token")
        if rt.expires_at < datetime.now(timezone.utc):
            await session.delete(rt)
            await session.commit()
            raise HTTPException(400, "Token expired")
        discord_user_id = rt.discord_user_id
        await session.delete(rt)
        await session.commit()

    user = await claim_guild_moderator(discord_user_id, guild_id)
    jwt_token = create_access_token(user.username, user.role)
    return {
        "access_token": jwt_token,
        "token_type": "bearer",
        "username": user.username,
        "role": user.role,
    }


# --- Guild info (for frontend) ---


@router.get("/info")
async def get_guild_info(guild_id: int = Depends(resolve_guild)):
    """Get guild display info (name, slug)."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(GuildConfig).where(GuildConfig.guild_id == guild_id)
        )
        gc = result.scalar_one_or_none()
        return {
            "guild_id": guild_id,
            "name": gc.name if gc else str(guild_id),
            "slug": gc.slug if gc else None,
        }
