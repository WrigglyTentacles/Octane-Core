"""Authentication for web API: JWT, password hashing, role checks.

Site hierarchy:
- Global site admin: Full access (site settings, user management, all guilds). User.role=admin or GLOBAL_ADMIN_USERNAMES.
- Guild admin: Edit guild settings (theme, Discord channels). GuildModerator.role=admin for that guild.
- Guild moderator: Edit brackets, create/delete tournaments, backup/restore. No guild settings. GuildModerator.role=moderator.
- Guild user: Read-only access to brackets. No GuildModerator entry for that guild.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import config
from bot.models import GuildModerator, Tournament, User
from bot.models.base import async_session_factory

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
http_bearer = HTTPBearer(auto_error=False)


def _prepare_password(password: str) -> str:
    """Bcrypt has a 72-byte limit. Pre-hash longer passwords with SHA256."""
    encoded = password.encode("utf-8")
    if len(encoded) > 72:
        return hashlib.sha256(encoded).hexdigest()
    return password


def hash_password(password: str) -> str:
    return pwd_context.hash(_prepare_password(password))


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(_prepare_password(plain), hashed)


def create_access_token(username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=config.JWT_EXPIRE_DAYS)
    payload = {"sub": username, "role": role, "exp": expire}
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        return None


async def get_user_by_username(username: str) -> Optional[User]:
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()


async def get_user_by_discord_id(discord_id: int) -> Optional[User]:
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.discord_id == discord_id))
        return result.scalar_one_or_none()


async def claim_guild_moderator(
    discord_id: int, guild_id: int, role: str = "moderator"
) -> User:
    """Create or link User by discord_id, add GuildModerator. Used by magic link and future OAuth."""
    async with async_session_factory() as session:
        user = await session.execute(select(User).where(User.discord_id == discord_id))
        user = user.scalar_one_or_none()
        if not user:
            username = f"discord_{discord_id}"
            user = User(
                username=username,
                password_hash="",  # No password; Discord-linked
                role="user",
                discord_id=discord_id,
            )
            session.add(user)
            await session.flush()
        existing = await session.execute(
            select(GuildModerator).where(
                GuildModerator.user_id == user.id, GuildModerator.guild_id == guild_id
            )
        )
        if not existing.scalar_one_or_none():
            session.add(
                GuildModerator(user_id=user.id, guild_id=guild_id, role=role)
            )
        await session.commit()
        await session.refresh(user)
        return user


async def claim_guild_moderator_with_credentials(
    discord_id: int, guild_id: int, username: str, password: str, role: str = "moderator"
) -> User:
    """Create or update User with username/password linked to discord_id, add GuildModerator."""
    username = username.strip()
    if not username or len(username) < 2:
        raise ValueError("Username must be at least 2 characters")
    if not password or len(password) < 6:
        raise ValueError("Password must be at least 6 characters")

    async with async_session_factory() as session:
        existing_by_discord = await session.execute(select(User).where(User.discord_id == discord_id))
        user = existing_by_discord.scalar_one_or_none()
        existing_by_username = await session.execute(select(User).where(User.username == username))
        other_user = existing_by_username.scalar_one_or_none()

        if user:
            # Update existing user - username must not be taken by someone else
            if other_user and other_user.id != user.id:
                raise ValueError("Username already taken")
            user.username = username
            user.password_hash = hash_password(password)
            # Upgrade to moderator for canEdit (never set admin - that's global only)
            if user.role == "user":
                user.role = "moderator"
        else:
            # New user - username must be unique. Guild-scoped users get moderator (not admin)
            if other_user:
                raise ValueError("Username already taken")
            user = User(
                username=username,
                password_hash=hash_password(password),
                role="moderator",  # Guild-scoped; GuildModerator.role = admin or moderator
                discord_id=discord_id,
            )
            session.add(user)
            await session.flush()

        gm = await session.execute(
            select(GuildModerator).where(
                GuildModerator.user_id == user.id, GuildModerator.guild_id == guild_id
            )
        )
        if not gm.scalar_one_or_none():
            session.add(GuildModerator(user_id=user.id, guild_id=guild_id, role=role))
        await session.commit()
        await session.refresh(user)
        return user


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer),
    x_auth_token: Optional[str] = Header(None, alias="X-Auth-Token"),
) -> Optional[User]:
    """Return current user from JWT, or None if not authenticated. Accepts Authorization: Bearer or X-Auth-Token (fallback for proxies that strip Authorization)."""
    token = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    elif x_auth_token:
        token = x_auth_token
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    username = payload.get("sub")
    if not username:
        return None
    user = await get_user_by_username(username)
    if not user:
        return None
    return user


async def promote_guild_moderator_if_needed(user: User) -> User:
    """If user has role=user but GuildModerator exists, upgrade to moderator (for existing registrations)."""
    if user.role != "user":
        return user
    async with async_session_factory() as session:
        result = await session.execute(
            select(GuildModerator).where(GuildModerator.user_id == user.id)
        )
        if result.scalar_one_or_none():
            await session.execute(update(User).where(User.id == user.id).values(role="moderator"))
            await session.commit()
            user.role = "moderator"
    return user


async def require_user(
    user: Optional[User] = Depends(get_current_user),
) -> User:
    """Require authenticated user. Raises 401 if not logged in."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_user_or_guild_tournament(
    tournament_id: int,
    user: Optional[User] = Depends(get_current_user),
) -> Optional[User]:
    """Allow unauthenticated access for guild tournaments (guild_id != 0). Require auth for global (guild_id=0)."""
    async with async_session_factory() as session:
        t = await session.get(Tournament, tournament_id)
    if not t:
        raise HTTPException(404, "Tournament not found")
    if t.guild_id and t.guild_id != 0:
        return user  # Guild tournament: public, user can be None
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_moderator(user: User) -> User:
    """Require moderator or admin role. Raises 403 if insufficient."""
    if user.role not in ("moderator", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Moderator access required")
    return user


def require_admin(user: User) -> User:
    """Require admin role. Raises 403 if insufficient."""
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


def is_global_admin(user: User) -> bool:
    """True if user is a global (site-wide) admin: User.role=admin or in GLOBAL_ADMIN_USERNAMES."""
    if user.role == "admin":
        return True
    return user.username.lower() in config.GLOBAL_ADMIN_USERNAMES


async def require_moderator_user(
    user: User = Depends(require_user),
) -> User:
    """Dependency: require logged-in moderator or admin (global)."""
    return require_moderator(user)


async def check_moderator_for_guild(guild_id: int, user: User) -> None:
    """Raise 403 if user cannot moderate this guild. Used by dependencies."""
    if is_global_admin(user):
        return
    async with async_session_factory() as session:
        result = await session.execute(
            select(GuildModerator).where(
                GuildModerator.user_id == user.id,
                GuildModerator.guild_id == guild_id,
            )
        )
        gm = result.scalar_one_or_none()
        if gm and gm.role in ("moderator", "admin"):
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Moderator access required for this server",
    )


async def require_moderator_for_tournament(
    tournament_id: int,
    user: User = Depends(require_user),
) -> User:
    """Require user can moderate this tournament (global admin OR guild moderator/admin for tournament's guild)."""
    async with async_session_factory() as session:
        t = await session.get(Tournament, tournament_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
    if t.guild_id and t.guild_id != 0:
        await check_moderator_for_guild(t.guild_id, user)
        return user
    return require_moderator(user)


async def require_moderator_for_guild(
    guild_id: int,
    user: User = Depends(require_user),
) -> User:
    """Dependency: require user can moderate this guild (global admin OR GuildModerator)."""
    await check_moderator_for_guild(guild_id, user)
    return user


async def require_guild_admin(
    guild_id: int,
    user: User = Depends(require_user),
) -> User:
    """Dependency: require user is guild admin or global admin (for guild settings)."""
    if is_global_admin(user):
        return user
    async with async_session_factory() as session:
        result = await session.execute(
            select(GuildModerator).where(
                GuildModerator.user_id == user.id,
                GuildModerator.guild_id == guild_id,
            )
        )
        gm = result.scalar_one_or_none()
        if gm and gm.role == "admin":
            return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Guild admin access required",
    )


async def require_admin_user(
    user: User = Depends(require_user),
) -> User:
    """Dependency: require logged-in admin (legacy alias)."""
    return require_admin(user)


async def require_global_admin_user(
    user: User = Depends(require_user),
) -> User:
    """Dependency: require logged-in global (site-wide) admin."""
    if not is_global_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Global admin access required",
        )
    return user
