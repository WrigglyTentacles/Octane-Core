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
