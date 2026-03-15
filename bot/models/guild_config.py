"""Per-guild configuration for multi-server support."""
from __future__ import annotations

from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class GuildConfig(Base):
    """Per-guild settings: Discord channels, slug, theme, name."""

    __tablename__ = "guild_config"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)  # Cached guild name
    discord_signup_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    discord_signup_channel_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    discord_bracket_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    discord_bracket_channel_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Per-guild theme (overrides global SiteSettings when set)
    site_title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    accent_color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    accent_hover: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bg_primary: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bg_secondary: Mapped[str | None] = mapped_column(String(32), nullable=True)
