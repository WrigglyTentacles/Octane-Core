import React, { useEffect } from 'react';
import { useNavigate, useLocation, useParams } from 'react-router-dom';
import { useAuth } from './AuthContext';
import { useMyGuilds } from './useMyGuilds';

/** Dropdown to switch between guilds the user can moderate. Shown when user has edit rights and guilds. */
export function GuildSelector() {
  const { user, canEdit, isGlobalAdmin } = useAuth();
  const { guilds, loading } = useMyGuilds();
  const navigate = useNavigate();
  const location = useLocation();
  const params = useParams();
  const currentGuildId = params.guildId ? String(params.guildId) : null;
  const isOnGuildRoute = /^\/s\/\d+/.test(location.pathname);

  // Guild-scoped moderators: redirect from / to a guild so they only see that guild's tournaments
  useEffect(() => {
    if (!user || !canEdit || loading || isGlobalAdmin) return;
    if (isOnGuildRoute) return;
    if (guilds.length === 0) return;
    const g = guilds[0];
    if (g?.guild_id) navigate(`/s/${g.guild_id}${location.pathname === '/' ? '' : location.pathname}`, { replace: true });
  }, [user, canEdit, loading, guilds, isOnGuildRoute, navigate, location.pathname, isGlobalAdmin]);

  if (!user || !canEdit || loading || guilds.length === 0) return null;

  // Build path for a guild: /s/{guildId} + current subpath (e.g. /current, /winners)
  const subpath = location.pathname.replace(/^\/s\/\d+/, '') || '';
  const guildPath = (guildId) => (guildId ? `/s/${guildId}${subpath}` : subpath || '/');

  const handleChange = (e) => {
    const val = e.target.value;
    const target = val === '' ? '/' : guildPath(val);
    navigate(target);
  };

  const value = currentGuildId || (isGlobalAdmin ? '' : guilds[0]?.guild_id?.toString() ?? '');

  return (
    <select
      value={value}
      onChange={handleChange}
      style={{ padding: '8px 12px', fontSize: 14, minWidth: 160 }}
      title="Switch server"
    >
      {isGlobalAdmin && <option value="">Global</option>}
      {guilds.map((g) => (
        <option key={g.guild_id} value={String(g.guild_id)}>
          {g.name}
        </option>
      ))}
    </select>
  );
}
