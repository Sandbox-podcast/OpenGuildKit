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

// Served by `openguildkit ui`, the page opens the project of that server. Anywhere else (`npm run dev`
// without OGK_API, or ?demo=1) it opens the Atelier Nova demonstration, which only `npm run dev` and
// `npm run build:demo` include: the build that the wheel ships says how to start it instead.

function Splash() {
  return <div className="splash" role="status"><img src="./assets/brand/favicon.png" alt="" width={48} height={48} /><span>Ouverture de la guilde…</span></div>;
}

function DemoNotIncluded() {
  return (
    <main className="splash" style={{ padding: '24px 16px', textAlign: 'center' }}>
      <img src="./assets/brand/favicon.png" alt="" width={48} height={48} />
      <h1 style={{ fontSize: '1.4rem', margin: 0 }}>La démonstration n'est pas incluse</h1>
      <p style={{ margin: 0, maxWidth: '60ch' }}>Cette page est l'interface de ton projet : ouvre-la avec <code>openguildkit ui</code>, dans le dossier du projet.</p>
      <p style={{ margin: 0, maxWidth: '60ch' }}>La démonstration Atelier Nova ne fait pas partie du paquet. Lance-la depuis un clone du dépôt, puis ouvre http://localhost:5199 :</p>
      <pre style={{ textAlign: 'left', margin: 0 }}><code>cd web{'\n'}npm ci --ignore-scripts{'\n'}npm run dev</code></pre>
    </main>
  );
}

async function start() {
  const demo = new URLSearchParams(window.location.search).has('demo');
  // `openguildkit ui` marks its page: the project code then downloads while the session is read.
  const served = !demo && !!document.querySelector('meta[name="openguildkit-ui"]');
  if (served) void import('./project/ProjectApp');
  const session = demo ? null : await detectSession();
  document.documentElement.dataset.app = session ? 'project' : 'demo';
  document.title = session ? `${session.project.name} · Open Guild Kit` : __OGK_DEMO__ ? 'Open Guild Kit — Démonstration interactive' : 'Open Guild Kit';
  const root = createRoot(document.getElementById('root')!);
  root.render(<Splash />);
  // The app and the screen of the address are loaded before the first render: no screen waits on a chunk.
  let App: ComponentType;
  if (session) {
    const project = await import('./project/ProjectApp');
    await project.preloadRoute(session.project.initialized);
    App = project.ProjectApp;
  } else if (__OGK_DEMO__) {
    const demoApp = await import('./app/App');
    await demoApp.preloadRoute();
    App = demoApp.App;
  } else {
    App = DemoNotIncluded;
  }
  root.render(<StrictMode><ErrorBoundary><App /></ErrorBoundary></StrictMode>);
}

void start();
