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
from bot.models import User
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
    """Dependency: require logged-in moderator or admin."""
    return require_moderator(user)


async def require_admin_user(
    user: User = Depends(require_user),
) -> User:
    """Dependency: require logged-in admin."""
    return require_admin(user)
