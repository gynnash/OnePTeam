import { useEffect, useState } from 'react';
import { getArticle, getArticles, getGraph, getNote, getNotes, triggerArticle } from '../api.js';

function GraphView({ graph }) {
  if (!graph || !graph.nodes || graph.nodes.length === 0) return <p className="muted">No graph nodes yet.</p>;
  const width = 700, height = 420;
  const cols = Math.max(1, Math.ceil(Math.sqrt(graph.nodes.length)));
  const positions = graph.nodes.map((node, index) => {
    const col = index % cols, row = Math.floor(index / cols);
    return { id: node.id, x: 40 + col * ((width - 80) / Math.max(1, cols - 1)), y: 40 + row * 60 };
  });
  const byId = new Map(positions.map((p) => [p.id, p]));
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="graph" role="img" aria-label="reasoning graph">
      {graph.edges.map((edge, index) => {
        const a = byId.get(edge.source), b = byId.get(edge.target);
        if (!a || !b) return null;
        return <line key={index} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#888" strokeWidth="1" />;
      })}
      {graph.nodes.map((node) => {
        const p = byId.get(node.id);
        return (
          <g key={node.id}>
            <circle cx={p.x} cy={p.y} r="8" fill="#4c9be8"><title>{node.label}</title></circle>
            <text x={p.x + 10} y={p.y + 4} className="graph-label">{node.label.slice(0, 18)}</text>
          </g>
        );
      })}
    </svg>
  );
}

export default function KnowledgeBrowser({ name, navigate }) {
  const [tab, setTab] = useState('notes');
  const [vault, setVault] = useState('project');
  const [notes, setNotes] = useState([]);
  const [selected, setSelected] = useState('');
  const [note, setNote] = useState(null);
  const [graph, setGraph] = useState(null);
  const [articles, setArticles] = useState([]);
  const [article, setArticle] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  useEffect(() => { getNotes(name, vault).then((data) => setNotes(data.notes)).catch((e) => setError(e.message)); }, [name, vault]);
  useEffect(() => { getGraph(name).then((data) => setGraph(data)).catch(() => {}); }, [name]);
  useEffect(() => { getArticles().then((data) => setArticles(data.articles)).catch(() => {}); }, [name]);

  const openNote = (path) => {
    setSelected(path);
    getNote(name, vault, path).then((data) => setNote(data)).catch((e) => setError(e.message));
  };
  const openArticle = async (slug) => {
    setError('');
    try { setArticle(await getArticle(slug)); } catch (e) { setError(e.message); }
  };
  const generate = async () => {
    setBusy(true); setError(''); setMessage('');
    try {
      const result = await triggerArticle(name);
      setMessage(`Article written: ${result.title}`);
      setArticles((await getArticles()).articles);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  return (
    <section>
      <h2>Knowledge — {name} <button onClick={() => navigate('run', name)}>Back to run</button></h2>
      <div className="tabs">
        <button className={tab === 'notes' ? 'active' : ''} onClick={() => setTab('notes')}>Notes</button>
        <button className={tab === 'graph' ? 'active' : ''} onClick={() => setTab('graph')}>Reasoning graph</button>
        <button className={tab === 'articles' ? 'active' : ''} onClick={() => setTab('articles')}>Articles</button>
      </div>
      {message && <p className="ok">{message}</p>}{error && <p className="error">{error}</p>}
      {tab === 'notes' && (
        <div className="two-column">
          <div className="notes-list">
            <div className="vault-toggle">
              <button className={vault === 'project' ? 'active' : ''} onClick={() => { setVault('project'); setSelected(''); setNote(null); }}>Project</button>
              <button className={vault === 'global' ? 'active' : ''} onClick={() => { setVault('global'); setSelected(''); setNote(null); }}>Global</button>
            </div>
            {notes.map((entry) => (
              <div key={entry.id} className={selected === entry.path ? 'note-item selected' : 'note-item'} onClick={() => openNote(entry.path)}>
                <span className="note-title">{entry.title}</span>
                <span className="note-meta">{entry.type} · iter {entry.iteration}</span>
              </div>
            ))}
            {notes.length === 0 && <p className="muted">No notes in this vault yet.</p>}
          </div>
          <div className="note-reader">
            {note ? (
              <>
                <pre className="evidence">{JSON.stringify(note.frontmatter, null, 2)}</pre>
                <div className="markdown">{note.body.split('\n').map((line, index) => <p key={index}>{line || ' '}</p>)}</div>
              </>
            ) : <p className="muted">Select a note to read it.</p>}
          </div>
        </div>
      )}
      {tab === 'graph' && <GraphView graph={graph} />}
      {tab === 'articles' && (
        <div className="two-column">
          <div className="notes-list">
            <button onClick={generate} disabled={busy} className="generate">{busy ? 'Synthesizing…' : 'Generate article'}</button>
            {articles.map((entry) => (
              <div key={entry.slug} className="note-item" onClick={() => openArticle(entry.slug)}>
                <span className="note-title">{entry.title}</span>
                <span className="note-meta">{entry.project} · {String(entry.created).slice(0, 10)}</span>
              </div>
            ))}
            {articles.length === 0 && <p className="muted">No articles yet — generate one from the run records.</p>}
          </div>
          <div className="note-reader">
            {article ? (
              <>
                <div className="markdown">{article.markdown.split('\n').map((line, index) => <p key={index}>{line || ' '}</p>)}</div>
                <h4>Reasoning graph for this article</h4>
                <GraphView graph={article.graph} />
              </>
            ) : <p className="muted">Select an article to read it.</p>}
          </div>
        </div>
      )}
    </section>
  );
}
