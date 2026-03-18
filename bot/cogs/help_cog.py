"""Help cog - /octane-core help for in-channel help embed."""
from __future__ import annotations

import discord
from discord import app_commands

import config


def _build_help_embed() -> discord.Embed:
    """Build the Octane-Core help embed."""
    embed = discord.Embed(
        title="Octane-Core Help",
        description="Rocket League tournament bot — signups, brackets, and results.",
        color=discord.Color.blue(),
    )
    embed.add_field(
        name="📋 Signing up",
        value=(
            "• React with 📝 on the signup post, or use `/tournament register`\n"
            "• Use `/tournament status` to check your signup status"
        ),
        inline=False,
    )
    embed.add_field(
        name="📊 Bracket commands",
        value=(
            "• `/bracket view` — View the bracket\n"
            "• `/bracket next` — Who you play next\n"
            "• `/bracket status` — Your match status"
        ),
        inline=False,
    )
    embed.add_field(
        name="📝 Other commands",
        value=(
            "• `/tournament list` — List tournaments\n"
            "• `/tournament unregister` — Drop out\n"
            "• `/profile` — Your profile (if Epic linked)"
        ),
        inline=False,
    )
    if config.SITE_URL:
        base = config.SITE_URL.rstrip("/")
        embed.add_field(
            name="🌐 Web",
            value=f"View brackets and brackets at **{base}**",
            inline=False,
        )
    embed.set_footer(text="Moderators: use /octane-core help with moderator: Yes for mod guide")
    embed.timestamp = discord.utils.utcnow()
    return embed


def _build_mod_help_embed() -> discord.Embed:
    """Build the moderator help embed."""
    embed = discord.Embed(
        title="Octane-Core — Moderator Guide",
        description="Commands and workflow for running tournaments.",
        color=discord.Color.green(),
    )
    embed.add_field(
        name="📋 Tournament lifecycle",
        value=(
            "1. `/tournament create` — Create tournament\n"
            "2. `/tournament post` — Post signup\n"
            "3. Add participants (web or Discord signups)\n"
            "4. `/team add` / `remove` (2v2/3v3)\n"
            "5. Generate bracket (web)\n"
            "6. `/bracket post-teams`, `/bracket post` — Post to Discord\n"
            "7. `/bracket update` — Record winners\n"
            "8. `/tournament cleanup` — Remove old messages"
        ),
        inline=False,
    )
    embed.add_field(
        name="📝 Moderator commands",
        value=(
            "• `/tournament post-roster` — Post full signup list\n"
            "• `/tournament edit` — Edit name, status, times\n"
            "• `/bracket generate` — Generate bracket\n"
            "• `/bracket post-teams` — Post teams/participants\n"
            "• `/bracket post` — Post current round\n"
            "• `/tournament set-signup-channel` — Set signup channel"
        ),
        inline=False,
    )
    embed.add_field(
        name="⚙️ Web UI",
        value=(
            "• Hamburger menu: Set times, Post roster, Cleanup, Clone\n"
            "• Bracket tab: Post Teams, Post Round, Post Results\n"
            "• Settings: Discord channels, theme (guild admin)"
        ),
        inline=False,
    )
    embed.set_footer(text="See docs/USER_GUIDE.md and docs/MODERATOR_GUIDE.md for full guides")
    embed.timestamp = discord.utils.utcnow()
    return embed


octane_core_group = app_commands.Group(
    name="octane-core",
    description="Octane-Core bot help and info",
)


@octane_core_group.command(name="help", description="Post help embed in this channel")
@app_commands.describe(
    post="Post in channel for everyone (default: true) or only show to you",
    moderator="Show moderator guide instead of user guide",
)
async def help_cmd(
    interaction: discord.Interaction,
    post: bool = True,
    moderator: bool = False,
) -> None:
    """Post the Octane-Core help embed. Use post=True to pin it in the channel for everyone."""
    if not interaction.guild_id:
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return

    embed = _build_mod_help_embed() if moderator else _build_help_embed()
    ephemeral = not post

    await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
