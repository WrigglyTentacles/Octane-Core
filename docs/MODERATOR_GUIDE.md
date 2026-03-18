# Octane Moderator & Admin Guide

A guide for moderators and admins running Rocket League tournaments with Octane.

---

## Roles & Permissions

| Role | Can do |
|------|--------|
| **Guild moderator** | Create/edit tournaments, generate brackets, manage participants, post to Discord |
| **Guild admin** | Everything above + guild settings (theme, Discord channels) |
| **Global admin** | Full site access, all guilds, user management |

---

## Tournament Lifecycle

### 1. Create a tournament

**Discord:** `/tournament create` — format, MMR playlist, optional deadline and start time.

**Web:** Hamburger menu (☰) → Create new tournament → name, format, signup deadline, tournament begins.

**Times:** Set signup deadline and/or tournament begins. If only one is set, the other defaults to it.

### 2. Post signup

**Discord:** `/tournament post` — posts the signup embed for users to react.

**Web:** Hamburger menu → Post signup to Discord (requires signup channel configured).

**Setup:** Run `/tournament set-signup-channel` in the channel where you want signups, or configure the Discord signup channel in Settings.

### 3. Manage participants

**Web:** Participants tab — add participants, standby, reorder, move between lists.

**Discord:** Users react to the signup post or use `/tournament register`.

### 4. Teams (2v2, 3v3 only)

**Discord:** `/team add`, `/team remove`, `/team list`, `/team update` (substitute).

**Web:** Teams tab — add/remove members, assign to teams.

### 5. Generate bracket

**Web:** Bracket tab → Choose bracket type (single or double elimination) → Generate Bracket.

**Discord:** `/bracket generate`.

### 6. Post to Discord

- **Post Teams** — Teams/participants list (for assembly before round 1).
- **Post Round** — Current round lineup.
- **Post Results** — Tournament results (requires champion).
- **Post roster** — Full signup list (hamburger menu).
- **Post tournament begins** — Standalone start time (hamburger menu, when set).

### 7. Record results

**Web:** Click a match card → Set winner.

**Discord:** `/bracket update` — match ID and winner slot.

### 8. Cleanup

**Web:** Hamburger menu → Cleanup messages — removes all tracked Discord messages.

**Discord:** `/tournament cleanup` — same.

---

## Discord Commands Reference

### Tournament (moderator+)

| Command | Description |
|---------|-------------|
| `/tournament create` | Create tournament |
| `/tournament list` | List tournaments |
| `/tournament post` | Post signup message |
| `/tournament post-roster` | Post full signup roster |
| `/tournament edit` | Edit name, status, deadline, starts_at |
| `/tournament cleanup` | Delete tracked Discord messages |
| `/tournament delete` | Delete tournament (admin only) |

### Tournament (all users)

| Command | Description |
|---------|-------------|
| `/tournament register` | Sign up |
| `/tournament unregister` | Drop out |
| `/tournament status` | Check signup status |

### Bracket (moderator+)

| Command | Description |
|---------|-------------|
| `/bracket generate` | Generate bracket |
| `/bracket post` | Post current round lineup |
| `/bracket post-teams` | Post teams/participants |
| `/bracket update` | Record match winner |

### Bracket (all users)

| Command | Description |
|---------|-------------|
| `/bracket view` | View bracket |
| `/bracket next` | Who you play next |
| `/bracket status` | Full match status |

### Team (moderator+)

| Command | Description |
|---------|-------------|
| `/team add` | Add player to team |
| `/team remove` | Remove from team |
| `/team update` | Substitute player |
| `/team list` | List teams |

### Config (admin)

| Command | Description |
|---------|-------------|
| `/config invite` | Bot invite link |
| `/config sync` | Sync slash commands |
| `/config roles` | Set moderator/admin role IDs |
| `/config debug_roles` | Show your roles |

---

## Web UI Reference

### Hamburger menu (☰)

- **Rename** — Tournament name
- **Set times** — Signup deadline and tournament begins
- **Post tournament begins** — Standalone start time (when set)
- **Post signup to Discord**
- **Post roster** — Full signup list
- **Cleanup messages** — Remove tracked Discord messages
- **Clone** — Copy participants to new tournament
- **Re-open** — Re-open closed/completed tournament
- **Archive** / **Unarchive**
- **Delete**
- **Format** — 1v1, 2v2, 3v3, 4v4

### Bracket tab

- **Post Teams** — Teams/participants list
- **Post Round** — Current round
- **Post Results** — Tournament results
- **Reset** — Delete bracket (requires regenerate)

### Settings (guild admin)

- **Discord** — Signup channel, bracket channel
- **Theme** — Colors, branding
- **User management** — Guild moderators (global admin)

---

## Settings & Configuration

### Discord channels

1. **Signup channel** — Where signup messages are posted. Set via `/tournament set-signup-channel` or in Settings.
2. **Bracket channel** — Where teams, round, results, roster, and tournament begins are posted. Set in Settings.

### Bot setup

1. Invite bot: `/config invite`
2. Sync commands: `/config sync`
3. Set moderator/admin roles: `/config roles`

---

## Tips

- **Tournament ID**: Shown on signup posts and in `/tournament list`. Use it with all commands.
- **Post Results**: Requires a champion. Cleanup runs automatically when posting.
- **Cleanup**: Removes signup, teams, round, results, roster, and tournament begins messages.
- **Starts at vs deadline**: Signup deadline = when signups close. Tournament begins = when the tournament starts. Both can be set.
