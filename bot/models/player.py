"""Player model."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base


class Player(Base):
    """Discord user for tournament registration. Epic linking is optional (future /link with manual approval)."""

    __tablename__ = "players"

    discord_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)  # Discord display name
    epic_username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # Epic display name (when linked)
    epic_id: Mapped[Optional[str]] = mapped_column(String(32), unique=True, nullable=True)  # Epic ID (when linked, manual approval)

    registrations = relationship(
        "Registration", back_populates="player", cascade="all, delete-orphan"
    )
