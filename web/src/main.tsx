import { StrictMode, type ComponentType } from 'react';
import { createRoot } from 'react-dom/client';
import './styles/fonts.css';
import './styles/tokens.css';
import './styles/components.css';
import './styles/shell.css';
import './styles/spaces.css';
import './styles/pro.css';
import './styles/project.css';
import { detectSession } from './project/api';
import { ErrorBoundary } from './shared/ui/ErrorBoundary';

// Served by `openguildkit ui`, the page opens the project of that server. Anywhere else (a static host,
// `npm run dev` without OGK_API, or ?demo=1) it opens the Atelier Nova demonstration.

function Splash() {
  return <div className="splash" role="status"><img src="./assets/brand/favicon.png" alt="" width={48} height={48} /><span>Ouverture de la guilde…</span></div>;
}

async function start() {
  const demo = new URLSearchParams(window.location.search).has('demo');
  // `openguildkit ui` marks its page: the project code then downloads while the session is read.
  const served = !demo && !!document.querySelector('meta[name="openguildkit-ui"]');
  if (served) void import('./project/ProjectApp');
  const session = demo ? null : await detectSession();
  document.documentElement.dataset.app = session ? 'project' : 'demo';
  document.title = session ? `${session.project.name} · Open Guild Kit` : 'Open Guild Kit — Démonstration interactive';
  const root = createRoot(document.getElementById('root')!);
  root.render(<Splash />);
  // The app and the screen of the address are loaded before the first render: no screen waits on a chunk.
  let App: ComponentType;
  if (session) {
    const project = await import('./project/ProjectApp');
    await project.preloadRoute(session.project.initialized);
    App = project.ProjectApp;
  } else {
    const demoApp = await import('./app/App');
    await demoApp.preloadRoute();
    App = demoApp.App;
  }
  root.render(<StrictMode><ErrorBoundary><App /></ErrorBoundary></StrictMode>);
}

void start();
