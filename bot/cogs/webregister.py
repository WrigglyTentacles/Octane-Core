"""Webregister cog - /webregister for mod/admin to get magic link for web dashboard."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands

import config
from bot.checks import mod_or_higher
from sqlalchemy import select

from bot.models import GuildConfig, RegistrationToken
from bot.models.base import get_async_session
from web.api.web_urls import bracket_url


@app_commands.command(description="Get your web dashboard link (Moderator or Admin only)")
@mod_or_higher()
async def webregister(interaction: discord.Interaction) -> None:
    """Generate magic link and DM it to the user. Only mod/admin can use."""
    if not interaction.guild_id or not interaction.user:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return

    guild_id = interaction.guild_id
    user_id = interaction.user.id

    if not config.SITE_URL:
        await interaction.response.send_message(
            "Web dashboard is not configured (SITE_URL missing).",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

    async for session in get_async_session():
        session.add(
            RegistrationToken(
                token=token,
                discord_user_id=user_id,
                guild_id=guild_id,
                expires_at=expires_at,
            )
        )
        # Ensure GuildConfig exists for this guild
        result = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild_id))
        if not result.scalar_one_or_none():
            guild_name = interaction.guild.name if interaction.guild else None
            session.add(GuildConfig(guild_id=guild_id, name=guild_name))
        await session.commit()
        break

    url = f"{bracket_url(guild_id, 'register')}?token={token}"

    try:
        await interaction.user.send(
            f"**Octane Bracket Manager** — Click to set up your web account:\n{url}\n\n"
            f"You'll choose a username and password (linked to your Discord). Link expires in 15 minutes."
        )
        await interaction.followup.send(
            "Check your DMs for the registration link!",
            ephemeral=True,
        )
    except discord.Forbidden:
        await interaction.followup.send(
            "I can't DM you. Enable DMs from server members and try again.",
            ephemeral=True,
        )
