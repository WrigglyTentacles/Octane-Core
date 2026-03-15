"""Guild-aware URL helpers for bot and web."""
from __future__ import annotations

import config


def bracket_url(guild_id: int, path: str = "current") -> str:
    """Build guild-scoped URL for bracket, register, etc."""
    if not config.SITE_URL:
        return ""
    return f"{config.SITE_URL.rstrip('/')}/s/{guild_id}/{path}"
