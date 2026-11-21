/**
 * Export adapter. Every format offered by a button is really produced here:
 * Markdown, JSON, YAML, standalone HTML and SVG. Texts are escaped; exported HTML contains
 * no external resource. Simulated or fictional content is labelled inside the file.
 */
import type { Content, Deliverable, DeliverableVersion } from '@/domain/types';

export type ExportFormat = 'md' | 'json' | 'yaml' | 'html' | 'svg';
export const FORMAT_LABELS: Record<ExportFormat, string> = { md: 'Markdown', json: 'JSON', yaml: 'YAML', html: 'HTML autonome', svg: 'SVG' };

export const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);

/** Minimal YAML serialiser for plain data (objects, arrays, strings, numbers, booleans, null). */
export function toYaml(value: unknown, indent = 0): string {
  const pad = '  '.repeat(indent);
  const scalar = (v: unknown) => {
    if (v === null || v === undefined) return 'null';
    if (typeof v === 'number' || typeof v === 'boolean') return String(v);
    const s = String(v);
    return /^[\w À-ÿ.,/@()-]+$/.test(s) && !/^(true|false|null|\d)/.test(s) && !s.includes(': ') ? s : JSON.stringify(s);
  };
  if (Array.isArray(value)) {
    if (!value.length) return '[]';
    return value.map((v) => (v && typeof v === 'object' ? `${pad}-\n${toYaml(v, indent + 1)}` : `${pad}- ${scalar(v)}`)).join('\n');
  }
  if (value && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).filter(([, v]) => v !== undefined);
    if (!entries.length) return `${pad}{}`;
    return entries.map(([k, v]) => {
      const key = /^[\w-]+$/.test(k) ? k : JSON.stringify(k);
      if (v && typeof v === 'object' && (!Array.isArray(v) || v.length)) return `${pad}${key}:\n${toYaml(v, indent + 1)}`;
      return `${pad}${key}: ${Array.isArray(v) ? '[]' : scalar(v)}`;
    }).join('\n');
  }
  return pad + scalar(value);
}

const header = (title: string, meta: string[]) => `<!-- ${meta.join(' · ')} -->\n# ${title}\n\n`;

export function contentToMarkdown(c: Content, title: string): string {
  switch (c.kind) {
    case 'markdown': return c.body;
    case 'files': return `# ${title}\n\n${c.files.map((f) => `## ${f.path}\n\n\`\`\`${f.language}\n${f.body}\`\`\`\n`).join('\n')}`;
    case 'api': return `# ${title}\n\n\`\`\`yaml\n${c.spec}\`\`\`\n`;
    case 'component': return `# ${c.name}\n\n${c.description}\n\n## États\n${c.variants.map((v) => `- **${v.name}** : ${Object.entries(v.props).map(([k, val]) => `${k}=${val}`).join(', ')}`).join('\n')}\n\n## Vérifications\n${c.checks.map((x) => `- ${x}`).join('\n')}\n`;
    case 'gallery': return `# ${title}\n\n${c.intro}\n`;
    case 'roadmap': return `# ${title}\n\n| Horizon | Sujet | Statut | Note |\n| --- | --- | --- | --- |\n${c.items.map((i) => `| ${i.horizon} | ${i.title} | ${i.status} | ${i.note} |`).join('\n')}\n`;
    case 'landing': return `# ${c.hero}\n\n${c.subtitle}\n\n${c.features.map((f) => `## ${f.title}\n${f.text}`).join('\n\n')}\n\n**${c.cta}**\n\n> ${c.note}\n`;
    case 'slides': return c.slides.map((sl, i) => `## ${i + 1}. ${sl.title}\n\n${sl.bullets.map((b) => `- ${b}`).join('\n')}${sl.note ? `\n\n> Note : ${sl.note}` : ''}`).join('\n\n---\n\n');
    case 'storyboard': return `# ${title}\n\n| # | Scène | Durée | Visuel | Voix |\n| --- | --- | --- | --- | --- |\n${c.scenes.map((s, i) => `| ${i + 1} | ${s.title} | ${s.seconds} s | ${s.visual} | ${s.voice} |`).join('\n')}\n\nDurée totale : ${c.scenes.reduce((a, s) => a + s.seconds, 0)} s\n`;
  }
}

const CSS = `body{margin:0;font:16px/1.6 system-ui,sans-serif;background:#10121d;color:#f3f0e8}main{max-width:880px;margin:0 auto;padding:32px 20px}h1,h2{line-height:1.25}a{color:#69c4d4}.note{font-size:13px;color:#b9bdc9;border-left:3px solid #a78bfa;padding-left:10px;margin-top:32px}.hero{padding:56px 24px;background:#1b2030;text-align:center}.hero h1{font-size:2.2rem;margin:0 0 12px}.features{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin:24px 0}.features div{background:#1b2030;padding:16px}.cta{display:inline-block;background:#e8b86d;color:#1d1406;padding:10px 18px;font-weight:700;text-decoration:none}.slide{min-height:70vh;display:flex;flex-direction:column;justify-content:center;border-bottom:2px solid #3a4058;padding:24px}.slide h2{font-size:2rem}pre{background:#0b0d16;padding:12px;overflow:auto}`;

export function standaloneHtml(title: string, bodyHtml: string, note: string): string {
  return `<!doctype html>\n<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(title)}</title><style>${CSS}</style></head>\n<body>${bodyHtml}<main><p class="note">${esc(note)}</p></main></body></html>\n`;
}

/** HTML body of a landing page — also used for the sandboxed preview. */
export function landingBody(c: Extract<Content, { kind: 'landing' }>): string {
  return `<section class="hero"><h1>${esc(c.hero)}</h1><p>${esc(c.subtitle)}</p><a class="cta" href="#contact">${esc(c.cta)}</a></section><main><div class="features">${c.features.map((f) => `<div><h2>${esc(f.title)}</h2><p>${esc(f.text)}</p></div>`).join('')}</div><p class="note">${esc(c.note)}</p></main>`;
}

function markdownToHtml(md: string): string {
  const lines = esc(md).split('\n');
  return lines.map((l) => {
    if (/^### /.test(l)) return `<h3>${l.slice(4)}</h3>`;
    if (/^## /.test(l)) return `<h2>${l.slice(3)}</h2>`;
    if (/^# /.test(l)) return `<h1>${l.slice(2)}</h1>`;
    if (/^\s*[-*] /.test(l)) return `<li>${l.replace(/^\s*[-*] /, '')}</li>`;
    if (/^\d+\. /.test(l)) return `<li>${l.replace(/^\d+\. /, '')}</li>`;
    return l.trim() ? `<p>${l}</p>` : '';
  }).join('\n').replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
}

export function storyboardSvg(c: Extract<Content, { kind: 'storyboard' }>, title: string): string {
  const total = c.scenes.reduce((a, s) => a + s.seconds, 0) || 1;
  const W = 960; let x = 20;
  const blocks = c.scenes.map((s, i) => {
    const w = Math.max(80, ((W - 40) * s.seconds) / total);
    const out = `<g><rect x="${x}" y="60" width="${w - 6}" height="120" fill="${['#2b3250', '#3a2f55', '#2f4a4a', '#4a3a2a'][i % 4]}" stroke="#565e7e"/><text x="${x + 8}" y="84" fill="#e8b86d" font-size="14" font-family="monospace">${i + 1}. ${esc(s.title)}</text><text x="${x + 8}" y="106" fill="#f3f0e8" font-size="12" font-family="sans-serif">${esc(s.visual).slice(0, 38)}</text><text x="${x + 8}" y="168" fill="#b9bdc9" font-size="12" font-family="monospace">${s.seconds} s</text></g>`;
    x += w;
    return out;
  }).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="220" viewBox="0 0 ${W} 220"><rect width="${W}" height="220" fill="#10121d"/><text x="20" y="36" fill="#f3f0e8" font-size="18" font-family="sans-serif">${esc(title)} — ${total} s</text>${blocks}<text x="20" y="206" fill="#b9bdc9" font-size="11" font-family="sans-serif">Storyboard de démonstration (contenu simulé)</text></svg>\n`;
}

export function roadmapSvg(c: Extract<Content, { kind: 'roadmap' }>, title: string): string {
  const W = 960; const col = (W - 40) / Math.max(1, c.items.length);
  const items = c.items.map((it, i) => `<g><rect x="${20 + i * col}" y="60" width="${col - 10}" height="110" fill="#1b2030" stroke="#3a4058"/><text x="${28 + i * col}" y="82" fill="#e8b86d" font-size="13" font-family="monospace">${esc(it.horizon)}</text><text x="${28 + i * col}" y="106" fill="#f3f0e8" font-size="13" font-family="sans-serif">${esc(it.title).slice(0, 34)}</text><text x="${28 + i * col}" y="128" fill="#7dd3a8" font-size="12" font-family="sans-serif">${esc(it.status)}</text></g>`).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="200" viewBox="0 0 ${W} 200"><rect width="${W}" height="200" fill="#10121d"/><text x="20" y="36" fill="#f3f0e8" font-size="18" font-family="sans-serif">${esc(title)}</text>${items}</svg>\n`;
}

/** Formats really available for a content kind. */
export function formatsFor(c: Content): ExportFormat[] {
  const base: ExportFormat[] = ['md', 'json', 'yaml'];
  if (c.kind === 'landing' || c.kind === 'slides' || c.kind === 'markdown') base.push('html');
  if (c.kind === 'storyboard' || c.kind === 'roadmap') base.push('svg');
  return base;
}

export function exportDeliverable(d: Deliverable, v: DeliverableVersion, format: ExportFormat): { filename: string; mime: string; text: string } {
  const slug = d.title.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^\w]+/g, '-').toLowerCase().replace(/^-|-$/g, '');
  const meta = [`Open Guild Kit — démonstration interactive`, `${d.title} v${v.number}`, v.simulated ? 'Contenu généré par simulation' : 'Contenu saisi localement', `exporté le ${new Date().toLocaleString('fr-FR')}`];
  const filename = `${slug}-v${v.number}`;
  const c = v.content;
  switch (format) {
    case 'md': return { filename: `${filename}.md`, mime: 'text/markdown', text: c.kind === 'markdown' ? `<!-- ${meta.join(' · ')} -->\n${c.body}` : header(d.title, meta) + contentToMarkdown(c, d.title).replace(/^# .*\n\n/, '') };
    case 'json': return { filename: `${filename}.json`, mime: 'application/json', text: JSON.stringify({ format: 'ogk-livrable/1', simulation: v.simulated, meta, livrable: { id: d.id, titre: d.title, type: d.type, statut: d.status, version: v.number, décrit: v.describes }, contenu: c }, null, 2) };
    case 'yaml': return { filename: `${filename}.yaml`, mime: 'application/yaml', text: `# ${meta.join(' · ')}\n${toYaml({ format: 'ogk-livrable/1', simulation: v.simulated, livrable: { id: d.id, titre: d.title, type: d.type, statut: d.status, version: v.number }, contenu: c })}\n` };
    case 'html': {
      const body = c.kind === 'landing' ? landingBody(c) : c.kind === 'slides' ? c.slides.map((sl, i) => `<section class="slide"><p>${i + 1} / ${c.slides.length}</p><h2>${esc(sl.title)}</h2><ul>${sl.bullets.map((b) => `<li>${esc(b)}</li>`).join('')}</ul>${sl.note ? `<p class="note">${esc(sl.note)}</p>` : ''}</section>`).join('') : `<main>${markdownToHtml(contentToMarkdown(c, d.title))}</main>`;
      return { filename: `${filename}.html`, mime: 'text/html', text: standaloneHtml(d.title, body, meta.join(' · ')) };
    }
    case 'svg': return { filename: `${filename}.svg`, mime: 'image/svg+xml', text: c.kind === 'storyboard' ? storyboardSvg(c, d.title) : c.kind === 'roadmap' ? roadmapSvg(c, d.title) : '' };
  }
}

/** Triggers a real file download in the browser. */
export function download(filename: string, mime: string, text: string) {
  const blob = new Blob([text], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
