"""Shared API utilities."""

from bot.models import Player


def player_display_name(player: Player | None, player_id: int) -> str:
    """Return human-readable name for a Discord player. Never show raw user ID."""
    if not player:
        return "Discord User"
    name = (player.display_name or "").strip()
    if name and not name.isdigit():
        return name
    return "Discord User"
