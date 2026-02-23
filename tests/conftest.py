"""Pytest configuration and fixtures for API tests."""
import os

# Set test env BEFORE any imports that use config
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["INITIAL_ADMIN_PASSWORD"] = "testpass123"
os.environ["INITIAL_ADMIN_USERNAME"] = "admin"

import pytest
from httpx import ASGITransport, AsyncClient

from bot.models.base import init_db
from web.api.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
async def _init_db():
    """Ensure database tables exist before each test (ASGI lifespan doesn't run with httpx)."""
    await init_db()


@pytest.fixture
async def client():
    """Async HTTP client for testing the API."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture
async def auth_headers(client):
    """Login as admin and return Authorization headers for protected endpoints."""
    r = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "testpass123"},
    )
    assert r.status_code == 200, f"Login failed: {r.text}"
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
