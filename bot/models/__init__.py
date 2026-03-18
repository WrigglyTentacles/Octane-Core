"""Database models."""
from bot.models.base import Base, init_db
from bot.models.player import Player
from bot.models.tournament import Tournament
from bot.models.registration import Registration
from bot.models.team import Team, TeamManualMember
from bot.models.manual_entry import TournamentManualEntry
from bot.models.signup_message import TournamentSignupMessage
from bot.models.bracket_message import TournamentBracketMessage
from bot.models.bracket import Bracket, BracketMatch  # noqa: F401 - for metadata
from bot.models.user import User  # noqa: F401 - for metadata
from bot.models.site_settings import SiteSettings  # noqa: F401 - for metadata
from bot.models.guild_config import GuildConfig  # noqa: F401 - for metadata
from bot.models.guild_moderator import GuildModerator  # noqa: F401 - for metadata
from bot.models.registration_token import RegistrationToken  # noqa: F401 - for metadata

__all__ = [
    "Base",
    "Player",
    "Tournament",
    "Registration",
    "Team",
    "TeamManualMember",
    "TournamentManualEntry",
    "TournamentSignupMessage",
    "TournamentBracketMessage",
    "Bracket",
    "BracketMatch",
    "User",
    "SiteSettings",
    "GuildConfig",
    "GuildModerator",
    "RegistrationToken",
    "get_async_session",
    "init_db",
]
