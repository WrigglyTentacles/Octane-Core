"""Per-guild configuration for multi-server support."""
from __future__ import annotations

from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class GuildConfig(Base):
    """Per-guild settings: Discord channels, slug, theme."""

    __tablename__ = "guild_config"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)  # Cached guild name
    discord_signup_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    discord_bracket_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
