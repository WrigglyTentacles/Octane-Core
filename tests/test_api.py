"""Tests for basic API functionality."""
import pytest


@pytest.mark.asyncio
async def test_health(client):
    """Health endpoint returns ok."""
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_list_tournaments_empty(client):
    """List tournaments returns empty list initially."""
    r = await client.get("/api/tournaments")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_create_tournament(client):
    """Create tournament returns tournament data (no auth required)."""
    r = await client.post(
        "/api/tournaments",
        json={"name": "Test Cup", "format": "1v1"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Test Cup"
    assert data["format"] == "1v1"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_tournaments_after_create(client):
    """List tournaments returns created tournament."""
    await client.post(
        "/api/tournaments",
        json={"name": "Test Cup", "format": "1v1"},
    )
    r = await client.get("/api/tournaments")
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    names = [t["name"] for t in data]
    assert "Test Cup" in names


@pytest.mark.asyncio
async def test_participants_flow(client, auth_headers):
    """Add participant, list, remove."""
    # Create tournament
    r = await client.post(
        "/api/tournaments",
        json={"name": "Participant Test", "format": "1v1"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    tid = r.json()["id"]

    # List participants (empty)
    r = await client.get(f"/api/tournaments/{tid}/participants")
    assert r.status_code == 200
    assert r.json() == []

    # Add participant (requires auth)
    r = await client.post(
        f"/api/tournaments/{tid}/participants",
        json={"display_name": "Player One"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    p1 = r.json()
    assert p1["display_name"] == "Player One"
    assert p1["list_type"] == "participant"

    # List participants
    r = await client.get(f"/api/tournaments/{tid}/participants")
    assert r.status_code == 200
    parts = r.json()
    assert len(parts) == 1
    assert parts[0]["display_name"] == "Player One"

    # Remove participant
    r = await client.delete(
        f"/api/tournaments/{tid}/participants/{p1['id']}",
        headers=auth_headers,
    )
    assert r.status_code == 200

    # List empty again
    r = await client.get(f"/api/tournaments/{tid}/participants")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_standby_flow(client, auth_headers):
    """Add standby, list."""
    r = await client.post(
        "/api/tournaments",
        json={"name": "Standby Test", "format": "1v1"},
        headers=auth_headers,
    )
    tid = r.json()["id"]

    r = await client.post(
        f"/api/tournaments/{tid}/standby",
        json={"display_name": "Standby One"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["display_name"] == "Standby One"

    r = await client.get(f"/api/tournaments/{tid}/standby")
    assert r.status_code == 200
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_bracket_preview(client, auth_headers):
    """Bracket preview requires 2+ participants."""
    r = await client.post(
        "/api/tournaments",
        json={"name": "Bracket Test", "format": "1v1"},
        headers=auth_headers,
    )
    tid = r.json()["id"]

    # Preview with 0 participants - error
    r = await client.get(f"/api/tournaments/{tid}/bracket/preview")
    assert r.status_code == 200  # Returns 200 with error in body
    assert "error" in r.json()

    # Add 2 participants
    await client.post(
        f"/api/tournaments/{tid}/participants",
        json={"display_name": "A"},
        headers=auth_headers,
    )
    await client.post(
        f"/api/tournaments/{tid}/participants",
        json={"display_name": "B"},
        headers=auth_headers,
    )

    # Preview with 2 participants - success
    r = await client.get(f"/api/tournaments/{tid}/bracket/preview")
    assert r.status_code == 200
    data = r.json()
    assert "rounds" in data
    assert "error" not in data or not data.get("error")


@pytest.mark.asyncio
async def test_bracket_generate(client, auth_headers):
    """Generate bracket from participants."""
    r = await client.post(
        "/api/tournaments",
        json={"name": "Generate Test", "format": "1v1"},
        headers=auth_headers,
    )
    tid = r.json()["id"]

    await client.post(
        f"/api/tournaments/{tid}/participants",
        json={"display_name": "P1"},
        headers=auth_headers,
    )
    await client.post(
        f"/api/tournaments/{tid}/participants",
        json={"display_name": "P2"},
        headers=auth_headers,
    )

    r = await client.post(
        f"/api/tournaments/{tid}/bracket/generate",
        json={"use_manual_order": True, "bracket_type": "single_elim"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert "ok" in r.json()

    # Get bracket
    r = await client.get(f"/api/tournaments/{tid}/bracket")
    assert r.status_code == 200
    data = r.json()
    assert "rounds" in data
    assert "error" not in data


@pytest.mark.asyncio
async def test_settings(client, auth_headers):
    """Settings GET is public, PATCH requires admin."""
    r = await client.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "site_title" in data
    assert "accent_color" in data

    r = await client.patch(
        "/api/settings",
        json={"site_title": "Test Title"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["site_title"] == "Test Title"


@pytest.mark.asyncio
async def test_auth_login(client):
    """Login with initial admin bootstrap."""
    r = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "testpass123"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    assert data["username"] == "admin"
    assert data["role"] == "admin"


@pytest.mark.asyncio
async def test_auth_login_invalid(client):
    """Login with wrong password fails."""
    r = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_404_tournament(client):
    """Non-existent tournament returns 404 for participants."""
    r = await client.get("/api/tournaments/99999/participants")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_protected_endpoints_require_auth(client, auth_headers):
    """Protected endpoints return 401 when called without auth headers."""
    r = await client.post("/api/tournaments", json={"name": "Auth Test", "format": "1v1"})
    assert r.status_code == 200
    tid = r.json()["id"]

    # Add participant - no auth
    r = await client.post(
        f"/api/tournaments/{tid}/participants",
        json={"display_name": "P1"},
    )
    assert r.status_code == 401, "add participant should require auth"

    # Add standby - no auth
    r = await client.post(
        f"/api/tournaments/{tid}/standby",
        json={"display_name": "S1"},
    )
    assert r.status_code == 401, "add standby should require auth"

    # Add participant with auth, then delete without auth
    r = await client.post(
        f"/api/tournaments/{tid}/participants",
        json={"display_name": "P1"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    pid = r.json()["id"]
    r = await client.delete(f"/api/tournaments/{tid}/participants/{pid}")
    assert r.status_code == 401, "delete participant should require auth"


@pytest.mark.asyncio
async def test_clone_tournament(client, auth_headers):
    """Clone tournament copies participants and standby."""
    r = await client.post(
        "/api/tournaments",
        json={"name": "Original", "format": "1v1"},
    )
    tid = r.json()["id"]
    await client.post(
        f"/api/tournaments/{tid}/participants",
        json={"display_name": "P1"},
        headers=auth_headers,
    )
    await client.post(
        f"/api/tournaments/{tid}/standby",
        json={"display_name": "S1"},
        headers=auth_headers,
    )
    r = await client.post(
        f"/api/tournaments/{tid}/clone",
        json={},
        headers=auth_headers,
    )
    assert r.status_code == 200
    cloned = r.json()
    assert cloned["name"] == "Original (copy)"
    assert cloned["format"] == "1v1"
    cid = cloned["id"]
    r = await client.get(f"/api/tournaments/{cid}/participants")
    assert len(r.json()) == 1
    assert r.json()[0]["display_name"] == "P1"
    r = await client.get(f"/api/tournaments/{cid}/standby")
    assert len(r.json()) == 1
    assert r.json()[0]["display_name"] == "S1"
