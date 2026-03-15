import React, { createContext, useContext } from 'react';
import { useParams } from 'react-router-dom';

const GuildContext = createContext(null);

export function GuildProvider({ children }) {
  const params = useParams();
  const guildId = params.guildId || null;
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
