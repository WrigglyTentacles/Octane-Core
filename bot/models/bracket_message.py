"""Tournament bracket messages (teams, round, results) - for cleanup when posting results."""
from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class TournamentBracketMessage(Base):
    """Discord message posted for a tournament (teams, round, results). Tracked for cleanup."""

    __tablename__ = "tournament_bracket_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"), nullable=False)
    message_type: Mapped[str] = mapped_column(String(16), nullable=False)  # teams, round, results
