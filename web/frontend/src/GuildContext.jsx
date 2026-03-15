import React, { createContext, useContext } from 'react';
import { useLocation, useParams } from 'react-router-dom';

const GuildContext = createContext(null);

export function GuildProvider({ children }) {
  const params = useParams();
  const location = useLocation();
  // useParams may be empty when GuildProvider wraps Routes; fallback to parsing pathname
  const m = location.pathname.match(/^\/s\/(\d+)/);
  const guildId = params.guildId || (m ? m[1] : null);
  const apiBase = guildId ? `/api/s/${guildId}` : '/api';

  return (
    <GuildContext.Provider value={{ guildId, apiBase }}>
      {children}
    </GuildContext.Provider>
  );
}

export function useGuild() {
  const ctx = useContext(GuildContext);
  return ctx || { guildId: null, apiBase: '/api' };
}
