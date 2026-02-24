"""Shared API utilities."""

from bot.models import Player


def player_display_name(player: Player | None, player_id: int) -> str:
    """Return human-readable name for a Discord player. Never show raw user ID."""
    if not player:
        return "Discord User"
    name = (player.display_name or "").strip()
    if name:
        # Only treat as raw ID if it's a long digit string (Discord snowflake)
        if name.isdigit() and len(name) >= 15:
            return "Discord User"
        return name
    return "Discord User"
