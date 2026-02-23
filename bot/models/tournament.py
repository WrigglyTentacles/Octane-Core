"""Tournament model."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base


# Supported formats: 1v1, 2v2, 3v3, 4v4, or custom (e.g. "custom: 4v4")
def parse_format_players(format_str: str) -> int:
    """Return number of players per side (1 for 1v1, 2 for 2v2, etc.)."""
    import re
    m = re.search(r"(\d+)v\d+", format_str, re.I)
    return int(m.group(1)) if m else 2


# rlapi PlaylistKey values
MMR_PLAYLISTS = {
    "solo_duel": 10,
    "doubles": 11,
    "standard": 13,
    "hoops": 27,
    "rumble": 28,
    "dropshot": 29,
    "snow_day": 30,
    "tournaments": 34,
}


class Tournament(Base):
    """Tournament with format and MMR playlist."""

    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False)  # 1v1, 2v2, 3v3
    mmr_playlist: Mapped[str] = mapped_column(String(32), nullable=False)  # solo_duel, doubles, etc.
    registration_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open")  # open, closed, in_progress, completed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    registrations = relationship(
        "Registration", back_populates="tournament", cascade="all, delete-orphan"
    )
    teams = relationship(
        "Team", back_populates="tournament", cascade="all, delete-orphan"
    )
    brackets = relationship(
        "Bracket", back_populates="tournament", cascade="all, delete-orphan"
    )
    manual_entries = relationship(
        "TournamentManualEntry", back_populates="tournament", cascade="all, delete-orphan"
    )
    signup_messages = relationship(
        "TournamentSignupMessage", back_populates="tournament", cascade="all, delete-orphan"
    )
