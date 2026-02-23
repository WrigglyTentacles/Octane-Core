"""Config cog - /config for role IDs (Admin only)."""
from __future__ import annotations

import discord
from discord import app_commands

from bot.checks import admin_only


config_group = app_commands.Group(name="config", description="Bot configuration (Admin only)")


@config_group.command(name="roles", description="Set moderator/admin role IDs (Admin only)")
@app_commands.describe(
    moderator_roles="Comma-separated role IDs for Moderators",
    admin_roles="Comma-separated role IDs for Admins",
)
@admin_only()
async def roles(
    interaction: discord.Interaction,
    moderator_roles: str = "",
    admin_roles: str = "",
) -> None:
    """Set role IDs. Stored in env - for per-guild config, use a database in future."""
    await interaction.response.send_message(
        "Role configuration is currently set via environment variables (MODERATOR_ROLE_IDS, ADMIN_ROLE_IDS). "
        "Per-guild config will be added in a future update.",
        ephemeral=True,
    )
