"""Config cog - /config for role IDs (Admin only), /debug_roles for troubleshooting."""
from __future__ import annotations

import logging

import discord
from discord import app_commands

from bot.checks import admin_only, _get_member_with_roles, _get_role_ids, _get_role_names, _resolve_role_names
import config

logger = logging.getLogger("octane.config")


config_group = app_commands.Group(name="config", description="Bot configuration (Admin only)")

# Permissions: Manage Server, Manage Roles, Read Messages, Send Messages, Embed Links, Attach Files, Read Message History, Add Reactions
INVITE_PERMISSIONS = "277025508360"


@app_commands.command(description="Get the bot invite link (adds the bot to your server)")
async def invite(interaction: discord.Interaction) -> None:
    """Get the correct invite URL. The **bot** scope is required — without it, the app installs but no bot appears."""
    app_id = interaction.client.application_id
    if not app_id:
        await interaction.response.send_message("Bot not ready yet. Try again in a moment.", ephemeral=True)
        return
    url = f"https://discord.com/api/oauth2/authorize?client_id={app_id}&permissions={INVITE_PERMISSIONS}&scope=bot%20applications.commands"
    await interaction.response.send_message(
        f"**Add Octane-Core to your server:**\n{url}\n\n"
        "⚠️ The **bot** scope is required. If you used a different link and the bot didn't appear, use this one and re-add.",
        ephemeral=True,
    )


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
            "Could not get member data. Enable **Server Members Intent** in the Discord Developer Portal: "
            "Your App → Bot → Privileged Gateway Intents → Server Members Intent. Then reinvite the bot.",
            ephemeral=True,
        )
        return
    role_ids_set = _get_role_ids(member)
    role_names_set = _get_role_names(member)
    # Resolve role IDs to names - use guild from bot's cache (member.guild can be stale/404)
    guild_for_roles = (
        interaction.client.get_guild(interaction.guild_id)
        if interaction.guild_id
        else (member.guild or interaction.guild)
    )
    if not role_names_set and role_ids_set and guild_for_roles:
        try:
            logger.info("Resolving %d role IDs for guild %s (%s)", len(role_ids_set), guild_for_roles.id, guild_for_roles.name)
            role_names_set = await _resolve_role_names(
                role_ids_set, guild_for_roles, interaction.client
            )
        except Exception as e:
            logger.exception("Role resolution failed for guild %s: %s", guild_for_roles.id, e)
    role_names = sorted(role_names_set)
    role_ids_str = sorted(str(r) for r in role_ids_set)
    expected_mod = f"names: {list(config.MODERATOR_ROLE_NAMES)}, IDs: {list(config.MODERATOR_ROLE_IDS)}, user IDs: {list(config.MODERATOR_USER_IDS)}"
    expected_admin = f"names: {list(config.ADMIN_ROLE_NAMES)}, IDs: {list(config.ADMIN_ROLE_IDS)}, user IDs: {list(config.ADMIN_USER_IDS)}"
    is_admin = member.guild_permissions.administrator
    is_owner = interaction.guild and interaction.guild.owner_id == interaction.user.id
    has_mod = (
        is_owner
        or member.guild_permissions.manage_guild
        or interaction.user.id in (config.MODERATOR_USER_IDS | config.ADMIN_USER_IDS)
        or bool(role_names_set & config.MODERATOR_ROLE_NAMES)
        or bool(role_ids_set & config.MODERATOR_ROLE_IDS)
    )
    has_admin_role = (
        interaction.user.id in config.ADMIN_USER_IDS
        or bool(role_names_set & config.ADMIN_ROLE_NAMES)
        or bool(role_ids_set & config.ADMIN_ROLE_IDS)
    )
    has_manage_guild = member.guild_permissions.manage_guild
    lines = [
        f"**Your user ID:** {interaction.user.id} *(add to MODERATOR_USER_IDS in .env if roles are empty)*",
        f"**Server owner?** {is_owner} *(always has mod access)*",
        f"**Gateway roles (member.roles):** {gateway_roles}",
        f"**Raw _roles count (API payload):** {raw_role_count}",
        f"**Your roles:** {', '.join(role_names) or '(none)'}",
        f"**Role IDs:** {', '.join(role_ids_str) or '(none)'}",
        f"**Server admin?** {is_admin}",
        f"**Manage Server?** {has_manage_guild} *(grants mod access without .env)*",
        f"**Expected mod names (from .env):** {expected_mod}",
        f"**Expected admin names/IDs (from .env):** {expected_admin}",
        f"**Has mod role?** {has_mod}",
        f"**Has admin role?** {has_admin_role}",
    ]
    if not has_mod and not is_admin and not is_owner:
        fix = ["A role with **Manage Server** grants mod access (no .env needed)."]
        if not role_names_set and role_ids_set:
            fix.append("Or add your user ID to MODERATOR_USER_IDS in .env.")
            if interaction.client.guilds:
                bot_in = ", ".join(g.name or str(g.id) for g in interaction.client.guilds[:3])
                fix.append(f"Run /debug_roles in the server where you added the bot ({bot_in}).")
        if config.MODERATOR_ROLE_NAMES and "comissioner" in str(config.MODERATOR_ROLE_NAMES).lower():
            fix.append('Check spelling: "Tournament Commissioner" has two m\'s.')
        if role_ids_set and config.MODERATOR_ROLE_IDS and not (role_ids_set & config.MODERATOR_ROLE_IDS):
            fix.append("Or add one of your role IDs to MODERATOR_ROLE_IDS in .env.")
        lines.append("\n**Fix:** " + " ".join(fix))
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
