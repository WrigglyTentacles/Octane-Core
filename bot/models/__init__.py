"""Database models."""
from bot.models.base import Base, init_db
from bot.models.player import Player
from bot.models.tournament import Tournament
from bot.models.registration import Registration
from bot.models.team import Team, TeamManualMember
from bot.models.manual_entry import TournamentManualEntry
from bot.models.bracket import Bracket, BracketMatch  # noqa: F401 - for metadata
from bot.models.user import User  # noqa: F401 - for metadata
from bot.models.site_settings import SiteSettings  # noqa: F401 - for metadata

__all__ = [
    "Base",
    "Player",
    "Tournament",
    "Registration",
    "Team",
    "TeamManualMember",
    "TournamentManualEntry",
    "Bracket",
    "BracketMatch",
    "User",
    "SiteSettings",
    "get_async_session",
    "init_db",
]
