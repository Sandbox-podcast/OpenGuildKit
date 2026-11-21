import type { ReactNode } from 'react';
import './Button.css';

export interface ButtonProps {
  variant?: 'primary' | 'secondary' | 'danger';
  size?: 'sm' | 'md';
  disabled?: boolean;
  children: ReactNode;
  onClick?: () => void;
}

export function Button({ variant = 'primary', size = 'md', disabled = false, children, onClick }: ButtonProps) {
  return (
    <button className={`button button--${variant} button--${size}`} disabled={disabled} onClick={onClick}>
      {children}
    </button>
  );
}
