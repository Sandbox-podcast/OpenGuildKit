// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ActionForm } from '@/project/parts';
import { button, cleanup, click, field, mount, type } from './harness';

afterEach(cleanup);

const fields = [
  { name: 'id', label: 'Identifiant', required: true, check: (v: string) => (/^[a-z-]+$/.test(v) ? null : 'Des lettres minuscules et des tirets.') },
  { name: 'brief', label: 'Ce que l’équipe doit faire', required: true, multiline: true },
];

describe('ActionForm', () => {
  it('keeps the button off until every required field has a value', async () => {
    const { container } = await mount(<ActionForm fields={fields} submit="Ouvrir" onSubmit={vi.fn()} />);
    expect(button(container, 'Ouvrir').disabled).toBe(true);
    await type(field(container, 'Identifiant'), 'export-csv');
    expect(button(container, 'Ouvrir').disabled).toBe(true);
    await type(field(container, 'Ce que l’équipe doit faire'), '   ');
    expect(button(container, 'Ouvrir').disabled).toBe(true);
    await type(field(container, 'Ce que l’équipe doit faire'), 'Export the requests as CSV.');
    expect(button(container, 'Ouvrir').disabled).toBe(false);
  });

  it('says under a field why its value is refused, and refuses to send it', async () => {
    const onSubmit = vi.fn();
    const { container } = await mount(<ActionForm fields={fields} submit="Ouvrir" onSubmit={onSubmit} />);
    await type(field(container, 'Identifiant'), 'Export CSV');
    await type(field(container, 'Ce que l’équipe doit faire'), 'Export the requests as CSV.');
    expect(container.textContent).toContain('Des lettres minuscules et des tirets.');
    expect(field(container, 'Identifiant').getAttribute('aria-invalid')).toBe('true');
    expect(button(container, 'Ouvrir').disabled).toBe(true);
    container.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    expect(onSubmit).not.toHaveBeenCalled();
    await type(field(container, 'Identifiant'), 'export-csv');
    expect(container.textContent).not.toContain('Des lettres minuscules');
  });

  it('sends the values of its fields when the person submits', async () => {
    const onSubmit = vi.fn();
    const { container } = await mount(<ActionForm fields={fields} submit="Ouvrir" onSubmit={onSubmit} initial={{ id: 'export-csv' }} />);
    expect(field(container, 'Identifiant').value).toBe('export-csv');
    await type(field(container, 'Ce que l’équipe doit faire'), 'Export the requests as CSV.');
    await click(button(container, 'Ouvrir'));
    expect(onSubmit).toHaveBeenCalledOnce();
    expect(onSubmit).toHaveBeenCalledWith({ id: 'export-csv', brief: 'Export the requests as CSV.' });
  });
});
