"""Permission checks for slash commands."""
from __future__ import annotations

import discord
from discord import app_commands

import config


def get_moderator_role_ids(guild_id: int) -> set[int]:
    """Get moderator role IDs for guild (from config or future per-guild DB)."""
    return config.MODERATOR_ROLE_IDS


def get_admin_role_ids(guild_id: int) -> set[int]:
    """Get admin role IDs for guild (from config or future per-guild DB)."""
    return config.ADMIN_ROLE_IDS


def mod_or_higher():
    """Check that user has Moderator or Admin role, or is server admin."""

    def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            return False
        if interaction.user.guild_permissions.administrator:
            return True
        mod_roles = get_moderator_role_ids(interaction.guild_id)
        admin_roles = get_admin_role_ids(interaction.guild_id)
        user_role_ids = {r.id for r in interaction.user.roles}
        return bool(user_role_ids & (mod_roles | admin_roles))

    return app_commands.check(predicate)


def admin_only():
    """Check that user has Admin role or is server admin."""

    def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            return False
        if interaction.user.guild_permissions.administrator:
            return True
        admin_roles = get_admin_role_ids(interaction.guild_id)
        user_role_ids = {r.id for r in interaction.user.roles}
        return bool(user_role_ids & admin_roles)

    return app_commands.check(predicate)
