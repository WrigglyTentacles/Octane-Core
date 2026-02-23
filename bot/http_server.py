"""Internal HTTP server for web-triggered Discord actions (e.g. post signup)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiohttp.web
import discord
from sqlalchemy import delete as sql_delete, select

import config
from bot.models import Registration, Tournament, TournamentSignupMessage

logger = logging.getLogger("octane.http")

SIGNUP_EMOJI = "📝"


def _build_signup_embed(t: Tournament, count: int) -> discord.Embed:
    """Build signup embed (same as tournaments cog)."""
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
        embed_dict = _build_signup_embed(t, count)

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
            msg = await channel.send(embed=embed)
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


def create_app(bot) -> aiohttp.web.Application:
    """Create aiohttp app with bot reference."""
    app = aiohttp.web.Application()
    app["bot"] = bot
    app.router.add_post("/internal/post-signup", _handle_post_signup)
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
