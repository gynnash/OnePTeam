import { useEffect, useState } from 'react';
import { candidateAction, getCandidates } from '../api.js';

export default function Candidates({ name, navigate }) {
  const [candidates, setCandidates] = useState([]);
  const [scores, setScores] = useState({});
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const load = () => getCandidates(name).then((data) => setCandidates(data.candidates)).catch((e) => setError(e.message));
  useEffect(() => { load(); const timer = setInterval(load, 5000); return () => clearInterval(timer); }, [name]);
  const act = async (id, action, body = {}) => {
    setError(''); setMessage('');
    try { await candidateAction(name, id, action, body); setMessage(`${action} recorded for ${id}`); await load(); }
    catch (e) { setError(e.message); }
  };
  return (
    <section>
      <h2>Candidates — {name} <button onClick={() => navigate('run', name)}>Back to run</button></h2>
      {message && <p className="ok">{message}</p>}{error && <p className="error">{error}</p>}
      <table className="projects">
        <thead><tr><th>ID</th><th>Title</th><th>Status</th><th>Score</th><th>Dimensions</th><th>Decision</th><th></th></tr></thead>
        <tbody>
          {candidates.map((candidate) => (
            <tr key={candidate.id}>
              <td>{candidate.id}</td>
              <td>{candidate.title}</td>
              <td>{candidate.status}</td>
              <td>{candidate.score !== null && candidate.score !== undefined ? candidate.score.toFixed(3) : '—'}</td>
              <td className="dimensions">
                {candidate.dimensions ? Object.entries(candidate.dimensions)
                  .filter(([key]) => key !== 'rationale')
                  .map(([key, value]) => `${key}=${value}`).join(' ') : ''}
              </td>
              <td>{candidate.decision ? `${candidate.decision.decision}${candidate.decision.applied ? ' (applied)' : ''}` : '—'}</td>
              <td className="row-actions">
                <button onClick={() => act(candidate.id, 'approve')}>Approve</button>
                <button onClick={() => act(candidate.id, 'reject')}>Reject</button>
                <input className="score-input" type="number" min="0" max="1" step="0.05"
                  placeholder="0.50" value={scores[candidate.id] || ''}
                  onChange={(e) => setScores({ ...scores, [candidate.id]: e.target.value })} />
                <button onClick={() => act(candidate.id, 'rescore', { score: Number(scores[candidate.id]) })}
                  disabled={!scores[candidate.id]}>Rescore</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {candidates.length === 0 && <p className="muted">No candidates yet — the Product Loop writes them after each round.</p>}
    </section>
  );
}
