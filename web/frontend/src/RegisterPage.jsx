import React, { useState } from 'react';
import { useParams, useSearchParams, useNavigate } from 'react-router-dom';

const TOKEN_KEY = 'octane_token';

export default function RegisterPage() {
  const { guildId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState('form'); // form, loading, success, error
  const [error, setError] = useState(null);
  const [successUsername, setSuccessUsername] = useState(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const token = searchParams.get('token');

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!guildId || !token) {
      setStatus('error');
      setError('Missing token. Use /webregister in Discord to get your link.');
      return;
    }
    if (username.trim().length < 2) {
      setError('Username must be at least 2 characters');
      return;
    }
    if (password.length < 6) {
      setError('Password must be at least 6 characters');
      return;
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    setStatus('loading');
    setError(null);
    try {
      const res = await fetch(`/api/s/${guildId}/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, username: username.trim(), password }),
      });
      let data;
      try {
        data = await res.json();
      } catch {
        throw new Error(res.ok ? 'Invalid response' : `Registration failed (${res.status})`);
      }
      if (!res.ok) {
        const msg = Array.isArray(data.detail) ? data.detail.map((e) => e.msg || e).join(', ') : (data.detail || data.error || 'Registration failed');
        throw new Error(msg);
      }
      localStorage.setItem(TOKEN_KEY, data.access_token);
      setStatus('success');
      setSuccessUsername(data.username);
      setTimeout(() => navigate(`/s/${guildId}/current`, { replace: true }), 2500);
    } catch (err) {
      setStatus('form');
      setError(err.message);
    }
  };

  if (!guildId || !token) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        <div style={{ maxWidth: 400, textAlign: 'center' }}>
          <p style={{ color: 'var(--text-secondary)', marginBottom: 16 }}>Missing token. Use /webregister in Discord to get your link.</p>
          <a href="/login" style={{ color: 'var(--accent)' }}>Go to login</a>
        </div>
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
      <div style={{ maxWidth: 400, width: '100%' }}>
        {status === 'form' && (
          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <h2 style={{ margin: '0 0 8px', fontSize: 20 }}>Complete registration</h2>
            <p style={{ color: 'var(--text-muted)', fontSize: 14, marginBottom: 8 }}>
              Set up your username and password. Your account is linked to your Discord ID so you can manage tournaments across servers.
            </p>
            <p style={{ color: 'var(--text-muted)', fontSize: 13, marginBottom: 12, padding: 10, background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-sm)' }}>
              <strong>Already registered?</strong> Enter your existing username and password to add this server to your account.
            </p>
            {error && <p style={{ color: 'var(--error)', fontSize: 14 }}>{error}</p>}
            <div>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 12, color: 'var(--text-muted)' }}>Username</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Choose a username"
                autoComplete="username"
                style={{ width: '100%', padding: '10px 14px', boxSizing: 'border-box' }}
                minLength={2}
              />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 12, color: 'var(--text-muted)' }}>Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="At least 6 characters"
                autoComplete="new-password"
                style={{ width: '100%', padding: '10px 14px', boxSizing: 'border-box' }}
                minLength={6}
              />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 12, color: 'var(--text-muted)' }}>Confirm password</label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Repeat password"
                autoComplete="new-password"
                style={{ width: '100%', padding: '10px 14px', boxSizing: 'border-box' }}
              />
            </div>
            <button type="submit" className="primary" style={{ padding: '12px 20px' }}>
              Create account
            </button>
          </form>
        )}
        {status === 'loading' && <p style={{ textAlign: 'center' }}>Creating account...</p>}
        {status === 'success' && (
          <div style={{ textAlign: 'center' }}>
            <p style={{ marginBottom: 12 }}>Success! Logged in as <strong>{successUsername}</strong></p>
            <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>You can now log in with your username and password from any device.</p>
            <p style={{ fontSize: 13, marginTop: 12 }}>Redirecting to dashboard...</p>
          </div>
        )}
      </div>
    </div>
  );
}
