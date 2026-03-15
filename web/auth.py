"""Authentication for web API: JWT, password hashing, role checks."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from bot.models import GuildModerator, User
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


async def require_moderator_user(
    user: User = Depends(require_user),
) -> User:
    """Dependency: require logged-in moderator or admin (global)."""
    return require_moderator(user)


async def require_moderator_for_guild(
    guild_id: int,
    user: User = Depends(require_user),
) -> User:
    """Dependency: require user can moderate this guild (global admin OR GuildModerator)."""
    if user.role == "admin":
        return user
    async with async_session_factory() as session:
        result = await session.execute(
            select(GuildModerator).where(
                GuildModerator.user_id == user.id,
                GuildModerator.guild_id == guild_id,
            )
        )
        gm = result.scalar_one_or_none()
        if gm and gm.role in ("moderator", "admin"):
            return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Moderator access required for this server",
    )


async def require_admin_user(
    user: User = Depends(require_user),
) -> User:
    """Dependency: require logged-in admin."""
    return require_admin(user)
