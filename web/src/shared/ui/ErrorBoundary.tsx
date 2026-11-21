/**
 * Keeps a failing place from blanking the whole page. A chunk that no longer exists (the interface was
 * rebuilt or upgraded while the page stayed open) asks for a reload; any other error shows its message.
 */
import { Component, type ReactNode } from 'react';

interface State { error: Error | null }

export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State { return { error }; }

  componentDidUpdate(previous: { resetKey?: string }) {
    if (previous.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    const stale = /dynamically imported module|Importing a module script failed|error loading dynamically/i.test(error.message);
    return (
      <div className="empty" role="alert">
        <h3>{stale ? 'L’interface a été mise à jour' : 'Ce lieu n’a pas pu s’afficher'}</h3>
        <p>{stale ? 'Rechargez la page pour charger la nouvelle version.' : error.message}</p>
        <button type="button" className="btn primary" onClick={() => window.location.reload()}>Recharger la page</button>
      </div>
    );
  }
}
