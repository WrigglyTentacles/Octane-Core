"""Resolve guild_id_or_slug to guild_id for guild-scoped routes."""
from __future__ import annotations

from fastapi import HTTPException, Path

from bot.models import GuildConfig
from bot.models.base import async_session_factory
from sqlalchemy import select


async def resolve_guild(
    guild_id_or_slug: str = Path(..., description="Guild ID (numeric) or slug"),
) -> int:
    """Resolve path param to guild_id. Raises 404 if not found."""
    if guild_id_or_slug.isdigit():
        return int(guild_id_or_slug)
    async with async_session_factory() as session:
        result = await session.execute(
            select(GuildConfig).where(GuildConfig.slug == guild_id_or_slug)
        )
        gc = result.scalar_one_or_none()
        if not gc:
            raise HTTPException(404, f"Guild '{guild_id_or_slug}' not found")
        return gc.guild_id
