import { useEffect, useState } from 'react';
import { createProject, getProjects } from '../api.js';

export default function Dashboard({ navigate }) {
  const [projects, setProjects] = useState([]);
  const [requirement, setRequirement] = useState('');
  const [workspacePath, setWorkspacePath] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const load = () => getProjects().then((data) => setProjects(data.projects)).catch((e) => setError(e.message));
  useEffect(() => { load(); const timer = setInterval(load, 3000); return () => clearInterval(timer); }, []);
  const create = async (event) => {
    event.preventDefault();
    if ((!requirement.trim() && !workspacePath.trim()) || busy) return;
    setBusy(true); setError('');
    try {
      await createProject({ requirement: requirement.trim(), workspace_path: workspacePath.trim() });
      setRequirement('');
      setWorkspacePath('');
      await load();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  return (
    <section>
      <h2>Projects</h2>
      <form className="create-bar" onSubmit={create}>
        <input value={requirement} onChange={(e) => setRequirement(e.target.value)} placeholder="One-line requirement" />
        <input value={workspacePath} onChange={(e) => setWorkspacePath(e.target.value)} placeholder="Existing repository path (optional)" />
        <button type="submit" disabled={busy}>{busy ? 'Creating…' : 'Create'}</button>
      </form>
      {error && <p className="error">{error}</p>}
      <table className="projects">
        <thead><tr><th>Name</th><th>Mode</th><th>Status</th><th>Stage</th><th>Iteration</th><th>Stop reason</th></tr></thead>
        <tbody>
          {projects.map((project) => (
            <tr key={project.id} onClick={() => navigate('run', project.name)} className="clickable">
              <td>{project.name}</td>
              <td>{project.mode}</td>
              <td>{project.status}</td>
              <td>{project.harness ? project.harness.stage : (project.current_stage || '—')}</td>
              <td>{project.harness ? project.harness.iteration : '—'}</td>
              <td>{project.harness && project.harness.stop_reason ? project.harness.stop_reason : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="hint">Click a project to open its run detail, candidates, and knowledge browser.</p>
    </section>
  );
}
