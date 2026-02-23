import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';

const API = '/api';
const TOKEN_KEY = 'octane_token';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const token = typeof window !== 'undefined' ? localStorage.getItem(TOKEN_KEY) : null;

  const canEdit = user && (user.role === 'moderator' || user.role === 'admin');
  const isAdmin = user && user.role === 'admin';

  const fetchUser = useCallback(async () => {
    const t = localStorage.getItem(TOKEN_KEY);
    if (!t) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const res = await fetch(`${API}/auth/me/optional`, {
        headers: { Authorization: `Bearer ${t}` },
      });
      const text = await res.text();
      let data = null;
      try {
        data = text ? JSON.parse(text) : null;
      } catch {
        data = null;
      }
      if (data) {
        setUser(data);
      } else {
        localStorage.removeItem(TOKEN_KEY);
        setUser(null);
      }
    } catch {
      localStorage.removeItem(TOKEN_KEY);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUser();
  }, [fetchUser]);

  const login = async (username, password) => {
    const res = await fetch(`${API}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail || 'Login failed');
    localStorage.setItem(TOKEN_KEY, data.access_token);
    setUser({ username: data.username, role: data.role });
    return data;
  };

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY);
    setUser(null);
  };

  const authFetch = useCallback(async (url, opts = {}) => {
    const t = localStorage.getItem(TOKEN_KEY);
    const headers = { ...opts.headers };
    if (t) {
      headers.Authorization = `Bearer ${t}`;
      headers['X-Auth-Token'] = t;
    }
    const res = await fetch(url, { ...opts, headers });
    if (res.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      setUser(null);
    }
    return res;
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, canEdit, isAdmin, login, logout, authFetch, fetchUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
