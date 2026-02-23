import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from './AuthContext';

const API = '/api';

export default function SettingsPage() {
  const { authFetch, isAdmin } = useAuth();
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
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
      <p style={{ marginTop: 24 }}>
        <Link to="/" style={{ color: 'var(--accent)' }}>← Back to brackets</Link>
      </p>
    </div>
  );
}
