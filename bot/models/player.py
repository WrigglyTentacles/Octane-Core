"""Player model."""
from __future__ import annotations

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base


class Player(Base):
    """Discord user linked to Epic ID."""

    __tablename__ = "players"

    discord_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    epic_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=True)

    registrations = relationship(
        "Registration", back_populates="player", cascade="all, delete-orphan"
    )
