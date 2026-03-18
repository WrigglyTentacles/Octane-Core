# Octane-Core

Discord bot and web app for Rocket League tournaments. Create tournaments, manage signups and teams, generate brackets (single or double elimination), and record results.

## Guides

- **[User Guide](docs/USER_GUIDE.md)** — For players: signing up, viewing brackets, Discord commands
- **[Moderator Guide](docs/MODERATOR_GUIDE.md)** — For moderators and admins: running tournaments, Discord commands, web UI

## Features

- **Tournaments** — Create tournaments with configurable format (1v1, 2v2, 3v3), status, and bracket type
- **Registration** — Participants sign up via Discord or the web UI; moderators can manage standby lists
- **Teams** — Manage team rosters for 2v2/3v3 (`/team add`, `remove`, `list`)
- **Brackets** — Generate single-elimination or double-elimination brackets; view in Discord or web; record winners with `/bracket update`
- **Web UI** — Bracket viewer and management, participant/team lists, tournament configuration
- **Roles** — Moderator+ for create/edit/generate; Admin for delete and config

## Setup

1. **Discord** — Create an application at [Discord Developer Portal](https://discord.com/developers/applications):
   - **General Information** → copy your **Application ID**
   - **Bot** → click **Add Bot** (if not already added), copy the token, enable **Server Members Intent**
   - **Invite the bot** — use this URL (replace `YOUR_APPLICATION_ID` with your Application ID):
     ```
     https://discord.com/api/oauth2/authorize?client_id=YOUR_APPLICATION_ID&permissions=277025508360&scope=bot%20applications.commands
     ```
     The **`bot`** scope is required for the bot to join the server. Without it, the app installs but no bot user appears. Use **OAuth2 → URL Generator** in the Developer Portal and select scopes `bot` and `applications.commands` as an alternative.

2. **Environment** — Copy `.env.example` to `.env` and configure:
   - `DISCORD_TOKEN` (required)
   - `MODERATOR_ROLE_IDS` or `MODERATOR_ROLE_NAMES` (comma-separated)
   - `ADMIN_ROLE_IDS` or `ADMIN_ROLE_NAMES` (optional)
   - For web auth: `JWT_SECRET`, `INITIAL_ADMIN_USERNAME`, `INITIAL_ADMIN_PASSWORD`
   - For web→bot integration: `BOT_INTERNAL_URL`, `INTERNAL_API_SECRET`, `SITE_URL`

## Run

**Docker (recommended):**

```bash
docker compose up -d
```

- Bot: runs in background
- API: http://localhost:8000
- Frontend: served by API at `/`

**Manual:**

```bash
pip install -r requirements.txt
python run.py                    # Bot
python -m uvicorn web.api.main:app --host 0.0.0.0 --port 8000   # API
```

For local frontend dev: `cd web/frontend && npm install && npm start` (http://localhost:5173)

## Project Structure

```
Octane-Core/
├── bot/           # Discord bot
│   ├── cogs/      # Slash commands (tournaments, teams, brackets, etc.)
│   ├── models/    # SQLAlchemy models
│   └── services/  # Bracket generation, Discord embeds
├── config.py
├── run.py
└── web/
    ├── api/       # FastAPI (bracket, participants, auth)
    └── frontend/  # React + Vite
```
