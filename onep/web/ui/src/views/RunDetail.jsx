import { useEffect, useRef, useState } from 'react';
import { getRunDetail, openEvents, stopProject } from '../api.js';

function StageChain({ stages, current }) {
  const rows = [];
  stages.forEach((stage, index) => {
    rows.push(<div key={stage} className={stage === current ? 'stage active' : 'stage'}>{stage}</div>);
    if (index < stages.length - 1) rows.push(<div key={`a-${stage}`} className="arrow">→</div>);
  });
  return <div className="stage-chain">{rows}</div>;
}

function QualityCurve({ history }) {
  if (!history || history.length < 2) return <p className="muted">Not enough history for a curve yet.</p>;
  const width = 480, height = 140, pad = 24;
  const maxX = history.length - 1;
  const points = history.map((point, index) => {
    const x = pad + (index / maxX) * (width - 2 * pad);
    const y = height - pad - Math.max(0, point.quality_score) * (height - 2 * pad);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="curve" role="img" aria-label="quality curve">
      <polyline points={points} fill="none" stroke="#4c9be8" strokeWidth="2" />
      {history.map((point, index) => {
        const x = pad + (index / maxX) * (width - 2 * pad);
        const y = height - pad - Math.max(0, point.quality_score) * (height - 2 * pad);
        return <circle key={point.iteration} cx={x} cy={y} r="3" fill="#4c9be8"><title>{`iter ${point.iteration}: ${point.quality_score}`}</title></circle>;
      })}
    </svg>
  );
}

export default function RunDetail({ name, navigate }) {
  const [detail, setDetail] = useState(null);
  const [log, setLog] = useState([]);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const logRef = useRef(null);
  useEffect(() => {
    let cancelled = false;
    const load = () => getRunDetail(name).then((data) => { if (!cancelled) setDetail(data); }).catch((e) => setError(e.message));
    load();
    const timer = setInterval(load, 5000);
    const source = openEvents(name, (event) => {
      if (event.type === 'state') load();
      if (event.type === 'log') setLog((lines) => [...lines.slice(-399), event.payload]);
      if (event.type === 'flow') {
        load();
        setLog((lines) => [...lines, { type: 'trace', payload: { label: 'FLOW', message: `${event.payload.stage} (iter ${event.payload.iteration})` } }]);
      }
      if (event.type === 'distill') setLog((lines) => [...lines, { type: 'distill', payload: { label: 'KNOWLEDGE', message: `${event.payload.type} event distilled` } }]);
    });
    return () => { cancelled = true; clearInterval(timer); source.close(); };
  }, [name]);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [log]);
  const doStop = async () => {
    setError(''); setMessage('');
    try { const result = await stopProject(name); setMessage(result.note); } catch (e) { setError(e.message); }
  };
  if (!detail) return <section><h2>Run {name}</h2>{error && <p className="error">{error}</p>}<p className="muted">Loading…</p></section>;
  const history = (detail.quality_history || []).map((point) => ({ iteration: point.iteration, quality_score: point.quality_score }));
  return (
    <section>
      <h2>Run {detail.project_name} <span className={`pill ${detail.status}`}>{detail.status}</span></h2>
      <p className="goal">{detail.original_goal}</p>
      <div className="run-actions">
        <button onClick={() => navigate('candidates', name)}>Candidates</button>
        <button onClick={() => navigate('knowledge', name)}>Knowledge</button>
        <button onClick={doStop} className="danger">Force stop</button>
      </div>
      {message && <p className="ok">{message}</p>}{error && <p className="error">{error}</p>}
      <div className="cards">
        <div className="card"><span className="label">Stage</span><span className="value">{detail.stage}</span></div>
        <div className="card"><span className="label">Iteration</span><span className="value">{detail.iteration}</span></div>
        <div className="card"><span className="label">Spent ($)</span><span className="value">{detail.spent.toFixed(4)}</span></div>
        <div className="card"><span className="label">Stop reason</span><span className="value">{detail.stop_state && detail.stop_state.reason ? detail.stop_state.reason : '—'}</span></div>
      </div>
      <h3>State machine</h3>
      <StageChain stages={detail.stages} current={detail.stage} />
      <h3>Quality curve</h3>
      <QualityCurve history={history} />
      <h3>Stop evidence</h3>
      <pre className="evidence">{JSON.stringify(detail.stop_state, null, 2)}</pre>
      <h3>Live log</h3>
      <div className="log" ref={logRef}>
        {log.map((entry, index) => (
          <div key={index} className="log-line">
            <span className="log-label">{entry.payload && entry.payload.label}</span>
            <span>{entry.payload && entry.payload.message}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
