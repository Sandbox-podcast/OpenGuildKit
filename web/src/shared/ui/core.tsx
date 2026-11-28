/** Design system primitives. Each one covers rest, hover, focus, active, busy, error and disabled states. */
import { useId, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react';
import { Icon, type PixelIconName } from '@/shared/pixel/icons';
import type { Tone } from '@/shared/tone';

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'danger' | 'ai' | 'ghost'; size?: 'small'; icon?: PixelIconName; busy?: boolean };
export function Button({ variant, size, icon, busy, className, children, ...rest }: BtnProps) {
  return (
    <button type="button" {...rest} aria-busy={busy || undefined} className={['btn', variant, size, !children && 'icon', className].filter(Boolean).join(' ')}>
      {icon && <Icon name={icon} size={16} />}
      {children}
    </button>
  );
}

export function Panel({ title, actions, tone, className, children, as: Tag = 'section', id }: { title?: ReactNode; actions?: ReactNode; tone?: 'ai' | 'danger' | 'warn' | 'success'; className?: string; children: ReactNode; as?: 'section' | 'div' | 'article' | 'aside'; id?: string }) {
  const hid = useId();
  return (
    <Tag className={['panel', tone, className].filter(Boolean).join(' ')} aria-labelledby={title ? hid : undefined} id={id}>
      {(title || actions) && (
        <header>
          {title && <h2 id={hid} className="h-panel">{title}</h2>}
          {actions && <div className="row">{actions}</div>}
        </header>
      )}
      {children}
    </Tag>
  );
}

export function Badge({ tone = 'neutral', icon, children, title }: { tone?: Tone; icon?: PixelIconName; children: ReactNode; title?: string }) {
  return <span className={`badge tone-${tone}`} title={title}>{icon && <Icon name={icon} size={12} />}{children}</span>;
}

export function Notice({ tone = 'info', icon, children, title }: { tone?: 'info' | 'warn' | 'danger' | 'ai' | 'success'; icon?: PixelIconName; title?: string; children: ReactNode }) {
  const def: Record<string, PixelIconName> = { info: 'question', warn: 'warn', danger: 'warn', ai: 'ai', success: 'check' };
  return (
    <div className={`notice ${tone === 'info' ? '' : tone}`} role={tone === 'danger' ? 'alert' : undefined}>
      <Icon name={icon ?? def[tone]} size={16} />
      <div>{title && <strong>{title} </strong>}{children}</div>
    </div>
  );
}

export function Empty({ title, children, action, art }: { title: string; children?: ReactNode; action?: ReactNode; art?: ReactNode }) {
  return (
    <div className="empty">
      {art}
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

interface FieldShell { label: ReactNode; hint?: ReactNode; error?: string | null; className?: string }
function Shell({ label, hint, error, className, id, children }: FieldShell & { id: string; children: ReactNode }) {
  return (
    <div className={`field ${className ?? ''}`} data-invalid={error ? 'true' : undefined}>
      <label htmlFor={id}>{label}</label>
      {children}
      {hint && <span className="hint" id={`${id}-hint`}>{hint}</span>}
      {error && <span className="error" id={`${id}-err`} role="alert"><Icon name="warn" size={14} />{error}</span>}
    </div>
  );
}
const describedBy = (id: string, hint?: ReactNode, error?: string | null) => [hint && `${id}-hint`, error && `${id}-err`].filter(Boolean).join(' ') || undefined;

export function TextField({ label, hint, error, className, id: fieldId, ...rest }: FieldShell & InputHTMLAttributes<HTMLInputElement>) {
  const generatedId = useId();
  const id = fieldId ?? generatedId;
  return <Shell {...{ label, hint, error, className, id }}><input id={id} aria-invalid={!!error} aria-describedby={describedBy(id, hint, error)} {...rest} /></Shell>;
}
export function TextArea({ label, hint, error, className, id: fieldId, ...rest }: FieldShell & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const generatedId = useId();
  const id = fieldId ?? generatedId;
  return <Shell {...{ label, hint, error, className, id }}><textarea id={id} aria-invalid={!!error} aria-describedby={describedBy(id, hint, error)} {...rest} /></Shell>;
}
export function Select({ label, hint, error, className, id: fieldId, options, placeholder, ...rest }: FieldShell & SelectHTMLAttributes<HTMLSelectElement> & { options: { value: string; label: string; disabled?: boolean }[]; placeholder?: string }) {
  const generatedId = useId();
  const id = fieldId ?? generatedId;
  return (
    <Shell {...{ label, hint, error, className, id }}>
      <select id={id} aria-invalid={!!error} aria-describedby={describedBy(id, hint, error)} {...rest}>
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((o) => <option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>)}
      </select>
    </Shell>
  );
}
export function Checkbox({ label, ...rest }: { label: ReactNode } & InputHTMLAttributes<HTMLInputElement>) {
  return <label className="check"><input type="checkbox" {...rest} /><span>{label}</span></label>;
}
/** Multiple choice rendered as toggle chips (keyboard accessible checkboxes). */
export function Choices({ legend, options, value, onChange, multiple, disabled }: { legend: ReactNode; options: string[]; value: string[]; onChange: (v: string[]) => void; multiple?: boolean; disabled?: boolean }) {
  const name = useId();
  return (
    <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
      <legend className="label" style={{ fontWeight: 600, fontSize: '0.9rem', marginBottom: 4 }}>{legend}</legend>
      <div className="choice-group">
        {options.map((o) => (
          <label className="choice" key={o}>
            <input type={multiple ? 'checkbox' : 'radio'} name={name} checked={value.includes(o)} disabled={disabled}
              onChange={(e) => onChange(multiple ? (e.target.checked ? [...value, o] : value.filter((x) => x !== o)) : [o])} />
            <span>{o}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export interface TabDef { id: string; label: ReactNode; icon?: PixelIconName; count?: number }
/** Accessible tabs (arrow keys move between tabs). */
export function Tabs({ tabs, value, onChange, onKeyboardChange, label }: {
  tabs: TabDef[]; value: string; onChange: (id: string) => void;
  onKeyboardChange?: (id: string, tab: HTMLButtonElement) => void; label: string;
}) {
  return (
    <div className="tabs" role="tablist" aria-label={label}
      onKeyDown={(e) => {
        if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
        const i = tabs.findIndex((t) => t.id === value);
        const next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
        if (!next) return;
        const button = e.currentTarget.querySelector<HTMLButtonElement>(`[data-tab="${CSS.escape(next.id)}"]`);
        if (!button) return;
        e.preventDefault();
        if (onKeyboardChange) {
          onKeyboardChange(next.id, button);
          return;
        }
        onChange(next.id);
        requestAnimationFrame(() => button.focus());
      }}>
      {tabs.map((t) => (
        <button key={t.id} role="tab" data-tab={t.id} aria-selected={t.id === value} tabIndex={t.id === value ? 0 : -1} onClick={() => onChange(t.id)}>
          {t.icon && <Icon name={t.icon} size={14} />}{t.label}{t.count !== undefined && t.count > 0 && <span className="badge count">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Segmented<T extends string>({ value, onChange, options, label }: { value: T; onChange: (v: T) => void; options: { value: T; label: string; icon?: PixelIconName }[]; label: string }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => <button key={o.value} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>{o.icon && <Icon name={o.icon} size={14} />}{o.label}</button>)}
    </div>
  );
}

export function Progress({ value, label }: { value: number; label: string }) {
  return <div className="progress" role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100} aria-label={label}><span style={{ width: `${value}%` }} /></div>;
}

export function KV({ items }: { items: [ReactNode, ReactNode][] }) {
  return <dl className="kv">{items.map(([k, v], i) => <div key={i} style={{ display: 'contents' }}><dt>{k}</dt><dd>{v ?? '—'}</dd></div>)}</dl>;
}

export function Stat({ value, label, tone }: { value: ReactNode; label: string; tone?: Tone }) {
  return <div className="stat"><strong style={{ color: tone ? `var(--${tone === 'info' ? 'data' : tone})` : undefined }}>{value}</strong><span className="small muted">{label}</span></div>;
}
