"""Permission checks for slash commands."""
from __future__ import annotations

import discord
from discord import app_commands

import config


def _get_member(interaction: discord.Interaction) -> discord.Member | None:
    """Get Member from interaction."""
    if not interaction.guild:
        return None
    member = getattr(interaction, "member", None) or (
        interaction.user if isinstance(interaction.user, discord.Member) else None
    )
    return member


def _get_role_ids(member: discord.Member) -> set[int]:
    """Get member's role IDs. Uses raw _roles to bypass guild.get_role() returning None.
    discord.py's member.roles filters through guild.get_role(); if the guild role cache
    is incomplete, roles can appear empty even when _roles has IDs from the API payload."""
    ids = set()
    raw = getattr(member, "_roles", None)
    if raw is not None:
        ids.update(int(r) for r in raw)
    for r in member.roles:
        ids.add(r.id)
    return ids


def _get_role_names(member: discord.Member) -> set[str]:
    """Get member's role names (lowercase). Uses guild.roles for IDs in _roles when
    member.roles is incomplete."""
    names = {r.name.lower() for r in member.roles}
    raw = getattr(member, "_roles", None)
    guild = member.guild
    if raw is not None and guild is not None:
        for role_id in raw:
            rid = int(role_id)
            role = guild.get_role(rid)
            if role is not None and role.name.lower() not in names:
                names.add(role.name.lower())
    return names


async def _get_member_with_roles(interaction: discord.Interaction) -> discord.Member | None:
    """Get Member with roles. Fetches via REST API if we have no role IDs."""
    member = _get_member(interaction)
    if not member or not interaction.guild:
        return None
    role_ids = _get_role_ids(member)
    if len(role_ids) <= 1:  # Only @everyone or empty
        try:
            member = await interaction.guild.fetch_member(interaction.user.id)
        except discord.NotFound:
            return None
    return member


def _user_has_mod_or_higher(interaction: discord.Interaction) -> bool:
    """True if user is server admin, or has moderator/admin role (by ID or name)."""
    member = _get_member(interaction)
    if not member:
        return False
    if member.guild_permissions.administrator:
        return True
    role_ids = _get_role_ids(member)
    role_names = _get_role_names(member)
    mod_by_id = bool(role_ids & (config.MODERATOR_ROLE_IDS | config.ADMIN_ROLE_IDS))
    mod_by_name = bool(role_names & (config.MODERATOR_ROLE_NAMES | config.ADMIN_ROLE_NAMES))
    return mod_by_id or mod_by_name


def _user_has_admin(interaction: discord.Interaction) -> bool:
    """True if user is server admin, or has admin role (by ID or name)."""
    member = _get_member(interaction)
    if not member:
        return False
    if member.guild_permissions.administrator:
        return True
    role_ids = _get_role_ids(member)
    role_names = _get_role_names(member)
    return bool(role_ids & config.ADMIN_ROLE_IDS) or bool(role_names & config.ADMIN_ROLE_NAMES)


def mod_or_higher():
    """Check that user has Moderator or Admin role, or is server admin."""

    async def predicate(interaction: discord.Interaction) -> bool:
        member = await _get_member_with_roles(interaction)
        if not member:
            return False
        if member.guild_permissions.administrator:
            return True
        if interaction.user.id in (config.MODERATOR_USER_IDS | config.ADMIN_USER_IDS):
            return True
        role_ids = _get_role_ids(member)
        role_names = _get_role_names(member)
        mod_by_id = bool(role_ids & (config.MODERATOR_ROLE_IDS | config.ADMIN_ROLE_IDS))
        mod_by_name = bool(role_names & (config.MODERATOR_ROLE_NAMES | config.ADMIN_ROLE_NAMES))
        return mod_by_id or mod_by_name

    return app_commands.check(predicate)


def admin_only():
    """Check that user has Admin role or is server admin."""

    async def predicate(interaction: discord.Interaction) -> bool:
        member = await _get_member_with_roles(interaction)
        if not member:
            return False
        if member.guild_permissions.administrator:
            return True
        if interaction.user.id in config.ADMIN_USER_IDS:
            return True
        role_ids = _get_role_ids(member)
        role_names = _get_role_names(member)
        return bool(role_ids & config.ADMIN_ROLE_IDS) or bool(role_names & config.ADMIN_ROLE_NAMES)

    return app_commands.check(predicate)
