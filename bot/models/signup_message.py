"""Tournament signup message - maps a Discord message to a tournament for reaction-based signup."""
from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base


class TournamentSignupMessage(Base):
    """Discord message with reaction for tournament signup. React to sign up, remove to drop."""

    __tablename__ = "tournament_signup_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"), nullable=False)
    signup_emoji: Mapped[str] = mapped_column(String(32), default="📝")  # Emoji to react with

    tournament: Mapped["Tournament"] = relationship("Tournament", back_populates="signup_messages")
