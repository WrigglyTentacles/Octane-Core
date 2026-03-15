"""Web user model for site authentication."""
from __future__ import annotations

from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base


class User(Base):
    """Web user with role-based access."""

    __tablename__ = "web_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")  # user, moderator, admin
    discord_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True, index=True)

    guild_moderators = relationship("GuildModerator", back_populates="user", cascade="all, delete-orphan")
