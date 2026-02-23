"""Configuration for Octane-Core bot."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Discord
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

# Rocket League API
RLAPI_CLIENT_ID = os.getenv("RLAPI_CLIENT_ID", "")
RLAPI_CLIENT_SECRET = os.getenv("RLAPI_CLIENT_SECRET", "")

# Database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite+aiosqlite:///{Path(__file__).parent / 'octane.db'}",
)

# Role IDs (comma-separated)
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


MODERATOR_ROLE_IDS = _parse_role_ids(os.getenv("MODERATOR_ROLE_IDS", ""))
ADMIN_ROLE_IDS = _parse_role_ids(os.getenv("ADMIN_ROLE_IDS", ""))

# Web auth (JWT secret, initial admin bootstrap)
JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production-use-long-random-string")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 7
INITIAL_ADMIN_USERNAME = os.getenv("INITIAL_ADMIN_USERNAME", "admin")
INITIAL_ADMIN_PASSWORD = os.getenv("INITIAL_ADMIN_PASSWORD", "")  # Set to bootstrap first admin
