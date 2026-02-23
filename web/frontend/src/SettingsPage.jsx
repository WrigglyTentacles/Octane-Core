import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from './AuthContext';

const API = '/api';

export default function SettingsPage() {
  const { authFetch, isAdmin, user: currentUser } = useAuth();
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [users, setUsers] = useState([]);
  const [userError, setUserError] = useState('');
  const [createUsername, setCreateUsername] = useState('');
  const [createPassword, setCreatePassword] = useState('');
  const [createRole, setCreateRole] = useState('user');
  const [editingUser, setEditingUser] = useState(null);
  const [editPassword, setEditPassword] = useState('');
  const [editRole, setEditRole] = useState('user');
  const [form, setForm] = useState({
    site_title: '',
    accent_color: '',
    accent_hover: '',
    bg_primary: '',
    bg_secondary: '',
  });

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API}/settings`);
        const data = await res.json();
        setSettings(data);
        setForm({
          site_title: data.site_title || '',
          accent_color: data.accent_color || '',
          accent_hover: data.accent_hover || '',
          bg_primary: data.bg_primary || '',
          bg_secondary: data.bg_secondary || '',
        });
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const fetchUsers = useCallback(async () => {
    try {
      const res = await authFetch(`${API}/auth/users`);
      if (!res.ok) throw new Error('Failed to load users');
      const data = await res.json();
      setUsers(data);
    } catch (err) {
      setUserError(err.message);
    }
  }, [authFetch]);

  useEffect(() => {
    if (isAdmin) fetchUsers();
  }, [isAdmin, fetchUsers]);

  const handleCreateUser = async (e) => {
    e.preventDefault();
    setUserError('');
    if (!createUsername.trim() || !createPassword) {
      setUserError('Username and password required');
      return;
    }
    try {
      const res = await authFetch(`${API}/auth/users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: createUsername.trim(), password: createPassword, role: createRole }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || 'Failed to create user');
      setCreateUsername('');
      setCreatePassword('');
      setCreateRole('user');
      await fetchUsers();
    } catch (err) {
      setUserError(err.message);
    }
  };

  const handleUpdateUser = async (e) => {
    e.preventDefault();
    if (!editingUser) return;
    setUserError('');
    try {
      const body = {};
      if (editPassword) body.password = editPassword;
      if (editRole) body.role = editRole;
      if (Object.keys(body).length === 0) {
        setEditingUser(null);
        return;
      }
      const res = await authFetch(`${API}/auth/users/${encodeURIComponent(editingUser)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data?.detail || 'Failed to update');
      }
      setEditingUser(null);
      setEditPassword('');
      setEditRole('user');
      await fetchUsers();
    } catch (err) {
      setUserError(err.message);
    }
  };

  const handleDeleteUser = async (username) => {
    if (!window.confirm(`Delete user "${username}"? This cannot be undone.`)) return;
    setUserError('');
    try {
      const res = await authFetch(`${API}/auth/users/${encodeURIComponent(username)}`, { method: 'DELETE' });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data?.detail || 'Failed to delete');
      }
      await fetchUsers();
    } catch (err) {
      setUserError(err.message);
    }
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setError('');
    setSaving(true);
    try {
      const res = await authFetch(`${API}/settings`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (!res.ok) throw new Error('Failed to save');
      const data = await res.json();
      setSettings(data);
      setForm({
        site_title: data.site_title || '',
        accent_color: data.accent_color || '',
        accent_hover: data.accent_hover || '',
        bg_primary: data.bg_primary || '',
        bg_secondary: data.bg_secondary || '',
      });
      document.documentElement.style.setProperty('--site-title', data.site_title);
      document.documentElement.style.setProperty('--accent', data.accent_color);
      document.documentElement.style.setProperty('--accent-hover', data.accent_hover);
      document.documentElement.style.setProperty('--bg-primary', data.bg_primary);
      document.documentElement.style.setProperty('--bg-secondary', data.bg_secondary);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  if (!isAdmin) {
    return (
      <div style={{ padding: 32, color: 'var(--text-muted)' }}>
        Admin access required to manage settings.
      </div>
    );
  }

  if (loading) return <div style={{ padding: 32 }}>Loading...</div>;

  return (
    <div style={{ padding: 32, maxWidth: 560 }}>
      <h1 style={{ margin: '0 0 24px', fontSize: 24, color: 'var(--text-primary)' }}>
        Site settings
      </h1>
      <p style={{ color: 'var(--text-secondary)', marginBottom: 24, fontSize: 14 }}>
        Customize the site title and theme colors. Changes apply immediately.
      </p>
      <form onSubmit={handleSave}>
        {error && (
          <div
            style={{
              padding: 12,
              marginBottom: 16,
              background: 'rgba(239,68,68,0.15)',
              border: '1px solid var(--error)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--error)',
            }}
          >
            {error}
          </div>
        )}
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: 'var(--text-secondary)' }}>
            Site title
          </label>
          <input
            type="text"
            value={form.site_title}
            onChange={(e) => setForm((f) => ({ ...f, site_title: e.target.value }))}
            style={{ width: '100%', padding: '10px 14px' }}
            placeholder="Octane Bracket Manager"
          />
        </div>
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: 'var(--text-secondary)' }}>
            Accent color
          </label>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <input
              type="color"
              value={form.accent_color || '#93E9BE'}
              onChange={(e) => setForm((f) => ({ ...f, accent_color: e.target.value }))}
              style={{ width: 48, height: 36, padding: 2, cursor: 'pointer' }}
            />
            <input
              type="text"
              value={form.accent_color}
              onChange={(e) => setForm((f) => ({ ...f, accent_color: e.target.value }))}
              style={{ flex: 1, padding: '10px 14px' }}
              placeholder="#93E9BE"
            />
          </div>
        </div>
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: 'var(--text-secondary)' }}>
            Accent hover color
          </label>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <input
              type="color"
              value={form.accent_hover || '#a8f0d0'}
              onChange={(e) => setForm((f) => ({ ...f, accent_hover: e.target.value }))}
              style={{ width: 48, height: 36, padding: 2, cursor: 'pointer' }}
            />
            <input
              type="text"
              value={form.accent_hover}
              onChange={(e) => setForm((f) => ({ ...f, accent_hover: e.target.value }))}
              style={{ flex: 1, padding: '10px 14px' }}
              placeholder="#a8f0d0"
            />
          </div>
        </div>
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: 'var(--text-secondary)' }}>
            Background primary
          </label>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <input
              type="color"
              value={form.bg_primary || '#0f0f12'}
              onChange={(e) => setForm((f) => ({ ...f, bg_primary: e.target.value }))}
              style={{ width: 48, height: 36, padding: 2, cursor: 'pointer' }}
            />
            <input
              type="text"
              value={form.bg_primary}
              onChange={(e) => setForm((f) => ({ ...f, bg_primary: e.target.value }))}
              style={{ flex: 1, padding: '10px 14px' }}
              placeholder="#0f0f12"
            />
          </div>
        </div>
        <div style={{ marginBottom: 24 }}>
          <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: 'var(--text-secondary)' }}>
            Background secondary
          </label>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <input
              type="color"
              value={form.bg_secondary || '#18181c'}
              onChange={(e) => setForm((f) => ({ ...f, bg_secondary: e.target.value }))}
              style={{ width: 48, height: 36, padding: 2, cursor: 'pointer' }}
            />
            <input
              type="text"
              value={form.bg_secondary}
              onChange={(e) => setForm((f) => ({ ...f, bg_secondary: e.target.value }))}
              style={{ flex: 1, padding: '10px 14px' }}
              placeholder="#18181c"
            />
          </div>
        </div>
        <button type="submit" className="primary" disabled={saving}>
          {saving ? 'Saving...' : 'Save settings'}
        </button>
      </form>

      <div style={{ borderTop: '1px solid var(--border)', marginTop: 40, paddingTop: 32 }}>
        <h2 style={{ margin: '0 0 16px', fontSize: 18, color: 'var(--text-primary)' }}>User management</h2>
        <p style={{ color: 'var(--text-secondary)', marginBottom: 20, fontSize: 14 }}>
          Create and manage user, moderator, and admin accounts. Users can view; moderators and admins can edit brackets.
        </p>
        {userError && (
          <div style={{ padding: 12, marginBottom: 16, background: 'rgba(239,68,68,0.15)', border: '1px solid var(--error)', borderRadius: 'var(--radius-sm)', color: 'var(--error)' }}>
            {userError}
          </div>
        )}
        <form onSubmit={handleCreateUser} style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-end', marginBottom: 16 }}>
            <div>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 12, color: 'var(--text-muted)' }}>Username</label>
              <input type="text" value={createUsername} onChange={(e) => setCreateUsername(e.target.value)} placeholder="username" style={{ padding: '8px 12px', width: 140 }} />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 12, color: 'var(--text-muted)' }}>Password</label>
              <input type="password" value={createPassword} onChange={(e) => setCreatePassword(e.target.value)} placeholder="••••••••" style={{ padding: '8px 12px', width: 140 }} />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 12, color: 'var(--text-muted)' }}>Role</label>
              <select value={createRole} onChange={(e) => setCreateRole(e.target.value)} style={{ padding: '8px 12px', width: 120 }}>
                <option value="user">User</option>
                <option value="moderator">Moderator</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <button type="submit" className="primary" disabled={!createUsername.trim() || !createPassword}>
              Create user
            </button>
          </div>
        </form>
        <div style={{ background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'var(--bg-elevated)' }}>
                <th style={{ padding: '10px 14px', textAlign: 'left', fontSize: 12, color: 'var(--text-muted)', fontWeight: 600 }}>Username</th>
                <th style={{ padding: '10px 14px', textAlign: 'left', fontSize: 12, color: 'var(--text-muted)', fontWeight: 600 }}>Role</th>
                <th style={{ padding: '10px 14px', textAlign: 'right', fontSize: 12, color: 'var(--text-muted)', fontWeight: 600 }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.username} style={{ borderTop: '1px solid var(--border)' }}>
                  <td style={{ padding: '10px 14px', color: 'var(--text-primary)' }}>{u.username}</td>
                  <td style={{ padding: '10px 14px' }}>
                    {editingUser === u.username ? (
                      <select value={editRole} onChange={(e) => setEditRole(e.target.value)} style={{ padding: '4px 8px', fontSize: 13 }}>
                        <option value="user">user</option>
                        <option value="moderator">moderator</option>
                        <option value="admin">admin</option>
                      </select>
                    ) : (
                      <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>{u.role}</span>
                    )}
                  </td>
                  <td style={{ padding: '10px 14px', textAlign: 'right' }}>
                    {editingUser === u.username ? (
                      <>
                        <input type="password" value={editPassword} onChange={(e) => setEditPassword(e.target.value)} placeholder="New password" style={{ padding: '4px 8px', width: 120, marginRight: 8 }} />
                        <button onClick={handleUpdateUser} style={{ padding: '4px 10px', fontSize: 12, marginRight: 6 }}>Save</button>
                        <button onClick={() => { setEditingUser(null); setEditPassword(''); setEditRole('user'); }} style={{ padding: '4px 10px', fontSize: 12 }}>Cancel</button>
                      </>
                    ) : (
                      <>
                        <button onClick={() => { setEditingUser(u.username); setEditRole(u.role); setEditPassword(''); }} style={{ padding: '4px 10px', fontSize: 12, marginRight: 6 }}>Edit</button>
                        {u.username !== currentUser?.username && (
                          <button onClick={() => handleDeleteUser(u.username)} style={{ padding: '4px 10px', fontSize: 12, color: 'var(--error)' }}>Delete</button>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <p style={{ marginTop: 24 }}>
        <Link to="/" style={{ color: 'var(--accent)' }}>← Back to brackets</Link>
      </p>
    </div>
  );
}
