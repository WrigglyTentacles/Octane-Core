"""Bracket and match models."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base


class Bracket(Base):
    """Bracket for a tournament."""

    __tablename__ = "brackets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"), nullable=False)
    bracket_type: Mapped[str] = mapped_column(String(32), default="single_elim")  # single_elim, double_elim, swiss

    tournament = relationship("Tournament", back_populates="brackets")
    matches = relationship(
        "BracketMatch", back_populates="bracket", cascade="all, delete-orphan"
    )


class BracketMatch(Base):
    """Single match in a bracket."""

    __tablename__ = "bracket_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bracket_id: Mapped[int] = mapped_column(ForeignKey("brackets.id"), nullable=False)
    round_num: Mapped[int] = mapped_column(Integer, nullable=False)
    match_num: Mapped[int] = mapped_column(Integer, nullable=False)
    team1_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"), nullable=True)
    team2_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"), nullable=True)
    player1_id: Mapped[Optional[int]] = mapped_column(ForeignKey("players.discord_id"), nullable=True)
    player2_id: Mapped[Optional[int]] = mapped_column(ForeignKey("players.discord_id"), nullable=True)
    winner_team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"), nullable=True)
    winner_player_id: Mapped[Optional[int]] = mapped_column(ForeignKey("players.discord_id"), nullable=True)
    parent_match_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bracket_matches.id"), nullable=True)
    parent_match_slot: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    bracket = relationship("Bracket", back_populates="matches")
