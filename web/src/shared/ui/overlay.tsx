/** Dialogs, drawers, menus and toasts. Native <dialog> keeps focus inside; focus returns to the trigger. */
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { Icon } from '@/shared/pixel/icons';
import { Button, TextArea } from './core';
import { dismissToast, useToasts } from './toast';

export function Dialog({ open, onClose, title, children, footer, wide, drawer }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean; drawer?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  const trigger = useRef<Element | null>(null);
  const headingId = useId();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      trigger.current = document.activeElement;
      d.showModal();
      (d.querySelector('[autofocus], input, select, textarea, button:not(.dialog-close)') as HTMLElement | null)?.focus();
    }
    if (!open && d.open) {
      d.close();
      (trigger.current as HTMLElement | null)?.focus?.();
    }
  }, [open]);
  useEffect(() => () => { (trigger.current as HTMLElement | null)?.focus?.(); }, []);
  return (
    <dialog ref={ref} className={`dialog ${wide ? 'wide' : ''} ${drawer ? 'drawer' : ''}`} onCancel={(e) => { e.preventDefault(); onClose(); }} aria-labelledby={headingId}>
      {open && (
        <>
          <div className="dialog-head">
            <h2 id={headingId}>{title}</h2>
            <Button variant="ghost" icon="close" className="dialog-close" aria-label="Fermer" onClick={onClose} />
          </div>
          <div className="dialog-body">{children}</div>
          {footer && <div className="dialog-foot">{footer}</div>}
        </>
      )}
    </dialog>
  );
}

/** Asks for a confirmation, optionally with a mandatory reason (blocking, cancelling, reopening…). */
export function ConfirmDialog({ open, title, message, confirmLabel, danger, needsReason, reasonLabel = 'Motif', onConfirm, onClose, extra }: {
  open: boolean; title: string; message?: ReactNode; confirmLabel: string; danger?: boolean; needsReason?: boolean; reasonLabel?: string;
  onConfirm: (reason: string) => void; onClose: () => void; extra?: ReactNode;
}) {
  const [reason, setReason] = useState('');
  const [touched, setTouched] = useState(false);
  useEffect(() => { if (open) { setReason(''); setTouched(false); } }, [open]);
  const missing = needsReason && reason.trim().length < 3;
  return (
    <Dialog open={open} onClose={onClose} title={title}
      footer={<>
        <Button onClick={onClose}>Annuler</Button>
        <Button variant={danger ? 'danger' : 'primary'} onClick={() => { setTouched(true); if (!missing) onConfirm(reason.trim()); }}>{confirmLabel}</Button>
      </>}>
      {message && <div className="stack tight" style={{ marginBottom: 12 }}>{message}</div>}
      {extra}
      {needsReason && <TextArea label={reasonLabel} value={reason} onChange={(e) => setReason(e.target.value)} error={touched && missing ? 'Un motif est requis pour cette action.' : null} hint="Le motif est conservé dans l’historique." />}
    </Dialog>
  );
}

export function Drawer({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode }) {
  return <Dialog drawer open={open} onClose={onClose} title={title}>{children}</Dialog>;
}

/** Popover menu with keyboard support (Escape closes, arrows move). */
export function Menu({ label, trigger, children, align = 'left' }: { label: string; trigger: (props: { onClick: () => void; 'aria-expanded': boolean; 'aria-haspopup': 'menu' }) => ReactNode; children: (close: () => void) => ReactNode; align?: 'left' | 'right' }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setOpen(false); (ref.current?.querySelector('[aria-haspopup]') as HTMLElement | null)?.focus(); }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        const items = [...(ref.current?.querySelectorAll<HTMLElement>('.menu-pop button:not(:disabled), .menu-pop a') ?? [])];
        const i = items.indexOf(document.activeElement as HTMLElement);
        items[(i + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length]?.focus();
        e.preventDefault();
      }
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    const frame = requestAnimationFrame(() => ref.current?.querySelector<HTMLElement>('.menu-pop button:not(:disabled), .menu-pop a')?.focus());
    return () => { cancelAnimationFrame(frame); document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey); };
  }, [open]);
  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-block' }}>
      {trigger({ onClick: () => setOpen((o) => !o), 'aria-expanded': open, 'aria-haspopup': 'menu' })}
      {open && <div className="menu-pop" role="menu" aria-label={label} style={align === 'right' ? { right: 0 } : { left: 0 }}>{children(() => setOpen(false))}</div>}
    </div>
  );
}

export function Toasts() {
  const toasts = useToasts();
  const icons = { success: 'check', danger: 'warn', info: 'question', warning: 'warn' } as const;
  return (
    <div className="toasts" aria-live="polite" aria-atomic="false">
      {toasts.map((t) => (
        <div key={t.id} className={`toast tone-${t.tone}`} role={t.tone === 'danger' ? 'alert' : 'status'}>
          <Icon name={icons[t.tone]} size={16} />
          <div className="grow"><strong>{t.title}</strong>{t.text && <span className="small muted">{t.text}</span>}</div>
          <button className="btn ghost icon small" aria-label="Fermer la notification" onClick={() => dismissToast(t.id)}><Icon name="close" size={12} /></button>
        </div>
      ))}
    </div>
  );
}
