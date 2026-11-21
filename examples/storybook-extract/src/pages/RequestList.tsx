import { Button } from '../components/Button';
import { StatusBadge } from '../components/StatusBadge';

// Synthetic requests: the screen the team selected for the extraction.
export function RequestList() {
  return (
    <main>
      <header>
        <h1>Support requests</h1>
        <Button size="sm" variant="secondary">Filter</Button>
        <Button>New request</Button>
      </header>
      <ul>
        <li>Printer offline <StatusBadge status="open" label="Open" /></li>
        <li>Invoice copy <StatusBadge status="waiting" label="Waiting for you" /></li>
        <li>Password reset <StatusBadge status="closed" label="Closed" /></li>
        <li>VPN access <StatusBadge status="open" label="Open" /></li>
      </ul>
    </main>
  );
}
