const jsonHeaders = { 'Content-Type': 'application/json' };

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = response.statusText;
    try { const data = await response.json(); detail = data.detail || detail; } catch (e) { /* ignore */ }
    throw new Error(detail);
  }
  return response.json();
}

export const getProjects = () => api('/api/projects');
export const createProject = (body) => api('/api/projects', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(body) });
export const getRunDetail = (name) => api(`/api/projects/${encodeURIComponent(name)}`);
export const getLog = (name, offset = 0) => api(`/api/projects/${encodeURIComponent(name)}/log?offset=${offset}&limit=200`);
export const stopProject = (name) => api(`/api/projects/${encodeURIComponent(name)}/stop`, { method: 'POST' });
export const getCandidates = (name) => api(`/api/projects/${encodeURIComponent(name)}/candidates`);
export const candidateAction = (name, id, action, body = {}) =>
  api(`/api/projects/${encodeURIComponent(name)}/candidates/${encodeURIComponent(id)}/${action}`, { method: 'POST', headers: jsonHeaders, body: JSON.stringify(body) });
export const triggerArticle = (name) => api(`/api/projects/${encodeURIComponent(name)}/article`, { method: 'POST' });
export const getNotes = (project, vault) => api(`/api/knowledge/notes?project=${encodeURIComponent(project || '')}&vault=${vault}`);
export const getNote = (project, vault, path) => api(`/api/knowledge/notes/content?project=${encodeURIComponent(project || '')}&vault=${vault}&path=${encodeURIComponent(path)}`);
export const getGraph = (project) => api(`/api/knowledge/graph?project=${encodeURIComponent(project)}`);
export const getArticles = () => api('/api/knowledge/articles');
export const getArticle = (slug) => api(`/api/knowledge/articles/${encodeURIComponent(slug)}`);

export function openEvents(name, onEvent) {
  const source = new EventSource(`/api/projects/${encodeURIComponent(name)}/events`);
  source.onmessage = (message) => {
    try { onEvent(JSON.parse(message.data)); } catch (e) { /* ignore malformed */ }
  };
  return source;
}
