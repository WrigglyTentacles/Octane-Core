"""Registration cog - /register, /profile, /update_epic."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import discord
from discord import app_commands

from bot.models import Player, init_db
from bot.models.base import get_async_session
from bot.services.rl_api import RLAPIService
import config


async def get_player(session: AsyncSession, discord_id: int) -> Optional[Player]:
    """Get player by Discord ID."""
    result = await session.execute(select(Player).where(Player.discord_id == discord_id))
    return result.scalar_one_or_none()


@app_commands.command(description="Link your Epic Account ID to your Discord account")
@app_commands.describe(epic_id="Your Epic Account ID (32-character hex)")
async def register(interaction: discord.Interaction, epic_id: str) -> None:
    epic_id = epic_id.strip().lower()
    if len(epic_id) != 32 or not all(c in "0123456789abcdef" for c in epic_id):
        await interaction.response.send_message(
            "Invalid Epic ID. It should be a 32-character hexadecimal string.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    display_name = interaction.user.display_name or str(interaction.user)
    async for session in get_async_session():
        await init_db()
        existing = await get_player(session, interaction.user.id)
        if existing:
            existing.epic_id = epic_id
            existing.display_name = display_name
        else:
            session.add(
                Player(
                    discord_id=interaction.user.id,
                    epic_id=epic_id,
                    display_name=display_name,
                )
            )
        await session.commit()
        break

    await interaction.followup.send(
        f"Successfully linked Epic ID `{epic_id}` to your account.",
        ephemeral=True,
    )


@app_commands.command(description="View your linked Epic ID and MMR")
async def profile(interaction: discord.Interaction) -> None:
    """Show profile with Epic ID and MMR."""
    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        player = await get_player(session, interaction.user.id)
        if not player:
            await interaction.followup.send(
                "You haven't registered yet. Use `/register epic_id` to link your Epic ID.",
                ephemeral=True,
            )
            return

        # Fetch fresh MMR from API
        rl_service = RLAPIService(config.RLAPI_CLIENT_ID, config.RLAPI_CLIENT_SECRET)
        try:
            player_data = await rl_service.get_player_by_epic_id(player.epic_id)
            if player_data:
                mmr_info = rl_service.get_playlist_mmr(player_data, "doubles")
                mmr_str = f"Doubles: {mmr_info[1]} ({mmr_info[0]} MMR)" if mmr_info else "No ranked data"
            else:
                mmr_str = "Could not fetch MMR"
        finally:
            await rl_service.close()

        embed = discord.Embed(
            title="Your Profile",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Epic ID", value=f"`{player.epic_id}`", inline=False)
        embed.add_field(name="Display Name", value=player.display_name or "—", inline=False)
        embed.add_field(name="MMR (Doubles)", value=mmr_str, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return


@app_commands.command(description="Update your linked Epic ID")
@app_commands.describe(epic_id="Your new Epic Account ID (32-character hex)")
async def update_epic(interaction: discord.Interaction, epic_id: str) -> None:
    """Update Epic ID."""
    epic_id = epic_id.strip().lower()
    if len(epic_id) != 32 or not all(c in "0123456789abcdef" for c in epic_id):
        await interaction.response.send_message(
            "Invalid Epic ID. It should be a 32-character hexadecimal string.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    async for session in get_async_session():
        player = await get_player(session, interaction.user.id)
        if not player:
            await interaction.followup.send(
                "You haven't registered yet. Use `/register epic_id` to link your Epic ID.",
                ephemeral=True,
            )
            return
        player.epic_id = epic_id
        player.display_name = interaction.user.display_name or str(interaction.user)
        await session.commit()
        break

    await interaction.followup.send(
        f"Successfully updated your Epic ID to `{epic_id}`.",
        ephemeral=True,
    )
