# Octane-Core

Discord bot for Rocket League tournaments. Manages Epic ID registration, MMR-based seeding, and bracket generation.

## Features

- **Registration**: Link Epic Account ID to Discord (`/register`, `/profile`, `/update_epic`)
- **MMR**: View MMR and rank per playlist (`/mmr`, `/leaderboard`)
- **Tournaments**: Create tournaments with configurable format (1v1/2v2/3v3) and MMR playlist (`/tournament create`, `list`, `register`)
- **Teams**: Manage team rosters for 2v2/3v3 (`/team add`, `remove`, `update`, `list`)
- **Brackets**: Generate single-elimination brackets, view in Discord, record winners (`/bracket generate`, `view`, `update`)
- **Roles**: Moderator+ for create/edit/generate; Admin for delete/config

## Setup

1. **Discord**: Create application at [Discord Developer Portal](https://discord.com/developers/applications), get bot token
2. **Epic Games** (optional): For MMR and bracket seeding, register at [Epic Developer Portal](https://dev.epicgames.com/) and set `RLAPI_CLIENT_ID` and `RLAPI_CLIENT_SECRET`. Registration works without these — Epic IDs are trusted (wrong IDs surface in private matches).
3. **Environment**: Copy `.env.example` to `.env` and fill in:
   - `DISCORD_TOKEN` (required)
   - `RLAPI_CLIENT_ID`, `RLAPI_CLIENT_SECRET` (optional, for MMR/leaderboard/bracket seeding)
   - Optional: `MODERATOR_ROLE_IDS`, `ADMIN_ROLE_IDS` (comma-separated)

## Run Bot

```bash
pip install -r requirements.txt
python run.py
```

## Run Web UI (Optional)

**API:**
```bash
python web/run_api.py
```

**Frontend:**
```bash
cd web/frontend
npm install
npm start
```

Open http://localhost:5173 and enter a tournament ID to view the bracket.

## Project Structure

```
Octane-Core/
├── bot/           # Discord bot
│   ├── cogs/      # Slash command groups
│   ├── models/    # SQLAlchemy models
│   └── services/  # RL API, bracket generation
├── config.py
├── run.py
└── web/           # Optional bracket viewer
    ├── api/       # FastAPI
    └── frontend/  # React + Vite
```
