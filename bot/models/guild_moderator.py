"""Links web users to guilds they can moderate."""
from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base


class GuildModerator(Base):
    """User has moderator/admin access to a specific guild."""

    __tablename__ = "guild_moderators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("web_users.id", ondelete="CASCADE"), nullable=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="moderator")  # moderator, admin

    __table_args__ = (UniqueConstraint("user_id", "guild_id", name="uq_guild_moderator_user_guild"),)

    user = relationship("User", back_populates="guild_moderators")
