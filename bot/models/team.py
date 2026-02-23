"""Team model for 2v2/3v3 tournaments."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base


class Team(Base):
    """Team for 2v2 or 3v3 tournament."""

    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    tournament: Mapped["Tournament"] = relationship("Tournament", back_populates="teams")
    members = relationship(
        "Registration", back_populates="team", cascade="all, delete-orphan"
    )
