import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

/**
 * Contrasts computed from the tokens of the stylesheets: the table of docs/accessibilite.md follows them, a text stays
 * at 4.5:1 and the edge of a control at 3:1 (the WCAG thresholds; the number of each criterion is to be verified).
 */
const read = (path: string) => readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8');

interface Rule { selector: string; declarations: Record<string, string> }
function rulesOf(file: string): Rule[] {
  const css = read(file).replace(/\/\*[\s\S]*?\*\//g, '');
  return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, selector, body]) => ({
    selector: selector.trim().replace(/\s+/g, ' '),
    declarations: Object.fromEntries(body.split(';').map((d) => d.split(/:(.*)/s).map((part) => part.trim())).filter(([name, value]) => name && value)),
  }));
}
const ruleOf = (file: string, selector: string) => {
  const found = rulesOf(file).filter((rule) => rule.selector === selector);
  expect(found, `${selector} in ${file}`).toHaveLength(1);
  return found[0].declarations;
};

type Palette = Record<string, string>;
/** RPG: the tokens of `:root`. Pro: the same, with what the light palette of pro.css replaces. */
const rpg: Palette = ruleOf('src/styles/tokens.css', ':root');
const pro: Palette = { ...rpg, ...ruleOf('src/styles/pro.css', ':root:has(.app.mode-focus)') };

function luminance(token: string, palette: Palette) {
  const value = palette[token];
  expect(value, `token ${token}`).toMatch(/^#[0-9a-f]{6}$/i);
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(value.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const ratio = (foreground: string, background: string, palette: Palette) => {
  const [light, dark] = [luminance(foreground, palette), luminance(background, palette)].sort((a, b) => b - a);
  return (light + 0.05) / (dark + 0.05);
};

/* The words of the page's table, and the token each one names. */
const FOREGROUND: Record<string, string> = {
  'Texte principal': '--text', 'Texte secondaire': '--text-2', 'Texte tertiaire': '--text-3', 'Texte atténué': '--muted',
  'Encre du bouton principal': '--accent-ink', 'Lien et contour de focus': '--data', 'Lien actif': '--accent-strong',
  'Avertissement': '--warning', 'Erreur': '--danger', 'Réussite': '--success', 'Texte de simulation': '--ai', 'Simulation et IA': '--ai',
  'Bordure forte et contour d\'un champ': '--border-strong', 'Contour d\'un champ': '--border-strong',
};
const BACKGROUND: Record<string, string> = {
  'Panneau': '--surface', 'Surface haute': '--surface-3', 'Fond de page': '--bg', 'Fond profond': '--bg-deep', 'Menthe': '--accent', 'Vert d\'action': '--accent',
  'Teinte de sélection': '--tint-data', 'Teinte de réussite': '--tint-success', 'Teinte d\'avertissement': '--tint-warning', 'Teinte d\'erreur': '--tint-danger', 'Teinte IA': '--tint-ai',
};

interface Row { foreground: string; background: string; shown: number; edge: boolean }
const page = read('docs/accessibilite.md').split('## Contrastes mesurés')[1].split('\n## ')[0];
function table(text: string): Row[] {
  return text.split('\n').filter((line) => line.startsWith('| ') && !/^\| (Premier plan|---)/.test(line)).map((line) => {
    const [foreground, background, value] = line.split('|').slice(1, -1).map((cell) => cell.trim());
    return { foreground, background, shown: Number(value.replace(':1', '').replace(',', '.')), edge: /^(Bordure|Contour)/.test(foreground) };
  });
}
const [rpgText, proText] = page.split('Le style Pro');
/** The ratio of a row of the page, from the tokens its two words name. */
function computed(row: Row, palette: Palette) {
  expect(FOREGROUND[row.foreground], `the test does not know « ${row.foreground} »`).toBeDefined();
  expect(BACKGROUND[row.background], `the test does not know « ${row.background} »`).toBeDefined();
  return ratio(FOREGROUND[row.foreground], BACKGROUND[row.background], palette);
}
const TABLES = [{ style: 'RPG', palette: rpg, rows: table(rpgText) }, { style: 'Pro', palette: pro, rows: table(proText) }];

describe('contrasts of the tokens', () => {
  it('are the ones the table of the accessibility page gives', () => {
    const stale = TABLES.flatMap(({ style, palette, rows }) => rows.map((row) => ({ row, value: computed(row, palette), style }))
      .filter(({ row, value }) => Math.abs(value - row.shown) > 0.005)
      .map(({ row, value, style: s }) => `${s}: ${row.foreground} sur ${row.background}: page ${row.shown}, jetons ${value.toFixed(2)}`));
    expect(stale).toEqual([]);
  });

  it('keep a text at 4.5:1 and the edge of a control at 3:1', () => {
    const below = TABLES.flatMap(({ style, palette, rows }) => rows.map((row) => ({ row, value: computed(row, palette), style }))
      .filter(({ row, value }) => value < (row.edge ? 3 : 4.5))
      .map(({ row, value, style: s }) => `${s}: ${row.foreground} sur ${row.background}: ${value.toFixed(2)}`));
    expect(below).toEqual([]);
  });
});

describe('edge of a field', () => {
  const resting = [
    { rule: '.input', file: 'src/styles/project.css' },
    { rule: '.field input, .field select, .field textarea', file: 'src/styles/components.css' },
  ];

  /** Issue #471: the edge of a field at rest was 1.29:1 in Pro and 2.09:1 in RPG, under 3:1. */
  it.each(resting)('at rest reaches 3:1 on its fill, the panel and the page in both styles: $rule', ({ rule, file }) => {
    const edge = /^var\((--[\w-]+)\)$/.exec(ruleOf(file, rule)['--edge'])?.[1];
    expect(edge).toBeDefined();
    const low = TABLES.flatMap(({ style, palette }) => ['--bg-deep', '--surface', '--bg'].map((behind) => ({ label: `${style} ${edge} sur ${behind}`, computed: ratio(edge!, behind, palette) })))
      .filter(({ computed }) => computed < 3).map(({ label, computed }) => `${label}: ${computed.toFixed(2)}`);
    expect(low).toEqual([]);
  });

  /** Issue #471: in Pro the focus of an `.input` outside a `.field` only recolored a 1 px edge. */
  it('shows a 2 px outline on the focus of an .input in Pro, as a .field does', () => {
    expect(ruleOf('src/styles/pro.css', '.mode-focus .field :is(input, select, textarea):focus').outline).toMatch(/^2px solid/);
    expect(ruleOf('src/styles/project.css', '.mode-focus .input:focus').outline).toMatch(/^2px solid/);
  });
});
