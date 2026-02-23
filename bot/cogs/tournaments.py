"""Tournaments cog - /tournament create, list, register, post, edit, delete."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete as sql_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

import discord
from discord import app_commands

from bot.checks import admin_only, mod_or_higher
from bot.models import Player, Registration, Tournament, TournamentSignupMessage
from bot.models.base import get_async_session
from bot.services.rl_api import RLAPIService
import config

SIGNUP_EMOJI = "📝"  # React to sign up


async def _default_tournament_name(guild_id: int, format_str: str, session: AsyncSession) -> str:
    """Generate default name: M-D-YYYY_format, with (x) suffix for duplicates."""
    now = datetime.now(timezone.utc)
    date_str = f"{now.month}-{now.day}-{now.year}"  # e.g. 2-23-2026
    base = f"{date_str}_{format_str}"
    # Escape _ for SQL LIKE (underscore is wildcard)
    pattern = base.replace("_", "\\_") + "%"
    result = await session.execute(
        select(Tournament).where(
            Tournament.guild_id == guild_id,
            Tournament.name.like(pattern, escape="\\"),
        )
    )
    existing = result.scalars().all()
    count = len(existing)
    return f"{base} ({count})" if count > 0 else base


FORMAT_CHOICES = [
    app_commands.Choice(name="1v1", value="1v1"),
    app_commands.Choice(name="2v2", value="2v2"),
    app_commands.Choice(name="3v3", value="3v3"),
    app_commands.Choice(name="4v4", value="4v4"),
    app_commands.Choice(name="Custom (e.g. 4v4)", value="custom"),
]

MMR_PLAYLIST_CHOICES = [
    app_commands.Choice(name="Solo Duel", value="solo_duel"),
    app_commands.Choice(name="Doubles", value="doubles"),
    app_commands.Choice(name="Standard", value="standard"),
    app_commands.Choice(name="Hoops", value="hoops"),
    app_commands.Choice(name="Rumble", value="rumble"),
    app_commands.Choice(name="Dropshot", value="dropshot"),
    app_commands.Choice(name="Snow Day", value="snow_day"),
    app_commands.Choice(name="Tournaments", value="tournaments"),
]


async def get_player(session: AsyncSession, discord_id: int):
    result = await session.execute(select(Player).where(Player.discord_id == discord_id))
    return result.scalar_one_or_none()


async def get_tournament(session: AsyncSession, tournament_id: int, guild_id: int):
    result = await session.execute(
        select(Tournament).where(
            Tournament.id == tournament_id,
            Tournament.guild_id == guild_id,
        )
    )
    return result.scalar_one_or_none()


def _build_signup_embed(t: Tournament, count: int) -> discord.Embed:
    """Build the signup embed for a tournament."""
    deadline_line = ""
    if t.registration_deadline:
        dt = t.registration_deadline
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ts = int(dt.timestamp())
        deadline_line = f"**Signup deadline:** <t:{ts}:F> (<t:{ts}:R>)\n\n"
    embed = discord.Embed(
        title=f"📋 {t.name}",
        description=(
            f"**Format:** {t.format}\n"
            f"**MMR Playlist:** {t.mmr_playlist}\n\n"
            f"{deadline_line}"
            f"React with {SIGNUP_EMOJI} to sign up!\n"
            f"Remove your reaction to drop out.\n\n"
            f"*Or use `/tournament register` with ID **{t.id}***"
        ),
        color=discord.Color.green(),
    )
    embed.set_footer(text=f"Tournament ID: {t.id} • {count} signed up")
    embed.timestamp = discord.utils.utcnow()
    return embed


def _parse_deadline(s: str) -> Optional[datetime]:
    """Parse deadline string (YYYY-MM-DD HH:mm, ISO, or <t:unix:R>) to UTC datetime."""
    s = s.strip()
    if not s:
        return None
    # Discord timestamp: <t:1771834500:R> or <t:1771834500:F>
    m = re.search(r"<t:(\d+):[^>]*>", s)
    if m:
        try:
            ts = int(m.group(1))
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OSError):
            pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


tournament_group = app_commands.Group(name="tournament", description="Tournament management")


@tournament_group.command(name="create", description="Create a new tournament (Moderator+)")
@app_commands.describe(
    name="Tournament name (optional, defaults to date_format e.g. 2-23-2026_2v2)",
    format="1v1, 2v2, or 3v3",
    mmr_playlist="Playlist to use for MMR seeding",
    deadline="Registration deadline (e.g. 2026-02-24 18:00, UTC)",
)
@app_commands.choices(format=FORMAT_CHOICES, mmr_playlist=MMR_PLAYLIST_CHOICES)
@mod_or_higher()
async def create(
    interaction: discord.Interaction,
    format: str,
    mmr_playlist: str,
    name: Optional[str] = None,
    deadline: Optional[str] = None,
) -> None:
    """Create a tournament. Name defaults to M-D-YYYY_format (e.g. 2-23-2026_2v2), with (1), (2) for duplicates."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    if deadline:
        parsed = _parse_deadline(deadline)
        if not parsed:
            await interaction.response.send_message(
                "Invalid deadline format. Use YYYY-MM-DD HH:mm (e.g. 2026-02-24 18:00).",
                ephemeral=True,
            )
            return
    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        if not name or not name.strip():
            name = await _default_tournament_name(interaction.guild_id, format, session)
        else:
            name = name.strip()
        reg_deadline = _parse_deadline(deadline) if deadline else None
        t = Tournament(
            guild_id=interaction.guild_id,
            name=name,
            format=format,
            mmr_playlist=mmr_playlist,
            status="open",
            registration_deadline=reg_deadline,
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)
        msg = f"Created tournament **{name}** ({format}, MMR from {mmr_playlist}). ID: {t.id}"
        if reg_deadline:
            msg += f"\nRegistration deadline: {reg_deadline.strftime('%Y-%m-%d %H:%M')} UTC"
        await interaction.followup.send(msg, ephemeral=True)
        return


@tournament_group.command(name="list", description="List tournaments in this server")
async def list_cmd(interaction: discord.Interaction) -> None:
    """List tournaments."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    await interaction.response.defer()

    async for session in get_async_session():
        result = await session.execute(
            select(Tournament).where(Tournament.guild_id == interaction.guild_id).order_by(Tournament.id.desc()).limit(10)
        )
        tournaments = result.scalars().all()
        if not tournaments:
            await interaction.followup.send("No tournaments found.")
            return
        lines = []
        for t in tournaments:
            lines.append(f"**{t.id}** — {t.name} ({t.format}, {t.mmr_playlist}) — {t.status}")
        embed = discord.Embed(title="Tournaments", description="\n".join(lines), color=discord.Color.blue())
        await interaction.followup.send(embed=embed)
        return


@tournament_group.command(name="register", description="Register for a tournament")
@app_commands.describe(tournament_id="Tournament ID to register for")
async def register_cmd(interaction: discord.Interaction, tournament_id: int) -> None:
    """Register for a tournament."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        player = await get_player(session, interaction.user.id)
        if not player:
            await interaction.followup.send(
                "Register first with `/register`.",
                ephemeral=True,
            )
            return
        t = await get_tournament(session, tournament_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        if t.status != "open":
            await interaction.followup.send(f"Tournament is {t.status}, registration closed.", ephemeral=True)
            return
        if t.registration_deadline:
            deadline = t.registration_deadline
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > deadline:
                ts = int(deadline.timestamp())
                await interaction.followup.send(
                    f"Registration closed. Deadline was <t:{ts}:F>.",
                    ephemeral=True,
                )
                return
        existing = await session.execute(
            select(Registration).where(
                Registration.tournament_id == tournament_id,
                Registration.player_id == interaction.user.id,
            )
        )
        if existing.scalar_one_or_none():
            await interaction.followup.send("You're already registered.", ephemeral=True)
            return
        session.add(Registration(tournament_id=tournament_id, player_id=interaction.user.id))
        await session.commit()
        await interaction.followup.send(f"Registered for **{t.name}**!", ephemeral=True)
        return


@tournament_group.command(name="unregister", description="Unregister from a tournament")
@app_commands.describe(tournament_id="Tournament ID to unregister from")
async def unregister_cmd(interaction: discord.Interaction, tournament_id: int) -> None:
    """Unregister from a tournament."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        t = await get_tournament(session, tournament_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        if t.status != "open":
            await interaction.followup.send(
                f"Tournament is {t.status}. Ask a moderator to remove you.",
                ephemeral=True,
            )
            return
        result = await session.execute(
            select(Registration).where(
                Registration.tournament_id == tournament_id,
                Registration.player_id == interaction.user.id,
                Registration.team_id.is_(None),
            )
        )
        reg = result.scalar_one_or_none()
        if not reg:
            await interaction.followup.send("You're not registered for this tournament.", ephemeral=True)
            return
        await session.delete(reg)
        await session.commit()
        await interaction.followup.send(f"Unregistered from **{t.name}**.", ephemeral=True)
        return


@tournament_group.command(name="post", description="Post a signup message — users react to sign up (Moderator+)")
@app_commands.describe(
    tournament_id="Tournament ID to post signup for",
    channel="Channel to post in (default: current channel)",
)
@mod_or_higher()
async def post(
    interaction: discord.Interaction,
    tournament_id: int,
    channel: Optional[discord.TextChannel] = None,
) -> None:
    """Post a signup embed. Users react with 📝 to sign up, or use /tournament register."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    target_channel = channel or interaction.channel
    if not isinstance(target_channel, discord.TextChannel):
        await interaction.response.send_message("Cannot post in this channel type.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        t = await get_tournament(session, tournament_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        if t.status != "open":
            await interaction.followup.send(
                f"Tournament is {t.status}. Set status to 'open' before posting signup.",
                ephemeral=True,
            )
            return

        # Count current registrations
        reg_count = await session.execute(
            select(Registration).where(Registration.tournament_id == tournament_id)
        )
        count = len(reg_count.scalars().all())
        embed = _build_signup_embed(t, count)

        # Retire old signup messages so only this post is active (avoids duplicate posts confusion)
        old_result = await session.execute(
            select(TournamentSignupMessage).where(TournamentSignupMessage.tournament_id == tournament_id)
        )
        had_old = len(old_result.scalars().all()) > 0
        await session.execute(
            sql_delete(TournamentSignupMessage).where(TournamentSignupMessage.tournament_id == tournament_id)
        )

        try:
            if target_channel.type == discord.ChannelType.forum:
                thread = await target_channel.create_thread(name=f"📋 {t.name} — Sign up", embed=embed)
                msg = thread  # create_thread returns Thread; first message is the one we created
                # Get the starter message to add reaction
                starter = await thread.fetch_message(thread.id) if hasattr(thread, "fetch_message") else None
                if starter is None:
                    # Thread's starter message has same ID as thread
                    try:
                        starter = await thread.fetch_message(thread.id)
                    except Exception:
                        pass
                if starter:
                    await starter.add_reaction(SIGNUP_EMOJI)
                msg_for_id = thread
            else:
                msg = await target_channel.send(embed=embed)
                await msg.add_reaction(SIGNUP_EMOJI)
                msg_for_id = msg
        except discord.Forbidden:
            await interaction.followup.send(
                f"Missing Access: I can't post in {target_channel.mention}. "
                "Ensure my role has Send Messages, Embed Links, Create Public Threads, and Add Reactions.",
                ephemeral=True,
            )
            return

        session.add(
            TournamentSignupMessage(
                message_id=msg.id,
                channel_id=msg.channel.id,
                guild_id=interaction.guild_id,
                tournament_id=tournament_id,
                signup_emoji=SIGNUP_EMOJI,
            )
        )
        await session.commit()

        followup = f"Posted signup for **{t.name}** in {target_channel.mention}. Users can react with {SIGNUP_EMOJI} to sign up."
        if had_old:
            followup += " Previous signup post(s) were retired — delete the old message(s) if still visible to avoid confusion."
        if t.registration_deadline:
            dt = t.registration_deadline
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ts = int(dt.timestamp())
            followup += f"\n\n**Copy for announcements:** `<t:{ts}:R>` or `<t:{ts}:F>`"
        await interaction.followup.send(followup, ephemeral=True)
        return


@tournament_group.command(name="edit", description="Edit a tournament (Moderator+)")
@app_commands.describe(
    tournament_id="Tournament ID",
    name="New name (optional)",
    status="New status: open, closed, in_progress, completed",
    deadline="Registration deadline (e.g. 2026-02-24 18:00 UTC). Use empty to clear.",
)
@mod_or_higher()
async def edit(
    interaction: discord.Interaction,
    tournament_id: int,
    name: Optional[str] = None,
    status: Optional[str] = None,
    deadline: Optional[str] = None,
) -> None:
    """Edit tournament."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    if deadline is not None and deadline.strip():
        parsed = _parse_deadline(deadline)
        if not parsed:
            await interaction.response.send_message(
                "Invalid deadline format. Use YYYY-MM-DD HH:mm (e.g. 2026-02-24 18:00).",
                ephemeral=True,
            )
            return
    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        t = await get_tournament(session, tournament_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        if name:
            t.name = name
        if status:
            t.status = status
        if deadline is not None:
            t.registration_deadline = _parse_deadline(deadline) if deadline.strip() else None
        await session.commit()
        await session.refresh(t)

        # If deadline changed, try to update existing signup embed
        signup_updated = False
        signup_failed = False
        if deadline is not None:
            result = await session.execute(
                select(TournamentSignupMessage).where(
                    TournamentSignupMessage.tournament_id == tournament_id,
                )
            )
            signup_msgs = result.scalars().all()
            reg_count = len(
                (await session.execute(select(Registration).where(Registration.tournament_id == tournament_id))).scalars().all()
            )
            embed = _build_signup_embed(t, reg_count)
            for sm in signup_msgs:
                try:
                    ch = interaction.client.get_channel(sm.channel_id) or await interaction.client.fetch_channel(sm.channel_id)
                    msg = await ch.fetch_message(sm.message_id)
                    await msg.edit(embed=embed)
                    signup_updated = True
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    signup_failed = True

        followup = f"Updated tournament **{t.name}**."
        if deadline is not None:
            if signup_updated:
                followup += " Updated the signup post with the new deadline."
            elif signup_failed:
                followup += " There is a signup post but I couldn't update it (deleted or no permission). Repost with `/tournament post` to show the deadline."
        await interaction.followup.send(followup, ephemeral=True)
        return


@tournament_group.command(name="delete", description="Delete a tournament (Admin only)")
@app_commands.describe(tournament_id="Tournament ID to delete")
@admin_only()
async def delete(interaction: discord.Interaction, tournament_id: int) -> None:
    """Delete tournament."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        t = await get_tournament(session, tournament_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        name = t.name
        await session.delete(t)
        await session.commit()
        await interaction.followup.send(f"Deleted tournament **{name}**.", ephemeral=True)
        return
