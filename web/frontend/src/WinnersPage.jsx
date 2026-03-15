import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useGuild } from './GuildContext';
import { GuildSelector } from './GuildSelector';

export default function WinnersPage() {
  const { guildId, apiBase } = useGuild();
  const [winners, setWinners] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${apiBase}/winners`);
        const data = await res.json();
        setWinners(Array.isArray(data) ? data : []);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    })();
  }, [apiBase]);

  if (loading) return <div style={{ padding: 32 }}>Loading...</div>;

  return (
    <div style={{ padding: 32, maxWidth: 720, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
        <h1 style={{ margin: 0, fontSize: 28, color: 'var(--text-primary)' }}>
          🏆 All-time winners
        </h1>
        <GuildSelector />
      </div>
      <p style={{ color: 'var(--text-secondary)', marginBottom: 24, fontSize: 14 }}>
        Tournament champions from completed brackets.
      </p>
      {error && (
        <div style={{ padding: 12, marginBottom: 16, background: 'rgba(239,68,68,0.15)', border: '1px solid var(--error)', borderRadius: 'var(--radius-sm)', color: 'var(--error)' }}>
          {error}
        </div>
      )}
      {winners.length === 0 ? (
        <p style={{ color: 'var(--text-muted)' }}>No completed tournaments with champions yet.</p>
      ) : (
        <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'var(--bg-elevated)' }}>
                <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: 12, color: 'var(--text-muted)', fontWeight: 600 }}>Tournament</th>
                <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: 12, color: 'var(--text-muted)', fontWeight: 600 }}>Format</th>
                <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: 12, color: 'var(--text-muted)', fontWeight: 600 }}>Champion</th>
              </tr>
            </thead>
            <tbody>
              {winners.map((w) => (
                <tr key={w.tournament_id} style={{ borderTop: '1px solid var(--border)' }}>
                  <td style={{ padding: '12px 16px', color: 'var(--text-primary)' }}>{w.tournament_name}</td>
                  <td style={{ padding: '12px 16px', color: 'var(--text-secondary)' }}>{w.format}</td>
                  <td style={{ padding: '12px 16px', color: 'var(--success)', fontWeight: 600 }}>
                    <div>👑 {w.winner_name}</div>
                    {w.winner_players && w.winner_players.length > 0 && (
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', fontWeight: 400, marginTop: 4 }}>
                        {w.winner_players.join(', ')}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p style={{ marginTop: 24 }}>
        <Link to={guildId ? `/s/${guildId}` : '/'} style={{ color: 'var(--accent)' }}>← Back to brackets</Link>
      </p>
    </div>
  );
}
