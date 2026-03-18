"""Internal HTTP server for web-triggered Discord actions (e.g. post signup)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiohttp.web
import discord
from sqlalchemy import delete as sql_delete, select

import config
from bot.models import Bracket, BracketMatch, Player, Registration, Team, TeamManualMember, Tournament, TournamentManualEntry, TournamentSignupMessage, TournamentBracketMessage
from bot.services.discord_embeds import (
    build_results_embed,
    build_roster_embed,
    build_round_lineup_embed,
    build_teams_embed,
    champion_match_has_winner,
    get_champion_info,
)

logger = logging.getLogger("octane.http")

SIGNUP_EMOJI = "📝"


async def _delete_tournament_messages(bot, session, tournament_id: int, *, include_results: bool = False) -> int:
    """Delete Discord messages for this tournament. Returns count of messages deleted.
    - include_results=False: signup + teams/round only (for post-results flow)
    - include_results=True: all tracked messages including results (for cleanup-only)
    """
    deleted = 0
    # Signup messages
    result = await session.execute(
        select(TournamentSignupMessage).where(TournamentSignupMessage.tournament_id == tournament_id)
    )
    for sm in result.scalars().all():
        try:
            ch = bot.get_channel(sm.channel_id) or await bot.fetch_channel(sm.channel_id)
            if ch:
                msg = await ch.fetch_message(sm.message_id)
                await msg.delete()
                deleted += 1
        except Exception as e:
            logger.debug("Could not delete signup message %s: %s", sm.message_id, e)
        await session.delete(sm)

    # Bracket messages (teams, round, optionally results)
    if include_results:
        result = await session.execute(
            select(TournamentBracketMessage).where(
                TournamentBracketMessage.tournament_id == tournament_id
            )
        )
    else:
        result = await session.execute(
            select(TournamentBracketMessage).where(
                TournamentBracketMessage.tournament_id == tournament_id,
                TournamentBracketMessage.message_type != "results",
            )
        )
    for bm in result.scalars().all():
        try:
            ch = bot.get_channel(bm.channel_id) or await bot.fetch_channel(bm.channel_id)
            if ch:
                msg = await ch.fetch_message(bm.message_id)
                await msg.delete()
                deleted += 1
        except Exception as e:
            logger.debug("Could not delete bracket message %s: %s", bm.message_id, e)
        await session.delete(bm)

    if not include_results:
        # Delete old results rows (we'll add new one in post-results flow)
        await session.execute(
            sql_delete(TournamentBracketMessage).where(
                TournamentBracketMessage.tournament_id == tournament_id,
                TournamentBracketMessage.message_type == "results",
            )
        )
    return deleted


def _build_signup_embed(t: Tournament, count: int, guild_id: int) -> discord.Embed:
    """Build signup embed (same as tournaments cog). Uses guild-aware URL."""
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


async def _handle_post_signup(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST /internal/post-signup - Post signup message to Discord (called by web API)."""
    auth = request.headers.get("Authorization")
    if not config.INTERNAL_API_SECRET:
        logger.warning("INTERNAL_API_SECRET not set - rejecting post-signup")
        return aiohttp.web.json_response({"error": "Internal API not configured"}, status=503)
    if auth != f"Bearer {config.INTERNAL_API_SECRET}":
        return aiohttp.web.json_response({"error": "Unauthorized"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return aiohttp.web.json_response({"error": "Invalid JSON"}, status=400)

    tournament_id = body.get("tournament_id")
    channel_id = body.get("channel_id")
    guild_id = body.get("guild_id")
    if not all(isinstance(x, int) for x in (tournament_id, channel_id, guild_id)):
        return aiohttp.web.json_response(
            {"error": "tournament_id, channel_id, guild_id required (integers)"}, status=400
        )

    bot = request.app["bot"]
    from bot.models.base import get_async_session

    async for session in get_async_session():
        t = await session.get(Tournament, tournament_id)
        if not t:
            return aiohttp.web.json_response({"error": "Tournament not found"}, status=404)
        if t.status != "open":
            return aiohttp.web.json_response(
                {"error": f"Tournament is {t.status}. Set status to 'open' first."}, status=400
            )

        reg_count = await session.execute(
            select(Registration).where(Registration.tournament_id == tournament_id)
        )
        count = len(reg_count.scalars().all())
        embed_dict = _build_signup_embed(t, count, guild_id)

        # Retire old signup messages
        await session.execute(
            sql_delete(TournamentSignupMessage).where(TournamentSignupMessage.tournament_id == tournament_id)
        )

        try:
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        except Exception as e:
            logger.exception("Failed to fetch channel %s", channel_id)
            return aiohttp.web.json_response({"error": f"Failed to fetch channel: {e}"}, status=400)

        if not channel or channel.guild.id != guild_id:
            return aiohttp.web.json_response({"error": "Channel not found or wrong guild"}, status=400)

        try:
            msg = await channel.send(embed=embed_dict)
        except Exception as e:
            logger.exception("Failed to post signup message")
            return aiohttp.web.json_response(
                {"error": f"Failed to post: {e}. Check bot permissions (Send Messages, Embed Links, Add Reactions)."},
                status=400,
            )

        # Link tournament to guild if it was web-only
        if t.guild_id == 0:
            t.guild_id = guild_id

        # Commit BEFORE adding reaction so reaction handler can find it (avoids race)
        session.add(
            TournamentSignupMessage(
                message_id=msg.id,
                channel_id=msg.channel.id,
                guild_id=guild_id,
                tournament_id=tournament_id,
                signup_emoji=SIGNUP_EMOJI,
            )
        )
        await session.commit()

        try:
            await msg.add_reaction(SIGNUP_EMOJI)
        except Exception:
            pass  # Message posted; reaction is optional
        break

    return aiohttp.web.json_response({"ok": True, "message_id": msg.id})


async def _handle_refresh_players(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST /internal/refresh-players - Refresh display_name from Discord for given player_ids."""
    auth = request.headers.get("Authorization")
    if not config.INTERNAL_API_SECRET:
        return aiohttp.web.json_response({"error": "Internal API not configured"}, status=503)
    if auth != f"Bearer {config.INTERNAL_API_SECRET}":
        return aiohttp.web.json_response({"error": "Unauthorized"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return aiohttp.web.json_response({"error": "Invalid JSON"}, status=400)

    player_ids = body.get("player_ids", [])
    if not isinstance(player_ids, list):
        return aiohttp.web.json_response({"error": "player_ids must be a list"}, status=400)

    bot = request.app["bot"]
    from bot.models.base import get_async_session

    refreshed = 0
    async for session in get_async_session():
        for pid in player_ids:
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                continue
            try:
                user = bot.get_user(pid) or await bot.fetch_user(pid)
                display_name = user.display_name if user else None
            except Exception:
                display_name = None
            player = await session.get(Player, pid)
            if player:
                player.display_name = display_name or player.display_name
                refreshed += 1
            elif display_name:
                session.add(Player(discord_id=pid, display_name=display_name))
                refreshed += 1
        await session.commit()
        break

    return aiohttp.web.json_response({"ok": True, "refreshed": refreshed})


def _check_internal_auth(request: aiohttp.web.Request) -> aiohttp.web.Response | None:
    """Return error response if auth fails, else None."""
    auth = request.headers.get("Authorization")
    if not config.INTERNAL_API_SECRET:
        return aiohttp.web.json_response(
            {"error": "Internal API not configured"}, status=503
        )
    if auth != f"Bearer {config.INTERNAL_API_SECRET}":
        return aiohttp.web.json_response({"error": "Unauthorized"}, status=401)
    return None


async def _handle_post_results(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST /internal/post-results - Post tournament results embed when champion declared."""
    err = _check_internal_auth(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return aiohttp.web.json_response({"error": "Invalid JSON"}, status=400)

    tournament_id = body.get("tournament_id")
    channel_id = body.get("channel_id")
    guild_id = body.get("guild_id")
    if not all(isinstance(x, int) for x in (tournament_id, channel_id, guild_id)):
        return aiohttp.web.json_response(
            {"error": "tournament_id, channel_id, guild_id required (integers)"},
            status=400,
        )

    bot = request.app["bot"]
    from bot.models.base import get_async_session

    async for session in get_async_session():
        t = await session.get(Tournament, tournament_id)
        if not t:
            return aiohttp.web.json_response(
                {"error": "Tournament not found"}, status=404
            )
        bracket_result = await session.execute(
            select(Bracket).where(Bracket.tournament_id == tournament_id)
        )
        bracket = bracket_result.scalar_one_or_none()
        if not bracket:
            return aiohttp.web.json_response(
                {"error": "No bracket found"}, status=404
            )
        is_team = t.format != "1v1"
        guild = bot.get_guild(guild_id)
        champ_name, champ_members = await get_champion_info(
            session, bracket, is_team, guild, bot
        )
        if not champ_name:
            return aiohttp.web.json_response(
                {"error": "Could not determine champion"}, status=400
            )
        embed = build_results_embed(t, champ_name, champ_members)

        # Clean up old messages (signup, teams, round) so only results remain
        await _delete_tournament_messages(bot, session, tournament_id)
        await session.commit()

        try:
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        except Exception as e:
            logger.exception("Failed to fetch channel %s", channel_id)
            return aiohttp.web.json_response(
                {"error": f"Failed to fetch channel: {e}"}, status=400
            )
        if not channel or channel.guild.id != guild_id:
            return aiohttp.web.json_response(
                {"error": "Channel not found or wrong guild"}, status=400
            )
        try:
            msg = await channel.send(embed=embed)
        except Exception as e:
            logger.exception("Failed to post results")
            return aiohttp.web.json_response(
                {"error": f"Failed to post: {e}. Check bot permissions."},
                status=400,
            )
        session.add(
            TournamentBracketMessage(
                message_id=msg.id,
                channel_id=channel_id,
                guild_id=guild_id,
                tournament_id=tournament_id,
                message_type="results",
            )
        )
        await session.commit()
        return aiohttp.web.json_response({"ok": True, "message_id": msg.id})
    return aiohttp.web.json_response({"error": "Internal error"}, status=500)


async def _handle_cleanup_messages(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST /internal/cleanup-messages - Delete all tracked Discord messages for a tournament."""
    err = _check_internal_auth(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return aiohttp.web.json_response({"error": "Invalid JSON"}, status=400)

    tournament_id = body.get("tournament_id")
    if not isinstance(tournament_id, int):
        return aiohttp.web.json_response(
            {"error": "tournament_id required (integer)"},
            status=400,
        )

    bot = request.app["bot"]
    from bot.models.base import get_async_session

    async for session in get_async_session():
        t = await session.get(Tournament, tournament_id)
        if not t:
            return aiohttp.web.json_response(
                {"error": "Tournament not found"}, status=404
            )
        deleted = await _delete_tournament_messages(
            bot, session, tournament_id, include_results=True
        )
        await session.commit()
        return aiohttp.web.json_response({"ok": True, "deleted": deleted})
    return aiohttp.web.json_response({"error": "Internal error"}, status=500)


def _build_tournament_begins_embed(t: Tournament) -> discord.Embed:
    """Build standalone embed for tournament begins announcement."""
    dt = t.starts_at
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ts = int(dt.timestamp())
    embed = discord.Embed(
        title=f"⏰ {t.name} begins",
        description=f"**Tournament begins:** <t:{ts}:F> (<t:{ts}:R>)",
        color=discord.Color.blue(),
    )
    embed.timestamp = discord.utils.utcnow()
    return embed


async def _handle_post_tournament_begins(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST /internal/post-tournament-begins - Post standalone tournament begins message to Discord."""
    err = _check_internal_auth(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return aiohttp.web.json_response({"error": "Invalid JSON"}, status=400)

    tournament_id = body.get("tournament_id")
    channel_id = body.get("channel_id")
    guild_id = body.get("guild_id")
    if not all(isinstance(x, int) for x in (tournament_id, channel_id, guild_id)):
        return aiohttp.web.json_response(
            {"error": "tournament_id, channel_id, guild_id required (integers)"},
            status=400,
        )

    bot = request.app["bot"]
    from bot.models.base import get_async_session

    async for session in get_async_session():
        t = await session.get(Tournament, tournament_id)
        if not t:
            return aiohttp.web.json_response(
                {"error": "Tournament not found"}, status=404
            )
        if not t.starts_at:
            return aiohttp.web.json_response(
                {"error": "Tournament has no start time. Set it in Set times first."},
                status=400,
            )
        embed = _build_tournament_begins_embed(t)
        try:
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        except Exception as e:
            logger.exception("Failed to fetch channel %s", channel_id)
            return aiohttp.web.json_response(
                {"error": f"Failed to fetch channel: {e}"}, status=400
            )
        if not channel or channel.guild.id != guild_id:
            return aiohttp.web.json_response(
                {"error": "Channel not found or wrong guild"}, status=400
            )
        try:
            msg = await channel.send(embed=embed)
        except Exception as e:
            logger.exception("Failed to post tournament begins")
            return aiohttp.web.json_response(
                {"error": f"Failed to post: {e}. Check bot permissions."},
                status=400,
            )
        session.add(
            TournamentBracketMessage(
                message_id=msg.id,
                channel_id=channel_id,
                guild_id=guild_id,
                tournament_id=tournament_id,
                message_type="begins",
            )
        )
        await session.commit()
        return aiohttp.web.json_response({"ok": True, "message_id": msg.id})
    return aiohttp.web.json_response({"error": "Internal error"}, status=500)


async def _handle_post_bracket(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST /internal/post-bracket - Post current round lineup embed (same as /bracket post)."""
    err = _check_internal_auth(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return aiohttp.web.json_response({"error": "Invalid JSON"}, status=400)

    tournament_id = body.get("tournament_id")
    channel_id = body.get("channel_id")
    guild_id = body.get("guild_id")
    if not all(isinstance(x, int) for x in (tournament_id, channel_id, guild_id)):
        return aiohttp.web.json_response(
            {"error": "tournament_id, channel_id, guild_id required (integers)"},
            status=400,
        )

    bot = request.app["bot"]
    from bot.models.base import get_async_session

    async for session in get_async_session():
        t = await session.get(Tournament, tournament_id)
        if not t:
            return aiohttp.web.json_response(
                {"error": "Tournament not found"}, status=404
            )
        bracket_result = await session.execute(
            select(Bracket).where(Bracket.tournament_id == tournament_id)
        )
        bracket = bracket_result.scalar_one_or_none()
        if not bracket:
            return aiohttp.web.json_response(
                {"error": "No bracket found"}, status=404
            )
        is_team = t.format != "1v1"
        guild = bot.get_guild(guild_id)
        result = await build_round_lineup_embed(
            session, t, bracket, is_team, guild, bot
        )
        if not result:
            return aiohttp.web.json_response(
                {"error": "All matches complete or no unplayed matches"},
                status=400,
            )
        embeds = result if isinstance(result, list) else [result]

        try:
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        except Exception as e:
            logger.exception("Failed to fetch channel %s", channel_id)
            return aiohttp.web.json_response(
                {"error": f"Failed to fetch channel: {e}"}, status=400
            )
        if not channel or channel.guild.id != guild_id:
            return aiohttp.web.json_response(
                {"error": "Channel not found or wrong guild"}, status=400
            )
        try:
            msg_ids = []
            for embed in embeds:
                msg = await channel.send(embed=embed)
                msg_ids.append(msg.id)
                session.add(
                    TournamentBracketMessage(
                        message_id=msg.id,
                        channel_id=channel_id,
                        guild_id=guild_id,
                        tournament_id=tournament_id,
                        message_type="round",
                    )
                )
            await session.commit()
        except Exception as e:
            logger.exception("Failed to post bracket")
            return aiohttp.web.json_response(
                {"error": f"Failed to post: {e}. Check bot permissions."},
                status=400,
            )
        return aiohttp.web.json_response({"ok": True, "message_id": msg_ids[0] if msg_ids else None, "message_ids": msg_ids})
    return aiohttp.web.json_response({"error": "Internal error"}, status=500)


async def _handle_post_teams(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST /internal/post-teams - Post teams/participants embed (for assembly before round 1)."""
    err = _check_internal_auth(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return aiohttp.web.json_response({"error": "Invalid JSON"}, status=400)

    tournament_id = body.get("tournament_id")
    channel_id = body.get("channel_id")
    guild_id = body.get("guild_id")
    if not all(isinstance(x, int) for x in (tournament_id, channel_id, guild_id)):
        return aiohttp.web.json_response(
            {"error": "tournament_id, channel_id, guild_id required (integers)"},
            status=400,
        )

    bot = request.app["bot"]
    from bot.models.base import get_async_session

    async for session in get_async_session():
        t = await session.get(Tournament, tournament_id)
        if not t:
            return aiohttp.web.json_response(
                {"error": "Tournament not found"}, status=404
            )
        is_team = t.format != "1v1"
        guild = bot.get_guild(guild_id)
        embed = await build_teams_embed(session, t, is_team, guild, bot)

        try:
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        except Exception as e:
            logger.exception("Failed to fetch channel %s", channel_id)
            return aiohttp.web.json_response(
                {"error": f"Failed to fetch channel: {e}"}, status=400
            )
        if not channel or channel.guild.id != guild_id:
            return aiohttp.web.json_response(
                {"error": "Channel not found or wrong guild"}, status=400
            )
        try:
            msg = await channel.send(embed=embed)
        except Exception as e:
            logger.exception("Failed to post teams")
            return aiohttp.web.json_response(
                {"error": f"Failed to post: {e}. Check bot permissions."},
                status=400,
            )
        session.add(
            TournamentBracketMessage(
                message_id=msg.id,
                channel_id=channel_id,
                guild_id=guild_id,
                tournament_id=tournament_id,
                message_type="teams",
            )
        )
        await session.commit()
        return aiohttp.web.json_response({"ok": True, "message_id": msg.id})
    return aiohttp.web.json_response({"error": "Internal error"}, status=500)


async def _handle_post_roster(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST /internal/post-roster - Post full roster of everyone signed up."""
    err = _check_internal_auth(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return aiohttp.web.json_response({"error": "Invalid JSON"}, status=400)

    tournament_id = body.get("tournament_id")
    channel_id = body.get("channel_id")
    guild_id = body.get("guild_id")
    if not all(isinstance(x, int) for x in (tournament_id, channel_id, guild_id)):
        return aiohttp.web.json_response(
            {"error": "tournament_id, channel_id, guild_id required (integers)"},
            status=400,
        )

    bot = request.app["bot"]
    from bot.models.base import get_async_session

    async for session in get_async_session():
        t = await session.get(Tournament, tournament_id)
        if not t:
            return aiohttp.web.json_response(
                {"error": "Tournament not found"}, status=404
            )
        guild = bot.get_guild(guild_id)
        embed = await build_roster_embed(session, t, guild, bot)

        try:
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        except Exception as e:
            logger.exception("Failed to fetch channel %s", channel_id)
            return aiohttp.web.json_response(
                {"error": f"Failed to fetch channel: {e}"}, status=400
            )
        if not channel or channel.guild.id != guild_id:
            return aiohttp.web.json_response(
                {"error": "Channel not found or wrong guild"}, status=400
            )
        try:
            msg = await channel.send(embed=embed)
        except Exception as e:
            logger.exception("Failed to post roster")
            return aiohttp.web.json_response(
                {"error": f"Failed to post: {e}. Check bot permissions."},
                status=400,
            )
        session.add(
            TournamentBracketMessage(
                message_id=msg.id,
                channel_id=channel_id,
                guild_id=guild_id,
                tournament_id=tournament_id,
                message_type="roster",
            )
        )
        await session.commit()
        return aiohttp.web.json_response({"ok": True, "message_id": msg.id})
    return aiohttp.web.json_response({"error": "Internal error"}, status=500)


async def _handle_get_guilds(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """GET /internal/discord/guilds - List guilds the bot is in."""
    err = _check_internal_auth(request)
    if err:
        return err
    bot = request.app["bot"]
    guilds = [{"id": str(g.id), "name": g.name} for g in bot.guilds]
    return aiohttp.web.json_response({"guilds": guilds})


async def _handle_invite_url(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """GET /internal/discord/invite-url - Bot invite URL with correct bot scope."""
    err = _check_internal_auth(request)
    if err:
        return err
    bot = request.app["bot"]
    app_id = getattr(bot, "application_id", None)
    if not app_id:
        return aiohttp.web.json_response({"error": "Bot not ready"}, status=503)
    permissions = "277025508360"
    url = f"https://discord.com/api/oauth2/authorize?client_id={app_id}&permissions={permissions}&scope=bot%20applications.commands"
    return aiohttp.web.json_response({"url": url})


async def _handle_has_mod(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """GET /internal/discord/guilds/{guild_id}/members/{user_id}/has-mod - Check if user has mod role."""
    err = _check_internal_auth(request)
    if err:
        return err
    try:
        guild_id = int(request.match_info["guild_id"])
        user_id = int(request.match_info["user_id"])
    except (ValueError, KeyError):
        return aiohttp.web.json_response({"error": "Invalid guild_id or user_id"}, status=400)
    bot = request.app["bot"]
    guild = bot.get_guild(guild_id)
    if not guild:
        return aiohttp.web.json_response({"error": "Guild not found"}, status=404)
    from bot.checks import user_has_admin_in_guild, user_has_mod_in_guild
    has_mod = await user_has_mod_in_guild(guild, user_id, client=bot)
    has_admin = await user_has_admin_in_guild(guild, user_id, client=bot)
    return aiohttp.web.json_response({"has_mod": has_mod, "has_admin": has_admin})


async def _handle_get_channels(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """GET /internal/discord/guilds/{guild_id}/channels - List text channels."""
    err = _check_internal_auth(request)
    if err:
        return err
    try:
        guild_id = int(request.match_info["guild_id"])
    except (ValueError, KeyError):
        return aiohttp.web.json_response(
            {"error": "Invalid guild_id"}, status=400
        )
    bot = request.app["bot"]
    guild = bot.get_guild(guild_id)
    if not guild:
        return aiohttp.web.json_response({"error": "Guild not found"}, status=404)
    channels = []
    for ch in guild.text_channels:
        perms = ch.permissions_for(guild.me)
        if perms.send_messages and perms.embed_links:
            parent = ch.category.name if ch.category else ""

            channels.append(
                {"id": str(ch.id), "name": ch.name, "parent_name": parent}
            )
    return aiohttp.web.json_response({"channels": channels})


def create_app(bot) -> aiohttp.web.Application:
    """Create aiohttp app with bot reference."""
    app = aiohttp.web.Application()
    app["bot"] = bot
    app.router.add_post("/internal/post-signup", _handle_post_signup)
    app.router.add_post("/internal/post-results", _handle_post_results)
    app.router.add_post("/internal/cleanup-messages", _handle_cleanup_messages)
    app.router.add_post("/internal/post-tournament-begins", _handle_post_tournament_begins)
    app.router.add_post("/internal/post-bracket", _handle_post_bracket)
    app.router.add_post("/internal/post-teams", _handle_post_teams)
    app.router.add_post("/internal/post-roster", _handle_post_roster)
    app.router.add_post("/internal/refresh-players", _handle_refresh_players)
    app.router.add_get("/internal/discord/guilds", _handle_get_guilds)
    app.router.add_get("/internal/discord/invite-url", _handle_invite_url)
    app.router.add_get(
        "/internal/discord/guilds/{guild_id}/channels", _handle_get_channels
    )
    app.router.add_get(
        "/internal/discord/guilds/{guild_id}/members/{user_id}/has-mod", _handle_has_mod
    )
    return app


async def start_http_server(bot, host: str = "0.0.0.0", port: int = 8001) -> None:
    """Start the internal HTTP server (run as a task alongside the bot)."""
    if not config.INTERNAL_API_SECRET:
        logger.info("INTERNAL_API_SECRET not set - skipping internal HTTP server")
        return
    app = create_app(bot)
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, host, port)
    await site.start()
    logger.info("Internal HTTP server listening on %s:%d", host, port)
