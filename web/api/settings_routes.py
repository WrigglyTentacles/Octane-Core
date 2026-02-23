"""Site settings API: title, theme colors (public read, admin write)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from bot.models import SiteSettings
from bot.models.base import async_session_factory
from web.auth import require_admin_user

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
