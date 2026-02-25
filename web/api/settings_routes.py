"""Site settings API: title, theme colors (public read, admin write)."""
from __future__ import annotations

import httpx

import config
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from bot.models import SiteSettings
from bot.models.base import async_session_factory
from web.auth import require_admin_user, require_moderator_user

router = APIRouter(prefix="/api/settings", tags=["settings"])

DEFAULTS = {
    "site_title": "Octane Bracket Manager",
    "accent_color": "#93E9BE",
    "accent_hover": "#a8f0d0",
    "bg_primary": "#0f0f12",
    "bg_secondary": "#18181c",
}


async def _get_setting(key: str) -> str:
    async with async_session_factory() as session:
        result = await session.execute(select(SiteSettings).where(SiteSettings.key == key))
        row = result.scalar_one_or_none()
        return row.value if row else DEFAULTS.get(key, "")


async def _set_setting(key: str, value: str) -> None:
    async with async_session_factory() as session:
        result = await session.execute(select(SiteSettings).where(SiteSettings.key == key))
        row = result.scalar_one_or_none()
        if row:
            row.value = value
        else:
            session.add(SiteSettings(key=key, value=value))
        await session.commit()


class SettingsResponse(BaseModel):
    site_title: str
    accent_color: str
    accent_hover: str
    bg_primary: str
    bg_secondary: str


class SettingsUpdate(BaseModel):
    site_title: str | None = None
    accent_color: str | None = None
    accent_hover: str | None = None
    bg_primary: str | None = None
    bg_secondary: str | None = None


@router.get("", response_model=SettingsResponse)
async def get_settings():
    """Get site settings (public, for theming)."""
    return SettingsResponse(
        site_title=await _get_setting("site_title"),
        accent_color=await _get_setting("accent_color"),
        accent_hover=await _get_setting("accent_hover"),
        bg_primary=await _get_setting("bg_primary"),
        bg_secondary=await _get_setting("bg_secondary"),
    )


@router.patch("", response_model=SettingsResponse)
async def update_settings(body: SettingsUpdate, admin=Depends(require_admin_user)):
    """Update site settings (admin only)."""
    updates = body.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if value is not None:
            await _set_setting(key, value)
    return SettingsResponse(
        site_title=await _get_setting("site_title"),
        accent_color=await _get_setting("accent_color"),
        accent_hover=await _get_setting("accent_hover"),
        bg_primary=await _get_setting("bg_primary"),
        bg_secondary=await _get_setting("bg_secondary"),
    )


@router.get("/export")
async def export_settings(admin=Depends(require_admin_user)):
    """Export all site settings as JSON backup (admin only)."""
    async with async_session_factory() as session:
        result = await session.execute(select(SiteSettings))
        rows = result.scalars().all()
        backup = {row.key: row.value for row in rows}
    return JSONResponse(content={"settings": backup})


class SettingsImport(BaseModel):
    settings: dict[str, str]


@router.get("/discord")
async def get_discord_settings():
    """Get Discord config for web-triggered signup and bracket posts. Only enabled when INTERNAL_API_SECRET is set."""
    enabled = bool(config.INTERNAL_API_SECRET)
    return {
        "enabled": enabled,
        "discord_guild_id": await _get_setting("discord_guild_id") or "",
        "discord_signup_channel_id": await _get_setting("discord_signup_channel_id") or "",
        "discord_signup_channel_name": await _get_setting("discord_signup_channel_name") or "",
        "discord_bracket_guild_id": await _get_setting("discord_bracket_guild_id") or "",
        "discord_bracket_channel_id": await _get_setting("discord_bracket_channel_id") or "",
        "discord_bracket_channel_name": await _get_setting("discord_bracket_channel_name") or "",
    }


class DiscordBracketUpdate(BaseModel):
    discord_bracket_guild_id: str | None = None
    discord_bracket_channel_id: str | None = None
    discord_bracket_channel_name: str | None = None


@router.patch("/discord")
async def update_discord_bracket(
    body: DiscordBracketUpdate, admin=Depends(require_admin_user)
):
    """Update bracket post channel (admin only)."""
    updates = body.model_dump(exclude_unset=True)
    for key, value in updates.items():
        await _set_setting(key, value or "")
    return await get_discord_settings()


def _bot_request_headers():
    return {"Authorization": f"Bearer {config.INTERNAL_API_SECRET}"}


@router.get("/discord/guilds")
async def get_discord_guilds(user=Depends(require_moderator_user)):
    """List guilds the bot is in (for channel picker). Proxies to bot."""
    if not config.INTERNAL_API_SECRET or not config.BOT_INTERNAL_URL:
        raise HTTPException(503, "Discord integration not configured")
    url = f"{config.BOT_INTERNAL_URL.rstrip('/')}/internal/discord/guilds"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers=_bot_request_headers())
    except httpx.ConnectError as e:
        raise HTTPException(
            503, "Could not reach the Discord bot. Ensure it is running."
        ) from e
    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text)
    return r.json()


@router.get("/discord/guilds/{guild_id}/channels")
async def get_discord_channels(
    guild_id: str, user=Depends(require_moderator_user)
):
    """List text channels in a guild (for channel picker). Proxies to bot."""
    if not config.INTERNAL_API_SECRET or not config.BOT_INTERNAL_URL:
        raise HTTPException(503, "Discord integration not configured")
    url = f"{config.BOT_INTERNAL_URL.rstrip('/')}/internal/discord/guilds/{guild_id}/channels"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers=_bot_request_headers())
    except httpx.ConnectError as e:
        raise HTTPException(
            503, "Could not reach the Discord bot. Ensure it is running."
        ) from e
    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text)
    return r.json()


@router.post("/import")
async def import_settings(body: SettingsImport, admin=Depends(require_admin_user)):
    """Restore site settings from a JSON backup (admin only). Overwrites existing keys."""
    async with async_session_factory() as session:
        result = await session.execute(select(SiteSettings))
        rows = result.scalars().all()
        existing = {row.key: row for row in rows}
        for key, value in body.settings.items():
            if key in existing:
                existing[key].value = value
            else:
                session.add(SiteSettings(key=key, value=value))
        await session.commit()
    return {"ok": True, "restored": len(body.settings)}
