"""Registration model - player registered for tournament."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base


class Registration(Base):
    """Player registration for a tournament."""

    __tablename__ = "registrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"), nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.discord_id"), nullable=False)
    team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"), nullable=True)

    tournament: Mapped["Tournament"] = relationship("Tournament", back_populates="registrations")
    player: Mapped["Player"] = relationship("Player", back_populates="registrations")
    team: Mapped[Optional["Team"]] = relationship("Team", back_populates="members")
