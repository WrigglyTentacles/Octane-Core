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
