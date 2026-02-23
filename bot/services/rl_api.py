"""Rocket League API service wrapper with caching."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

import rlapi
from rlapi import Platform, PlaylistKey

if TYPE_CHECKING:
    from rlapi import Player, Playlist

# Playlist name to PlaylistKey mapping
PLAYLIST_MAP = {
    "solo_duel": PlaylistKey.solo_duel,
    "doubles": PlaylistKey.doubles,
    "standard": PlaylistKey.standard,
    "hoops": PlaylistKey.hoops,
    "rumble": PlaylistKey.rumble,
    "dropshot": PlaylistKey.dropshot,
    "snow_day": PlaylistKey.snow_day,
    "tournaments": PlaylistKey.tournaments,
}

CACHE_TTL = 300  # 5 minutes


class RLAPIService:
    """Async RL API service with caching."""

    def __init__(self, client_id: str, client_secret: str):
        self._client = rlapi.Client(client_id=client_id, client_secret=client_secret)
        self._cache: dict[str, tuple[Player, float]] = {}

    async def close(self) -> None:
        """Close the API client."""
        await self._client.close()

    def _cache_key(self, epic_id: str) -> str:
        return f"epic:{epic_id}"

    async def get_player_by_epic_id(self, epic_id: str) -> Player | None:
        """Get player by Epic Account ID. Returns None if not found."""
        key = self._cache_key(epic_id)
        now = time.time()
        if key in self._cache:
            player, ts = self._cache[key]
            if now - ts < CACHE_TTL:
                return player
            del self._cache[key]

        try:
            player = await self._client.get_player_by_id(Platform.epic, epic_id)
            self._cache[key] = (player, now)
            return player
        except rlapi.errors.PlayerNotFound:
            return None
        except rlapi.errors.RLApiException:
            raise

    def get_playlist_mmr(self, player: Player, playlist_name: str) -> tuple[int, str] | None:
        """Get MMR and rank string for a playlist. Returns (skill, rank_str) or None."""
        playlist_key = PLAYLIST_MAP.get(playlist_name.lower())
        if not playlist_key:
            return None
        playlist = player.get_playlist(playlist_key)
        if not playlist:
            return None
        rank_str = str(playlist)  # e.g. "Champion I Div III"
        return (playlist.skill, rank_str)

    def get_playlist(self, player: Player, playlist_name: str) -> Playlist | None:
        """Get playlist data for a player."""
        playlist_key = PLAYLIST_MAP.get(playlist_name.lower())
        if not playlist_key:
            return None
        return player.get_playlist(playlist_key)
