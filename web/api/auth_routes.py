"""Auth API routes: login, current user, user management."""
from __future__ import annotations

from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, select

import config
from bot.models import GuildConfig, GuildModerator, User
from bot.models.base import async_session_factory
from web.auth import (
    create_access_token,
    get_current_user,
    get_user_by_username,
    hash_password,
    is_global_admin,
    promote_guild_moderator_if_needed,
    require_global_admin_user,
    require_user,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str


class UserResponse(BaseModel):
    username: str
    role: str
    is_global_admin: bool = False


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "user"  # user, moderator, admin


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    """Authenticate and return JWT."""
    user = await get_user_by_username(body.username)
    if not user:
        # Bootstrap: if INITIAL_ADMIN_PASSWORD is set and matches, create admin
        if (
            config.INITIAL_ADMIN_PASSWORD
            and body.username == config.INITIAL_ADMIN_USERNAME
            and body.password == config.INITIAL_ADMIN_PASSWORD
        ):
            async with async_session_factory() as session:
                user = User(
                    username=config.INITIAL_ADMIN_USERNAME,
                    password_hash=hash_password(config.INITIAL_ADMIN_PASSWORD),
                    role="admin",
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)
                token = create_access_token(user.username, user.role)
                return LoginResponse(access_token=token, username=user.username, role=user.role)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token(user.username, user.role)
    return LoginResponse(access_token=token, username=user.username, role=user.role)


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(require_user)):
    """Get current authenticated user."""
    user = await promote_guild_moderator_if_needed(user)
    return UserResponse(username=user.username, role=user.role, is_global_admin=is_global_admin(user))


@router.get("/me/optional")
async def get_me_optional(user: Optional[User] = Depends(get_current_user)):
    """Get current user if logged in, else null. For frontend auth check."""
    if not user:
        return None
    user = await promote_guild_moderator_if_needed(user)
    return {"username": user.username, "role": user.role, "is_global_admin": is_global_admin(user)}


@router.get("/my-guilds")
async def get_my_guilds(user: User = Depends(require_user)):
    """List guilds the current user can moderate. Verifies with Discord and removes stale GuildModerator entries."""
    user = await promote_guild_moderator_if_needed(user)
    headers = {"Authorization": f"Bearer {config.INTERNAL_API_SECRET}"} if config.INTERNAL_API_SECRET else {}

    # Global admin/moderator: return all guilds the bot is in
    if user.role in ("admin", "moderator"):
        if not config.BOT_INTERNAL_URL or not headers:
            return {"guilds": []}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    f"{config.BOT_INTERNAL_URL.rstrip('/')}/internal/discord/guilds",
                    headers=headers,
                )
            if r.status_code != 200:
                return {"guilds": []}
            data = r.json()
            return {"guilds": [{"guild_id": int(g["id"]), "name": g["name"], "slug": None} for g in data.get("guilds", [])]}
        except Exception:
            return {"guilds": []}

    # Guild-scoped: get GuildModerator rows, verify each with bot, remove stale
    if not user.discord_id:
        return {"guilds": []}
    if not config.BOT_INTERNAL_URL or not headers:
        # No bot: return GuildModerator guilds without verification
        async with async_session_factory() as session:
            result = await session.execute(
                select(GuildModerator, GuildConfig)
                .outerjoin(GuildConfig, GuildConfig.guild_id == GuildModerator.guild_id)
                .where(GuildModerator.user_id == user.id)
            )
            rows = result.all()
            return {"guilds": [{"guild_id": gm.guild_id, "name": gc.name if gc else str(gm.guild_id), "slug": gc.slug if gc else None} for gm, gc in rows]}

    guilds = []
    async with async_session_factory() as session:
        result = await session.execute(
            select(GuildModerator).where(GuildModerator.user_id == user.id)
        )
        mod_rows = result.scalars().all()
        for gm in mod_rows:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.get(
                        f"{config.BOT_INTERNAL_URL.rstrip('/')}/internal/discord/guilds/{gm.guild_id}/members/{user.discord_id}/has-mod",
                        headers=headers,
                    )
                if r.status_code != 200:
                    continue
                data = r.json()
                if not data.get("has_mod"):
                    # User no longer has mod role - remove GuildModerator
                    await session.execute(delete(GuildModerator).where(GuildModerator.id == gm.id))
                    continue
            except Exception:
                continue
            gc_result = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == gm.guild_id))
            gc = gc_result.scalar_one_or_none()
            guilds.append({"guild_id": gm.guild_id, "name": gc.name if gc else str(gm.guild_id), "slug": gc.slug if gc else None})
        await session.commit()
    return {"guilds": guilds}


@router.get("/users", response_model=list[UserResponse])
async def list_users(admin: User = Depends(require_global_admin_user)):
    """List all users (admin only)."""
    async with async_session_factory() as session:
        result = await session.execute(select(User).order_by(User.username))
        users = result.scalars().all()
        return [UserResponse(username=u.username, role=u.role, is_global_admin=is_global_admin(u)) for u in users]


@router.post("/users", response_model=UserResponse)
async def create_user(body: CreateUserRequest, admin: User = Depends(require_global_admin_user)):
    """Create a new user (admin only)."""
    if body.role not in ("user", "moderator", "admin"):
        raise HTTPException(400, "Invalid role")
    async with async_session_factory() as session:
        existing = await session.execute(select(User).where(User.username == body.username))
        if existing.scalar_one_or_none():
            raise HTTPException(400, "Username already exists")
        user = User(
            username=body.username,
            password_hash=hash_password(body.password),
            role=body.role,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return UserResponse(username=user.username, role=user.role, is_global_admin=is_global_admin(user))


class UpdateUserRequest(BaseModel):
    password: Optional[str] = None
    role: Optional[str] = None


@router.patch("/users/{username}")
async def update_user(username: str, body: UpdateUserRequest, admin: User = Depends(require_global_admin_user)):
    """Update user password or role (admin only)."""
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(404, "User not found")
        if body.password is not None:
            user.password_hash = hash_password(body.password)
        if body.role is not None:
            if body.role not in ("user", "moderator", "admin"):
                raise HTTPException(400, "Invalid role")
            user.role = body.role
        await session.commit()
        return {"ok": True}


@router.delete("/users/{username}")
async def delete_user(username: str, admin: User = Depends(require_global_admin_user)):
    """Delete a user (admin only). Cannot delete self."""
    if username == admin.username:
        raise HTTPException(400, "Cannot delete your own account")
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(404, "User not found")
        await session.delete(user)
        await session.commit()
        return {"ok": True}
