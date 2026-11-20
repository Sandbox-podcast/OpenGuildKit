import { Button } from '../components/Button';
import { StatusBadge } from '../components/StatusBadge';

export function RequestDetail({ onClose }: { onClose: () => void }) {
  return (
    <section>
      <h2>Password reset <StatusBadge status="closed" label="Closed" /></h2>
      <Button variant="secondary" onClick={onClose}>Back</Button>
      <Button variant="danger" disabled>Delete</Button>
      <Button>Reopen</Button>
    </section>
  );
}
