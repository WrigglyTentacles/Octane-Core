"""Database base and session setup."""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

import config


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


engine = create_async_engine(
    config.DATABASE_URL,
    echo=False,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_async_session():
    """Async generator yielding database sessions. Use: async for session in get_async_session(): ..."""
    async with async_session_factory() as session:
        yield session


# Migrations for existing databases
_MIGRATIONS = [
    "ALTER TABLE players ADD COLUMN epic_username VARCHAR(64)",
    # Make epic_id nullable (SQLite requires table recreation)
    "CREATE TABLE players_new (discord_id INTEGER NOT NULL PRIMARY KEY, display_name VARCHAR(128), epic_username VARCHAR(64), epic_id VARCHAR(32))",
    "INSERT INTO players_new SELECT discord_id, display_name, epic_username, epic_id FROM players",
    "DROP TABLE players",
    "ALTER TABLE players_new RENAME TO players",
    "CREATE UNIQUE INDEX ix_players_epic_id ON players(epic_id)",
    "CREATE TABLE IF NOT EXISTS tournament_signup_messages (id INTEGER PRIMARY KEY, message_id INTEGER UNIQUE, channel_id INTEGER, guild_id INTEGER, tournament_id INTEGER REFERENCES tournaments(id), signup_emoji VARCHAR(32) DEFAULT '📝')",
    "ALTER TABLE bracket_matches ADD COLUMN manual_entry1_id INTEGER REFERENCES tournament_manual_entries(id)",
    "ALTER TABLE bracket_matches ADD COLUMN manual_entry2_id INTEGER REFERENCES tournament_manual_entries(id)",
    "ALTER TABLE bracket_matches ADD COLUMN winner_manual_entry_id INTEGER REFERENCES tournament_manual_entries(id)",
    "ALTER TABLE bracket_matches ADD COLUMN bracket_section VARCHAR(16)",
    "ALTER TABLE bracket_matches ADD COLUMN loser_advances_to_match_id INTEGER REFERENCES bracket_matches(id)",
    "ALTER TABLE bracket_matches ADD COLUMN loser_advances_to_slot INTEGER",
    "ALTER TABLE tournament_manual_entries ADD COLUMN original_list_type VARCHAR(16)",
    "UPDATE tournament_manual_entries SET original_list_type = list_type WHERE original_list_type IS NULL",
    "ALTER TABLE tournaments ADD COLUMN archived INTEGER DEFAULT 0",
    # Recover from failed migration: ensure players table exists (e.g. if DROP succeeded but RENAME failed)
    "CREATE TABLE IF NOT EXISTS players (discord_id INTEGER NOT NULL PRIMARY KEY, display_name VARCHAR(128), epic_username VARCHAR(64), epic_id VARCHAR(32))",
    # Multi-server: guild_config, guild_moderators, registration_tokens, User.discord_id
    "CREATE TABLE IF NOT EXISTS guild_config (guild_id INTEGER NOT NULL PRIMARY KEY, slug VARCHAR(64), name VARCHAR(128), discord_signup_channel_id INTEGER, discord_bracket_channel_id INTEGER)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_guild_config_slug ON guild_config(slug)",
    "CREATE TABLE IF NOT EXISTS guild_moderators (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE, guild_id INTEGER NOT NULL, role VARCHAR(16) DEFAULT 'moderator')",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_guild_moderator_user_guild ON guild_moderators(user_id, guild_id)",
    "CREATE TABLE IF NOT EXISTS registration_tokens (id INTEGER PRIMARY KEY AUTOINCREMENT, token VARCHAR(64) NOT NULL UNIQUE, discord_user_id INTEGER NOT NULL, guild_id INTEGER NOT NULL, expires_at DATETIME NOT NULL)",
    "CREATE INDEX IF NOT EXISTS ix_registration_tokens_token ON registration_tokens(token)",
    "ALTER TABLE registration_tokens ADD COLUMN discord_role VARCHAR(16) DEFAULT 'moderator'",
    "ALTER TABLE guild_config ADD COLUMN site_title VARCHAR(128)",
    "ALTER TABLE guild_config ADD COLUMN accent_color VARCHAR(32)",
    "ALTER TABLE guild_config ADD COLUMN accent_hover VARCHAR(32)",
    "ALTER TABLE guild_config ADD COLUMN bg_primary VARCHAR(32)",
    "ALTER TABLE guild_config ADD COLUMN bg_secondary VARCHAR(32)",
    "ALTER TABLE guild_config ADD COLUMN discord_signup_channel_name VARCHAR(128)",
    "ALTER TABLE guild_config ADD COLUMN discord_bracket_channel_name VARCHAR(128)",
    "ALTER TABLE web_users ADD COLUMN discord_id INTEGER",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_web_users_discord_id ON web_users(discord_id)",
    "CREATE TABLE IF NOT EXISTS tournament_bracket_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, message_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, guild_id INTEGER NOT NULL, tournament_id INTEGER NOT NULL REFERENCES tournaments(id), message_type VARCHAR(16) NOT NULL)",
    "CREATE INDEX IF NOT EXISTS ix_tournament_bracket_messages_tournament ON tournament_bracket_messages(tournament_id)",
    "ALTER TABLE tournaments ADD COLUMN starts_at DATETIME",
]


async def _run_migrations(conn) -> None:
    """Add new columns if they don't exist."""
    for sql in _MIGRATIONS:
        try:
            await conn.execute(text(sql))
        except Exception:
            pass  # Column likely already exists


async def init_db() -> None:
    """Create all tables and run migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)
