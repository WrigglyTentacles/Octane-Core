"""Short-lived tokens for magic link registration (mod/admin self-register)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class RegistrationToken(Base):
    """One-time token for /webregister magic link. Expires in ~15 min."""

    __tablename__ = "registration_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    discord_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    discord_role: Mapped[str] = mapped_column(String(16), nullable=False, default="moderator")  # admin or moderator
