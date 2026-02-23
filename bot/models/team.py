"""Team model for 2v2/3v3 tournaments."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base


class Team(Base):
    """Team for 2v2, 3v3, 4v4, or custom tournament."""

    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    tournament: Mapped["Tournament"] = relationship("Tournament", back_populates="teams")
    members = relationship(
        "Registration", back_populates="team", cascade="all, delete-orphan"
    )
    manual_members = relationship(
        "TeamManualMember", back_populates="team", cascade="all, delete-orphan"
    )


class TeamManualMember(Base):
    """Manual entry as a team member (for teams created from manual participant list)."""

    __tablename__ = "team_manual_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    manual_entry_id: Mapped[int] = mapped_column(ForeignKey("tournament_manual_entries.id"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    team: Mapped["Team"] = relationship("Team", back_populates="manual_members")
    manual_entry: Mapped["TournamentManualEntry"] = relationship(
        "TournamentManualEntry", back_populates="team_memberships"
    )
