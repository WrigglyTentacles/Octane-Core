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
from bot.models import GuildConfig, Player, Registration, Team, Tournament, TournamentSignupMessage
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


def _build_signup_embed(t: Tournament, count: int, guild_id: int) -> discord.Embed:
    """Build the signup embed for a tournament. Uses guild-aware URL."""
    from web.api.web_urls import bracket_url

    deadline_line = ""
    starts_line = ""
    reg_ts = None
    if t.registration_deadline:
        dt = t.registration_deadline
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        reg_ts = int(dt.timestamp())
        deadline_line = f"**Signup deadline:** <t:{reg_ts}:F> (<t:{reg_ts}:R>)\n\n"
    if t.starts_at:
        dt = t.starts_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ts = int(dt.timestamp())
        starts_line = f"**Tournament begins:** <t:{ts}:F> (<t:{ts}:R>)\n\n"
    current_link = ""
    url = bracket_url(guild_id)
    if url:
        current_link = f"\n\n**View bracket:** {url}"
    embed = discord.Embed(
        title=f"📋 {t.name}",
        description=(
            f"**Format:** {t.format}\n"
            f"**MMR Playlist:** {t.mmr_playlist}\n\n"
            f"{deadline_line}"
            f"{starts_line}"
            f"React with {SIGNUP_EMOJI} to sign up!\n"
            f"Remove your reaction to drop out.\n\n"
            f"*Or use `/tournament register` with ID **{t.id}***"
            f"{current_link}"
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


def _apply_time_defaults(reg_deadline: Optional[datetime], starts_at: Optional[datetime]) -> tuple[Optional[datetime], Optional[datetime]]:
    """If only one of registration_deadline/starts_at is set, use it for both."""
    if reg_deadline and starts_at:
        return reg_deadline, starts_at
    if reg_deadline:
        return reg_deadline, reg_deadline
    if starts_at:
        return starts_at, starts_at
    return None, None


@tournament_group.command(name="create", description="Create a new tournament (Moderator+)")
@app_commands.describe(
    name="Tournament name (optional, defaults to date_format e.g. 2-23-2026_2v2)",
    format="1v1, 2v2, or 3v3",
    mmr_playlist="Playlist to use for MMR seeding",
    deadline="Signup deadline (e.g. 2026-02-24 18:00, UTC). Defaults to starts_at if omitted.",
    starts_at="When tournament begins (e.g. 2026-02-24 19:00). Defaults to deadline if omitted.",
)
@app_commands.choices(format=FORMAT_CHOICES, mmr_playlist=MMR_PLAYLIST_CHOICES)
@mod_or_higher()
async def create(
    interaction: discord.Interaction,
    format: str,
    mmr_playlist: str,
    name: Optional[str] = None,
    deadline: Optional[str] = None,
    starts_at: Optional[str] = None,
) -> None:
    """Create a tournament. Name defaults to M-D-YYYY_format (e.g. 2-23-2026_2v2), with (1), (2) for duplicates."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    for s, label in ((deadline, "deadline"), (starts_at, "starts_at")):
        if s and not _parse_deadline(s):
            await interaction.response.send_message(
                f"Invalid {label} format. Use YYYY-MM-DD HH:mm (e.g. 2026-02-24 18:00).",
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
        starts_dt = _parse_deadline(starts_at) if starts_at else None
        reg_deadline, starts_dt = _apply_time_defaults(reg_deadline, starts_dt)
        t = Tournament(
            guild_id=interaction.guild_id,
            name=name,
            format=format,
            mmr_playlist=mmr_playlist,
            status="open",
            registration_deadline=reg_deadline,
            starts_at=starts_dt,
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)
        msg = f"Created tournament **{name}** ({format}, MMR from {mmr_playlist}). ID: {t.id}"
        if reg_deadline:
            msg += f"\nSignup deadline: {reg_deadline.strftime('%Y-%m-%d %H:%M')} UTC"
        if starts_dt and (not reg_deadline or reg_deadline != starts_dt):
            msg += f"\nTournament begins: {starts_dt.strftime('%Y-%m-%d %H:%M')} UTC"
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
        display_name = interaction.user.display_name or str(interaction.user)
        if not player:
            player = Player(
                discord_id=interaction.user.id,
                display_name=display_name,
            )
            session.add(player)
            await session.flush()
        else:
            # Refresh display_name when they register (may have changed)
            player.display_name = display_name
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


@tournament_group.command(name="status", description="Check if you're signed up for a tournament")
@app_commands.describe(tournament_id="Tournament ID (optional — omit to list all open tournaments)")
async def status_cmd(interaction: discord.Interaction, tournament_id: Optional[int] = None) -> None:
    """Check signup status. With no ID, lists open tournaments and your status. With ID, shows status for that tournament."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        if tournament_id is not None:
            t = await get_tournament(session, tournament_id, interaction.guild_id)
            if not t:
                await interaction.followup.send("Tournament not found.", ephemeral=True)
                return
            result = await session.execute(
                select(Registration).where(
                    Registration.tournament_id == tournament_id,
                    Registration.player_id == interaction.user.id,
                )
            )
            reg = result.scalar_one_or_none()
            time_parts = []
            if t.registration_deadline:
                dt = t.registration_deadline
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                time_parts.append(f"Signup: <t:{int(dt.timestamp())}:R>")
            if t.starts_at:
                dt = t.starts_at
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                time_parts.append(f"Begins: <t:{int(dt.timestamp())}:R>")
            time_line = "\n" + " | ".join(time_parts) if time_parts else ""
            if reg:
                team_info = ""
                if reg.team_id:
                    team = await session.get(Team, reg.team_id)
                    team_info = f" (Team: **{team.name}**)" if team else ""
                await interaction.followup.send(
                    f"✓ You're signed up for **{t.name}** ({t.format}){team_info}.{time_line}",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"You're not signed up for **{t.name}** ({t.format}). React to the signup post or use `/tournament register {t.id}`.{time_line}",
                    ephemeral=True,
                )
            return

        # List all open tournaments in guild
        result = await session.execute(
            select(Tournament)
            .where(Tournament.guild_id == interaction.guild_id, Tournament.status == "open")
            .order_by(Tournament.id.desc())
            .limit(20)
        )
        tournaments = result.scalars().all()
        if not tournaments:
            await interaction.followup.send("No open tournaments in this server.", ephemeral=True)
            return
        reg_result = await session.execute(
            select(Registration.tournament_id).where(
                Registration.player_id == interaction.user.id,
                Registration.tournament_id.in_([t.id for t in tournaments]),
            )
        )
        signed_up_ids = {r[0] for r in reg_result.all()}
        def _time_line(t: Tournament) -> str:
            parts = []
            if t.registration_deadline:
                dt = t.registration_deadline
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                ts = int(dt.timestamp())
                parts.append(f"Signup: <t:{ts}:R>")
            if t.starts_at:
                dt = t.starts_at
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                ts = int(dt.timestamp())
                parts.append(f"Begins: <t:{ts}:R>")
            return " · " + " | ".join(parts) if parts else ""

        lines = []
        for t in tournaments:
            mark = "✓" if t.id in signed_up_ids else "✗"
            lines.append(f"{mark} **{t.name}** (ID: {t.id}, {t.format}){_time_line(t)}")
        await interaction.followup.send(
            "**Your signup status:**\n" + "\n".join(lines) + "\n\n*Use `/tournament status <id>` for details.*",
            ephemeral=True,
        )
        return


@tournament_group.command(name="set-signup-channel", description="Set this channel for web-triggered signup posts (Moderator+)")
@mod_or_higher()
async def set_signup_channel_cmd(interaction: discord.Interaction) -> None:
    """Set the current channel as the signup channel. Use this in the channel where you want signup messages posted from the web UI."""
    if not interaction.guild_id or not interaction.channel:
        await interaction.response.send_message("Use this in a server channel.", ephemeral=True)
        return
    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("This command must be used in a text channel.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        result = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == interaction.guild_id))
        gc = result.scalar_one_or_none()
        if not gc:
            gc = GuildConfig(guild_id=interaction.guild_id, name=interaction.guild.name)
            session.add(gc)
            await session.flush()
        gc.discord_signup_channel_id = interaction.channel.id
        gc.discord_signup_channel_name = interaction.channel.name
        await session.commit()
        break

    await interaction.followup.send(
        f"✓ Signup channel set to **#{interaction.channel.name}**. You can now post signup messages from the web UI.",
        ephemeral=True,
    )


@tournament_group.command(name="unregister", description="Unregister from a tournament")
@app_commands.describe(tournament_id="Tournament ID to unregister from")
async def unregister_cmd(interaction: discord.Interaction, tournament_id: int) -> None:
    """Unregister from a tournament. If on a team, moves you to unassigned; if unassigned, fully leaves."""
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
            )
        )
        reg = result.scalar_one_or_none()
        if not reg:
            await interaction.followup.send("You're not registered for this tournament.", ephemeral=True)
            return
        if reg.team_id:
            reg.team_id = None
            await session.commit()
            await interaction.followup.send(f"Moved to unassigned in **{t.name}**. You can be re-added to a team.", ephemeral=True)
        else:
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
        guild_id = t.guild_id if t.guild_id else (interaction.guild_id or 0)
        embed = _build_signup_embed(t, count, guild_id)

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
                msg = thread  # create_thread returns Thread; starter message ID = thread.id
            else:
                msg = await target_channel.send(embed=embed)
        except discord.Forbidden:
            await interaction.followup.send(
                f"Missing Access: I can't post in {target_channel.mention}. "
                "Ensure my role has Send Messages, Embed Links, Create Public Threads, and Add Reactions.",
                ephemeral=True,
            )
            return

        # Commit signup message BEFORE adding reaction so reaction handler can find it (avoids race)
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

        try:
            if target_channel.type == discord.ChannelType.forum:
                starter = await thread.fetch_message(thread.id)
                await starter.add_reaction(SIGNUP_EMOJI)
            else:
                await msg.add_reaction(SIGNUP_EMOJI)
        except discord.Forbidden:
            pass  # Message already posted; reaction is optional

        followup = f"Posted signup for **{t.name}** in {target_channel.mention}. Users can react with {SIGNUP_EMOJI} to sign up."
        if had_old:
            followup += " Previous signup post(s) were retired — delete the old message(s) if still visible to avoid confusion."
        await interaction.followup.send(followup, ephemeral=True)
        return


@tournament_group.command(name="edit", description="Edit a tournament (Moderator+)")
@app_commands.describe(
    tournament_id="Tournament ID",
    name="New name (optional)",
    status="New status: open, closed, in_progress, completed",
    deadline="Signup deadline (e.g. 2026-02-24 18:00 UTC). Use empty to clear.",
    starts_at="When tournament begins. Use empty to clear. Defaults to deadline if only one provided.",
)
@mod_or_higher()
async def edit(
    interaction: discord.Interaction,
    tournament_id: int,
    name: Optional[str] = None,
    status: Optional[str] = None,
    deadline: Optional[str] = None,
    starts_at: Optional[str] = None,
) -> None:
    """Edit tournament."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    for s, label in ((deadline, "deadline"), (starts_at, "starts_at")):
        if s is not None and s.strip() and not _parse_deadline(s):
            await interaction.response.send_message(
                f"Invalid {label} format. Use YYYY-MM-DD HH:mm (e.g. 2026-02-24 18:00).",
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
        if deadline is not None or starts_at is not None:
            reg_deadline = _parse_deadline(deadline) if deadline is not None else t.registration_deadline
            starts_dt = _parse_deadline(starts_at) if starts_at is not None else t.starts_at
            t.registration_deadline, t.starts_at = _apply_time_defaults(reg_deadline, starts_dt)
        await session.commit()
        await session.refresh(t)

        # If times changed, try to update existing signup embed
        signup_updated = False
        signup_failed = False
        if deadline is not None or starts_at is not None:
            result = await session.execute(
                select(TournamentSignupMessage).where(
                    TournamentSignupMessage.tournament_id == tournament_id,
                )
            )
            signup_msgs = result.scalars().all()
            reg_count = len(
                (await session.execute(select(Registration).where(Registration.tournament_id == tournament_id))).scalars().all()
            )
            guild_id = t.guild_id if t.guild_id else (interaction.guild_id or 0)
            embed = _build_signup_embed(t, reg_count, guild_id)
            for sm in signup_msgs:
                try:
                    ch = interaction.client.get_channel(sm.channel_id) or await interaction.client.fetch_channel(sm.channel_id)
                    msg = await ch.fetch_message(sm.message_id)
                    await msg.edit(embed=embed)
                    signup_updated = True
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    signup_failed = True

        followup = f"Updated tournament **{t.name}**."
        if deadline is not None or starts_at is not None:
            if signup_updated:
                followup += " Updated the signup post with the new times."
            elif signup_failed:
                followup += " There is a signup post but I couldn't update it (deleted or no permission). Repost with `/tournament post` to show the times."
        await interaction.followup.send(followup, ephemeral=True)
        return


@tournament_group.command(name="cleanup", description="Delete bot messages for a tournament (signup, teams, round, results)")
@app_commands.describe(tournament_id="Tournament ID to clean up")
@mod_or_higher()
async def cleanup(interaction: discord.Interaction, tournament_id: int) -> None:
    """Remove all tracked Discord messages for a tournament (signup, teams, round, results)."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    from bot.http_server import _delete_tournament_messages

    async for session in get_async_session():
        t = await get_tournament(session, tournament_id, interaction.guild_id)
        if not t:
            await interaction.followup.send("Tournament not found.", ephemeral=True)
            return
        deleted = await _delete_tournament_messages(
            interaction.client, session, tournament_id, include_results=True
        )
        await session.commit()
        await interaction.followup.send(
            f"Cleaned up **{t.name}**: removed {deleted} message(s) from Discord.",
            ephemeral=True,
        )
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
