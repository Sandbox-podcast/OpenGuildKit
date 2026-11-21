import { useSyncExternalStore } from 'react';

export interface Toast { id: number; tone: 'success' | 'danger' | 'info' | 'warning'; title: string; text?: string }
let toasts: Toast[] = [];
let seq = 0;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export function toast(t: Omit<Toast, 'id'>) {
  const id = ++seq;
  toasts = [...toasts.slice(-2), { ...t, id }];
  emit();
  setTimeout(() => dismissToast(id), t.tone === 'danger' ? 9000 : 3500);
}
export function dismissToast(id: number) { toasts = toasts.filter((t) => t.id !== id); emit(); }
export const useToasts = () => useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => toasts);
