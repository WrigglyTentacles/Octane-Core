"""Configuration for Octane-Core bot."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Discord
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

# Web -> Bot internal API (for triggering signup from web UI)
BOT_INTERNAL_URL = os.getenv("BOT_INTERNAL_URL", "http://bot:8001")  # URL the web API uses to reach the bot
INTERNAL_API_SECRET = os.getenv("INTERNAL_API_SECRET", "")  # Shared secret for web->bot requests

# Rocket League API
RLAPI_CLIENT_ID = os.getenv("RLAPI_CLIENT_ID", "")
RLAPI_CLIENT_SECRET = os.getenv("RLAPI_CLIENT_SECRET", "")

# Database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite+aiosqlite:///{Path(__file__).parent / 'octane.db'}",
)

# Role IDs or names (comma-separated). Names are case-insensitive.
def _parse_role_ids(value: str) -> set[int]:
    if not value:
        return set()
    result = set()
    for x in value.split(","):
        try:
            result.add(int(x.strip()))
        except ValueError:
            continue
    return result


def _parse_role_names(value: str) -> set[str]:
    if not value:
        return set()
    return {x.strip().lower() for x in value.split(",") if x.strip()}


MODERATOR_ROLE_IDS = _parse_role_ids(os.getenv("MODERATOR_ROLE_IDS", ""))
MODERATOR_ROLE_NAMES = _parse_role_names(os.getenv("MODERATOR_ROLE_NAMES", ""))
ADMIN_ROLE_IDS = _parse_role_ids(os.getenv("ADMIN_ROLE_IDS", ""))
ADMIN_ROLE_NAMES = _parse_role_names(os.getenv("ADMIN_ROLE_NAMES", ""))

# User IDs that bypass role checks (when Members Intent fails to return roles)
MODERATOR_USER_IDS = _parse_role_ids(os.getenv("MODERATOR_USER_IDS", ""))
ADMIN_USER_IDS = _parse_role_ids(os.getenv("ADMIN_USER_IDS", ""))

# Web auth (JWT secret, initial admin bootstrap)
JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production-use-long-random-string")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 7
INITIAL_ADMIN_USERNAME = os.getenv("INITIAL_ADMIN_USERNAME", "admin")
INITIAL_ADMIN_PASSWORD = os.getenv("INITIAL_ADMIN_PASSWORD", "")  # Set to bootstrap first admin
