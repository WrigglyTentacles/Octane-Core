"""Config cog - /config for role IDs (Admin only), /debug_roles for troubleshooting."""
from __future__ import annotations

import discord
from discord import app_commands

from bot.checks import admin_only, _get_member_with_roles, _get_role_ids, _get_role_names
import config


config_group = app_commands.Group(name="config", description="Bot configuration (Admin only)")


@app_commands.command(description="Sync slash commands to this server (Admin only)")
@admin_only()
async def sync(interaction: discord.Interaction) -> None:
    """Manually sync slash commands to the current guild. Use if /debug_roles etc. don't appear."""
    if not interaction.guild_id:
        await interaction.response.send_message("Run this in a server.", ephemeral=True)
        return
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("Could not get guild.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        interaction.client.tree.copy_global_to(guild=guild)
        await interaction.client.tree.sync(guild=guild)
        await interaction.followup.send(f"Commands synced to **{guild.name}**. Try `/debug_roles` now.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Sync failed: {e}", ephemeral=True)


@app_commands.command(description="Show your roles (for debugging permission issues)")
async def debug_roles(interaction: discord.Interaction) -> None:
    """Show what roles the bot sees for you. Use when permission checks fail."""
    if not interaction.guild_id:
        await interaction.response.send_message("Run this in a server.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)  # Avoid "application did not respond" if fetch is slow
    gateway_member = getattr(interaction, "member", None)
    gateway_roles = len(gateway_member.roles) if gateway_member else "N/A"
    raw_role_count = len(getattr(gateway_member, "_roles", [])) if gateway_member else "N/A"
    member = await _get_member_with_roles(interaction)
    if not member:
        await interaction.followup.send(
            "Could not get member data. (Fetch failed - check bot has Server Members Intent)",
            ephemeral=True,
        )
        return
    role_ids_set = _get_role_ids(member)
    role_names_set = _get_role_names(member)
    role_names = sorted(role_names_set)
    role_ids_str = sorted(str(r) for r in role_ids_set)
    expected_mod = f"names: {list(config.MODERATOR_ROLE_NAMES)}, IDs: {list(config.MODERATOR_ROLE_IDS)}, user IDs: {list(config.MODERATOR_USER_IDS)}"
    expected_admin = f"names: {list(config.ADMIN_ROLE_NAMES)}, IDs: {list(config.ADMIN_ROLE_IDS)}, user IDs: {list(config.ADMIN_USER_IDS)}"
    is_admin = member.guild_permissions.administrator
    has_mod = (
        interaction.user.id in (config.MODERATOR_USER_IDS | config.ADMIN_USER_IDS)
        or bool(role_names_set & config.MODERATOR_ROLE_NAMES)
        or bool(role_ids_set & config.MODERATOR_ROLE_IDS)
    )
    has_admin_role = (
        interaction.user.id in config.ADMIN_USER_IDS
        or bool(role_names_set & config.ADMIN_ROLE_NAMES)
        or bool(role_ids_set & config.ADMIN_ROLE_IDS)
    )
    lines = [
        f"**Your user ID:** {interaction.user.id} *(add to MODERATOR_USER_IDS in .env if roles are empty)*",
        f"**Gateway roles (member.roles):** {gateway_roles}",
        f"**Raw _roles count (API payload):** {raw_role_count}",
        f"**Your roles:** {', '.join(role_names) or '(none)'}",
        f"**Role IDs:** {', '.join(role_ids_str) or '(none)'}",
        f"**Server admin?** {is_admin}",
        f"**Expected mod names (from .env):** {expected_mod}",
        f"**Expected admin names/IDs (from .env):** {expected_admin}",
        f"**Has mod role?** {has_mod}",
        f"**Has admin role?** {has_admin_role}",
    ]
    await interaction.followup.send("\n".join(lines), ephemeral=True)


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
