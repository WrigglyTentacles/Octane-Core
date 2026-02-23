"""Auth API routes: login, current user, user management."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

import config
from bot.models import User
from bot.models.base import async_session_factory
from web.auth import (
    create_access_token,
    get_current_user,
    get_user_by_username,
    hash_password,
    require_admin_user,
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
    return UserResponse(username=user.username, role=user.role)


@router.get("/me/optional")
async def get_me_optional(user: Optional[User] = Depends(get_current_user)):
    """Get current user if logged in, else null. For frontend auth check."""
    if not user:
        return None
    return {"username": user.username, "role": user.role}


@router.get("/users", response_model=list[UserResponse])
async def list_users(admin: User = Depends(require_admin_user)):
    """List all users (admin only)."""
    async with async_session_factory() as session:
        result = await session.execute(select(User).order_by(User.username))
        users = result.scalars().all()
        return [UserResponse(username=u.username, role=u.role) for u in users]


@router.post("/users", response_model=UserResponse)
async def create_user(body: CreateUserRequest, admin: User = Depends(require_admin_user)):
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
        return UserResponse(username=user.username, role=user.role)


class UpdateUserRequest(BaseModel):
    password: Optional[str] = None
    role: Optional[str] = None


@router.patch("/users/{username}")
async def update_user(username: str, body: UpdateUserRequest, admin: User = Depends(require_admin_user)):
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
async def delete_user(username: str, admin: User = Depends(require_admin_user)):
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
