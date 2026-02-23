"""Manual participant and standby entries for tournaments."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base


class TournamentManualEntry(Base):
    """Manually editable participant or standby entry for a tournament."""

    __tablename__ = "tournament_manual_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    epic_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    list_type: Mapped[str] = mapped_column(String(16), nullable=False)  # participant | standby
    original_list_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # never changes; for standby recognition
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    tournament: Mapped["Tournament"] = relationship("Tournament", back_populates="manual_entries")
    team_memberships = relationship(
        "TeamManualMember", back_populates="manual_entry", cascade="all, delete-orphan"
    )
