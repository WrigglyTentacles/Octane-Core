import React, { useEffect, useState } from 'react';
import { useParams, useSearchParams, useNavigate } from 'react-router-dom';

const TOKEN_KEY = 'octane_token';

export default function RegisterPage() {
  const { guildId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState('loading'); // loading, success, error
  const [error, setError] = useState(null);

  const token = searchParams.get('token');

  useEffect(() => {
    if (!guildId || !token) {
      setStatus('error');
      setError('Missing token. Use /webregister in Discord to get your link.');
      return;
    }

    const doRegister = async () => {
      try {
        const res = await fetch(`/api/s/${guildId}/register?token=${encodeURIComponent(token)}`);
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || data.error || 'Registration failed');
        }
        localStorage.setItem(TOKEN_KEY, data.access_token);
        setStatus('success');
        setTimeout(() => navigate(`/s/${guildId}/current`, { replace: true }), 1500);
      } catch (err) {
        setStatus('error');
        setError(err.message);
      }
    };

    doRegister();
  }, [guildId, token, navigate]);

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
      <div style={{ maxWidth: 400, textAlign: 'center' }}>
        {status === 'loading' && <p>Registering...</p>}
        {status === 'success' && <p>Success! Redirecting to dashboard...</p>}
        {status === 'error' && (
          <>
            <p style={{ color: 'var(--text-secondary)', marginBottom: 16 }}>{error}</p>
            <a href="/login" style={{ color: 'var(--accent)' }}>Go to login</a>
          </>
        )}
      </div>
    </div>
  );
}
