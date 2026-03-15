import { useState, useEffect, useCallback } from 'react';
import { useAuth } from './AuthContext';

const API = '/api';

/** Fetch guilds the current user can moderate. Returns { guilds, loading, refetch }. */
export function useMyGuilds() {
  const { user, authFetch } = useAuth();
  const [guilds, setGuilds] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchGuilds = useCallback(async () => {
    if (!user) {
      setGuilds([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const res = await authFetch(`${API}/auth/my-guilds`);
      const data = await res.json();
      setGuilds(data.guilds || []);
    } catch {
      setGuilds([]);
    } finally {
      setLoading(false);
    }
  }, [user, authFetch]);

  useEffect(() => {
    fetchGuilds();
  }, [fetchGuilds]);

  return { guilds, loading, refetch: fetchGuilds };
}
