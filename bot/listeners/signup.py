"""Reaction-based tournament signup listener."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select

import discord

logger = logging.getLogger("octane.signup")
from discord.ext import commands

from bot.models import Player, Registration, Tournament, TournamentSignupMessage
from bot.models.base import get_async_session

SIGNUP_EMOJI = "📝"


def _emoji_matches(event_emoji: discord.PartialEmoji | str, stored: str) -> bool:
    """Check if reaction emoji matches the signup emoji."""
    if isinstance(event_emoji, str):
        return event_emoji == stored
    return event_emoji.name == stored


async def _handle_reaction_add(payload: discord.RawReactionActionEvent, bot: commands.Bot) -> None:
    """Handle reaction add - register user for tournament."""
    if payload.user_id == bot.user.id:
        return
    if not payload.guild_id:
        return

    emoji_str = str(payload.emoji) if payload.emoji.is_unicode_emoji() else payload.emoji.name
    if not emoji_str:
        return

    async for session in get_async_session():
        result = await session.execute(
            select(TournamentSignupMessage).where(
                TournamentSignupMessage.message_id == payload.message_id,
                TournamentSignupMessage.guild_id == payload.guild_id,
            )
        )
        signup_msg = result.scalar_one_or_none()
        if not signup_msg or not _emoji_matches(payload.emoji, signup_msg.signup_emoji):
            return

        # Check tournament exists and is open
        t = await session.get(Tournament, signup_msg.tournament_id)
        if not t or t.status != "open":
            if t and t.status != "open":
                logger.info("Reaction signup ignored: tournament %s is %s", t.name, t.status)
            return
        if t.registration_deadline:
            deadline = t.registration_deadline
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > deadline:
                try:
                    channel = bot.get_channel(payload.channel_id) or await bot.fetch_channel(payload.channel_id)
                    user = bot.get_user(payload.user_id) or await bot.fetch_user(payload.user_id)
                    if channel and user:
                        ts = int(deadline.timestamp())
                        await channel.send(
                            f"{user.mention} Registration closed. Deadline was <t:{ts}:F>.",
                            delete_after=10,
                        )
                except Exception:
                    pass
                return

        # Get or create Player (open by default — no /register required)
        player_result = await session.execute(select(Player).where(Player.discord_id == payload.user_id))
        player = player_result.scalar_one_or_none()
        user = bot.get_user(payload.user_id) or await bot.fetch_user(payload.user_id)
        display_name = user.display_name if user else str(payload.user_id)
        if not player:
            player = Player(discord_id=payload.user_id, display_name=display_name)
            session.add(player)
            await session.flush()  # Get player in session before adding Registration
        else:
            # Refresh display_name when user reacts (may have changed)
            player.display_name = display_name

        # Check if already registered
        existing = await session.execute(
            select(Registration).where(
                Registration.tournament_id == signup_msg.tournament_id,
                Registration.player_id == payload.user_id,
            )
        )
        if existing.scalar_one_or_none():
            return  # Already registered, nothing to do

        session.add(Registration(tournament_id=signup_msg.tournament_id, player_id=payload.user_id))
        await session.commit()

        try:
            channel = bot.get_channel(payload.channel_id) or await bot.fetch_channel(payload.channel_id)
            user = bot.get_user(payload.user_id) or await bot.fetch_user(payload.user_id)
            if channel and user:
                await channel.send(f"✅ {user.mention} signed up for **{t.name}**!", delete_after=5)
        except Exception:
            pass
        return


async def _handle_reaction_remove(payload: discord.RawReactionActionEvent, bot: commands.Bot) -> None:
    """Handle reaction remove - unassign from team (stays in tournament) or fully leave if not on team."""
    if not payload.guild_id:
        return

    emoji_str = str(payload.emoji) if payload.emoji.is_unicode_emoji() else payload.emoji.name
    if not emoji_str:
        return

    async for session in get_async_session():
        result = await session.execute(
            select(TournamentSignupMessage).where(
                TournamentSignupMessage.message_id == payload.message_id,
                TournamentSignupMessage.guild_id == payload.guild_id,
            )
        )
        signup_msg = result.scalar_one_or_none()
        if not signup_msg or not _emoji_matches(payload.emoji, signup_msg.signup_emoji):
            return

        t = await session.get(Tournament, signup_msg.tournament_id)
        if not t:
            return

        reg_result = await session.execute(
            select(Registration).where(
                Registration.tournament_id == signup_msg.tournament_id,
                Registration.player_id == payload.user_id,
            )
        )
        reg = reg_result.scalar_one_or_none()
        if not reg:
            return

        if reg.team_id:
            # On a team: unassign to unassigned section (name stays in tournament)
            reg.team_id = None
            msg = "moved to unassigned"
        else:
            # Not on team: fully leave
            await session.execute(
                delete(Registration).where(
                    Registration.tournament_id == signup_msg.tournament_id,
                    Registration.player_id == payload.user_id,
                )
            )
            msg = "dropped from"
        await session.commit()

        try:
            channel = bot.get_channel(payload.channel_id) or await bot.fetch_channel(payload.channel_id)
            user = bot.get_user(payload.user_id) or await bot.fetch_user(payload.user_id)
            if channel and user:
                await channel.send(f"👋 {user.mention} {msg} **{t.name}**.", delete_after=5)
        except Exception:
            pass
        return


def setup(bot: commands.Bot) -> None:
    """Register signup reaction listeners."""

    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
        await _handle_reaction_add(payload, bot)

    async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent) -> None:
        await _handle_reaction_remove(payload, bot)

    bot.add_listener(on_raw_reaction_add, "on_raw_reaction_add")
    bot.add_listener(on_raw_reaction_remove, "on_raw_reaction_remove")
