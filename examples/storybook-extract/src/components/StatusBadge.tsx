import './StatusBadge.css';

type Status = 'open' | 'waiting' | 'closed';

export const StatusBadge = ({ status, label }: { status: Status; label: string }) => (
  <span className={`badge badge--${status}`}>{label}</span>
);
