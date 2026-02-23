import React, { useState, useEffect } from 'react';

function App() {
  const [tournamentId, setTournamentId] = useState(1);
  const [bracket, setBracket] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchBracket = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/tournaments/${tournamentId}/bracket`);
      const data = await res.json();
      if (data.error) {
        setError(data.error);
        setBracket(null);
      } else {
        setBracket(data);
      }
    } catch (err) {
      setError(err.message);
      setBracket(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (tournamentId > 0) fetchBracket();
  }, [tournamentId]);

  return (
    <div style={{ padding: 20, fontFamily: 'system-ui' }}>
      <h1>Octane Bracket Viewer</h1>
      <div style={{ marginBottom: 16 }}>
        <label>Tournament ID: </label>
        <input
          type="number"
          value={tournamentId}
          onChange={(e) => setTournamentId(parseInt(e.target.value) || 1)}
          min={1}
          style={{ marginRight: 8 }}
        />
        <button onClick={fetchBracket} disabled={loading}>
          {loading ? 'Loading...' : 'Load Bracket'}
        </button>
      </div>
      {error && <p style={{ color: 'red' }}>{error}</p>}
      {bracket && (
        <div>
          <h2>{bracket.tournament.name} ({bracket.tournament.format})</h2>
          {Object.entries(bracket.rounds).map(([roundNum, matches]) => (
            <div key={roundNum} style={{ marginBottom: 24 }}>
              <h3>Round {roundNum}</h3>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
                {matches.map((m) => (
                  <div
                    key={m.id}
                    style={{
                      border: '1px solid #ccc',
                      padding: 12,
                      borderRadius: 8,
                      minWidth: 200,
                    }}
                  >
                    <div>
                      {m.team1_name || m.player1_name || 'TBD'} vs{' '}
                      {m.team2_name || m.player2_name || 'TBD'}
                    </div>
                    {(m.winner_team_id || m.winner_player_id) && (
                      <div style={{ marginTop: 4, color: 'green' }}>
                        Winner: {m.winner_team_id ? 'Team' : 'Player'}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default App;
