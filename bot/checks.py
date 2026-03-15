"""Permission checks for slash commands."""
from __future__ import annotations

import logging

import discord
from discord import app_commands

import config

logger = logging.getLogger("octane.checks")


def _role_id_name(r) -> tuple[int, str]:
    """Extract (role_id, name) from API dict or Role object."""
    if isinstance(r, dict):
        return int(r["id"]), (r.get("name") or "").lower()
    return int(r.id), (getattr(r, "name", None) or "").lower()


async def _fetch_guild_role_names(client, guild_id: int) -> dict[int, str]:
    """Fetch guild roles via Discord API. Returns {role_id: name}."""
    try:
        data = await client.http.get_roles(guild_id)
        # Discord API returns list of role objects; discord.py may return list of dicts
        if not isinstance(data, (list, tuple)):
            logger.warning("get_roles returned unexpected type %s for guild %s", type(data).__name__, guild_id)
            return {}
        result = {}
        for r in data:
            try:
                rid, name = _role_id_name(r)
                result[rid] = name
            except (KeyError, TypeError, ValueError) as e:
                logger.debug("Skipping role %r: %s", r, e)
                continue
        logger.info("Fetched %d role names for guild %s (resolved %d)", len(data), guild_id, len(result))
        return result
    except discord.NotFound:
        logger.debug("Guild %s not found (bot may have been removed)", guild_id)
        return {}
    except Exception as e:
        logger.warning("Failed to fetch guild roles for %s: %s", guild_id, e)
        return {}


async def _resolve_role_names(
    role_ids: set[int], guild: discord.Guild | None, client: discord.Client
) -> set[str]:
    """Resolve role IDs to names. Uses HTTP API first (most reliable), then cache."""
    names: set[str] = set()
    if not role_ids or not guild:
        logger.debug("_resolve_role_names: no role_ids or guild")
        return names
    # 1. HTTP API first - most reliable, doesn't depend on cache
    fetched = await _fetch_guild_role_names(client, guild.id)
    names = {fetched[rid] for rid in role_ids if rid in fetched}
    missing = role_ids - set(fetched.keys())
    if missing and fetched:
        logger.info("User role IDs %s not in guild %s fetched roles (have %d)", missing, guild.id, len(fetched))
    # 2. Fallback: guild.roles from cache when HTTP fails (e.g. bot not in guild)
    if not names and guild.roles:
        for role in guild.roles:
            if role.id in role_ids:
                names.add(role.name.lower())
    # 3. Last resort: refresh guild then use cache
    if not names:
        try:
            await guild.fetch()
            for role in guild.roles:
                if role.id in role_ids:
                    names.add(role.name.lower())
        except Exception:
            pass
    return names


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
    member.roles is incomplete. Falls back to iterating guild.roles when get_role returns None."""
    names = {r.name.lower() for r in member.roles}
    raw = getattr(member, "_roles", None)
    guild = member.guild
    if raw is not None and guild is not None:
        for role_id in raw:
            rid = int(role_id)
            role = guild.get_role(rid)
            if role is None and guild.roles:
                # Fallback: guild cache may not have role via get_role; iterate
                for r in guild.roles:
                    if r.id == rid:
                        role = r
                        break
            if role is not None and role.name.lower() not in names:
                names.add(role.name.lower())
    return names


async def _get_member_with_roles(interaction: discord.Interaction) -> discord.Member | None:
    """Get Member with roles. Fetches via REST API when possible for accurate permissions.
    Falls back to gateway member when fetch fails (e.g. Server Members Intent disabled)."""
    if not interaction.guild:
        return None
    try:
        return await interaction.guild.fetch_member(interaction.user.id)
    except (discord.NotFound, discord.HTTPException):
        pass
    return _get_member(interaction)


def _user_has_mod_or_higher(interaction: discord.Interaction) -> bool:
    """True if user is server admin, has Manage Server, or has moderator/admin role (by ID or name)."""
    member = _get_member(interaction)
    if not member:
        return False
    if member.guild_permissions.administrator:
        return True
    if member.guild_permissions.manage_guild:
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
    """Check that user has Moderator or Admin role, is server admin, or has Manage Server (can add bot)."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            return False
        # Server owner always has full permissions
        if interaction.guild.owner_id == interaction.user.id:
            return True
        member = await _get_member_with_roles(interaction)
        if not member:
            return False
        if member.guild_permissions.administrator:
            return True
        # Manage Server = permission needed to add a bot; grant mod access without .env config
        if member.guild_permissions.manage_guild:
            return True
        if interaction.user.id in (config.MODERATOR_USER_IDS | config.ADMIN_USER_IDS):
            return True
        role_ids = _get_role_ids(member)
        role_names = _get_role_names(member)
        if not role_names and role_ids and interaction.guild:
            role_names = await _resolve_role_names(
                role_ids, interaction.guild, interaction.client
            )
        mod_by_id = bool(role_ids & (config.MODERATOR_ROLE_IDS | config.ADMIN_ROLE_IDS))
        mod_by_name = bool(role_names & (config.MODERATOR_ROLE_NAMES | config.ADMIN_ROLE_NAMES))
        return mod_by_id or mod_by_name

    return app_commands.check(predicate)


async def user_has_mod_in_guild(guild, discord_user_id: int, *, client=None) -> bool:
    """Check if a Discord user has mod/admin role in a guild. Used by HTTP API for verification."""
    if not guild:
        return False
    if guild.owner_id == discord_user_id:
        return True
    try:
        member = await guild.fetch_member(discord_user_id)
    except (discord.NotFound, discord.HTTPException):
        return False
    if member.guild_permissions.administrator:
        return True
    # Manage Server = permission needed to add a bot; grant mod access without .env config
    if member.guild_permissions.manage_guild:
        return True
    if discord_user_id in (config.MODERATOR_USER_IDS | config.ADMIN_USER_IDS):
        return True
    role_ids = _get_role_ids(member)
    role_names = _get_role_names(member)
    if not role_names and role_ids and client:
        role_names = await _resolve_role_names(role_ids, guild, client)
    mod_by_id = bool(role_ids & (config.MODERATOR_ROLE_IDS | config.ADMIN_ROLE_IDS))
    mod_by_name = bool(role_names & (config.MODERATOR_ROLE_NAMES | config.ADMIN_ROLE_NAMES))
    return mod_by_id or mod_by_name


def admin_only():
    """Check that user has Admin role or is server admin."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            return False
        # Server owner always has full permissions
        if interaction.guild.owner_id == interaction.user.id:
            return True
        member = await _get_member_with_roles(interaction)
        if not member:
            return False
        if member.guild_permissions.administrator:
            return True
        if interaction.user.id in config.ADMIN_USER_IDS:
            return True
        role_ids = _get_role_ids(member)
        role_names = _get_role_names(member)
        if not role_names and role_ids and interaction.guild:
            role_names = await _resolve_role_names(
                role_ids, interaction.guild, interaction.client
            )
        return bool(role_ids & config.ADMIN_ROLE_IDS) or bool(role_names & config.ADMIN_ROLE_NAMES)

    return app_commands.check(predicate)
