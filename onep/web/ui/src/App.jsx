import { useEffect, useState } from 'react';
import Dashboard from './views/Dashboard.jsx';
import RunDetail from './views/RunDetail.jsx';
import Candidates from './views/Candidates.jsx';
import KnowledgeBrowser from './views/KnowledgeBrowser.jsx';

function parseHash() {
  const hash = window.location.hash.replace(/^#/, '');
  const [route, param] = hash.split('/').filter(Boolean);
  return { route: route || 'dashboard', param: param ? decodeURIComponent(param) : '' };
}

export default function App() {
  const [location, setLocation] = useState(parseHash());
  useEffect(() => {
    const onChange = () => setLocation(parseHash());
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  const navigate = (route, param = '') => {
    window.location.hash = param ? `/${route}/${encodeURIComponent(param)}` : `/${route}`;
  };
  let view;
  if (location.route === 'run' && location.param) view = <RunDetail name={location.param} navigate={navigate} />;
  else if (location.route === 'candidates' && location.param) view = <Candidates name={location.param} navigate={navigate} />;
  else if (location.route === 'knowledge' && location.param) view = <KnowledgeBrowser name={location.param} navigate={navigate} />;
  else view = <Dashboard navigate={navigate} />;
  return (
    <div className="app">
      <header className="topbar">
        <span className="brand" onClick={() => navigate('dashboard')}>OnePTeam</span>
        <span className="sub">Autonomous Development Harness</span>
      </header>
      <main>{view}</main>
    </div>
  );
}
