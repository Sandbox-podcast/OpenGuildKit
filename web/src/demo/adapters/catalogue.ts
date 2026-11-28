/**
 * Reference catalogue adapter.
 *
 * The source of truth is the Markdown catalogue supplied for the demo
 * (data/SOCLE_Catalogue_395_References.md). `npm run catalogue` converts it to
 * src/fixtures/catalogue.json; the in-app importer uses the same parser so a
 * new edition of the file (Markdown or JSON) goes through identical validation.
 */
import { z } from 'zod';
import { isSafeUrl } from '@/shared/text';

export const NATURE_GROUPS = {
  norme: 'Norme',
  standard: 'Standard ou spécification',
  convention: 'Convention',
  methode: 'Méthode, pratique ou principe',
  referentiel: 'Référentiel ou taxonomie',
  reglementation: 'Réglementation',
  protocole: 'Protocole, format ou vocabulaire',
  outil: 'Outil',
  indicateur: 'Indicateur ou objectif',
  attestation: 'Attestation',
} as const;
export type NatureGroup = keyof typeof NATURE_GROUPS;

export const PUBLICATION_STATUS = {
  published: 'Publiée par sa source',
  draft: 'Projet ou version provisoire',
  emerging: 'Spécification émergente',
} as const;
export type PublicationStatus = keyof typeof PUBLICATION_STATUS;

const sourceSchema = z.object({ label: z.string().min(1), url: z.string().url().refine(isSafeUrl, 'URL non autorisée') });
export const referenceSchema = z.object({
  id: z.string().regex(/^[a-z0-9-]+$/),
  name: z.string().min(1),
  nature: z.string().min(1),
  natureGroup: z.enum(Object.keys(NATURE_GROUPS) as [NatureGroup, ...NatureGroup[]]),
  family: z.string().min(1),
  familyId: z.string(),
  category: z.string().min(1),
  categoryId: z.string(),
  description: z.string().min(1),
  whenToUse: z.string(),
  sources: z.array(sourceSchema).min(1),
  publicationStatus: z.enum(Object.keys(PUBLICATION_STATUS) as [PublicationStatus, ...PublicationStatus[]]),
  statusNote: z.string().optional(),
  edition: z.string(),
});
export type Reference = z.infer<typeof referenceSchema>;

export const catalogueSchema = z.object({
  format: z.literal('ogk-catalogue/1'),
  edition: z.string(),
  title: z.string(),
  notice: z.string(),
  declared: z.object({ references: z.number(), categories: z.number(), families: z.number() }),
  references: z.array(referenceSchema),
});
export type Catalogue = z.infer<typeof catalogueSchema>;

export interface ParseIssue {
  line: number;
  message: string;
}
export interface ParseResult {
  catalogue: Catalogue;
  issues: ParseIssue[];
}

export { isSafeUrl };

export function slugify(text: string): string {
  return text
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/\+\+/g, 'pp')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64);
}

export function natureGroupOf(nature: string): NatureGroup {
  const n = nature.toLowerCase();
  const rules: [RegExp, NatureGroup][] = [
    [/^norme/, 'norme'],
    [/^attestation/, 'attestation'],
    [/^r[ée]glementation/, 'reglementation'],
    [/^(r[ée]f[ée]rentiel|taxonomie)/, 'referentiel'],
    [/^convention/, 'convention'],
    [/^outil/, 'outil'],
    [/^(indicateur|objectif)/, 'indicateur'],
    [/^(protocole|format|vocabulaire|encodage)/, 'protocole'],
    [/^(standard|sp[ée]cification|recommandation|[ée]cosyst[èe]me)/, 'standard'],
  ];
  return rules.find(([re]) => re.test(n))?.[1] ?? 'methode';
}

function statusOf(name: string, nature: string, description: string): { status: PublicationStatus; note?: string } {
  const text = `${name} ${nature} ${description}`;
  if (/[ée]mergente?/i.test(text)) return { status: 'emerging', note: 'Présentée comme émergente par sa source.' };
  if (/\(draft\)|\bdraft\b|candidate/i.test(text)) {
    return { status: 'draft', note: 'Présentée par sa source comme un projet ou une recommandation candidate.' };
  }
  return { status: 'published' };
}

const SOURCE_RE = /\[Source \d+:\s*((?:[^\]\\]|\\.)+)\]\((https?:\/\/[^\s)]+(?:\([^\s)]*\)[^\s)]*)*)\)/g;

/** Parses the Markdown catalogue. Never throws: problems are returned as issues. */
export function parseCatalogueMarkdown(markdown: string): ParseResult {
  const issues: ParseIssue[] = [];
  const lines = markdown.replace(/\r\n/g, '\n').split('\n');
  const edition = /\*\*[ÉE]dition\s*:\s*([^*]+)\*\*/.exec(markdown)?.[1].trim() ?? 'inconnue';
  const title =
    lines
      .find((l) => l.startsWith('# '))
      ?.slice(2)
      .trim() ?? 'Catalogue';
  const declaredMatch = /\*\*(\d+)\s+r[ée]f[ée]rences\s*·\s*(\d+)\s+cat[ée]gories\s*·\s*(\d+)\s+familles/i.exec(markdown);
  const notice = /\*\*Statut\s*:\s*([^*]+)\*\*/.exec(markdown)?.[1].trim() ?? '';
  const references: Reference[] = [];
  let family = '';
  let category = '';
  lines.forEach((raw, index) => {
    const line = raw.trim();
    const lineNo = index + 1;
    const fam = /^##\s+\d+\.\s+(.+?)\s+—\s+\d+\s+r[ée]f[ée]rences/.exec(line);
    if (fam) {
      family = fam[1].trim();
      category = '';
      return;
    }
    if (/^##\s/.test(line)) {
      family = '';
      category = '';
      return;
    }
    const cat = /^###\s+(.+?)\s+\((\d+)\)\s*$/.exec(line);
    if (cat) {
      category = cat[1].trim();
      return;
    }
    if (!line.startsWith('| **') || !family || !category) return;
    const cells = line
      .replace(/^\|\s*/, '')
      .replace(/\s*\|$/, '')
      .split(' | ');
    if (cells.length < 5) {
      issues.push({ line: lineNo, message: 'Ligne de tableau incomplète (5 colonnes attendues).' });
      return;
    }
    const [nameCell, nature, description, whenToUse] = cells;
    const sourcesCell = cells.slice(4).join(' | ');
    const name = /^\*\*(.+)\*\*$/.exec(nameCell)?.[1]?.trim();
    if (!name) {
      issues.push({ line: lineNo, message: 'Nom de référence absent ou mal formé.' });
      return;
    }
    const sources = [...sourcesCell.matchAll(SOURCE_RE)].map((m) => ({ label: m[1].trim(), url: m[2] }));
    if (sources.length === 0) issues.push({ line: lineNo, message: `« ${name} » n'a aucune source lisible.` });
    const unsafe = sources.filter((s) => !isSafeUrl(s.url));
    if (unsafe.length) issues.push({ line: lineNo, message: `« ${name} » contient une URL refusée.` });
    const { status, note } = statusOf(name, nature, description);
    references.push({
      id: slugify(name),
      name,
      nature: nature.trim(),
      natureGroup: natureGroupOf(nature),
      family,
      familyId: slugify(family),
      category,
      categoryId: slugify(category),
      description: description.trim(),
      whenToUse: whenToUse.trim(),
      sources: sources.filter((s) => isSafeUrl(s.url)),
      publicationStatus: status,
      ...(note ? { statusNote: note } : {}),
      edition,
    });
  });
  dedupeIds(references);
  const declared = declaredMatch
    ? { references: +declaredMatch[1], categories: +declaredMatch[2], families: +declaredMatch[3] }
    : { references: 0, categories: 0, families: 0 };
  return {
    catalogue: { format: 'ogk-catalogue/1', edition, title, notice, declared, references },
    issues,
  };
}

/** Stable ids: slug of the name, suffixed by the category slug on collision. */
function dedupeIds(references: Reference[]): void {
  const seen = new Map<string, number>();
  for (const r of references) {
    if (!seen.has(r.id)) {
      seen.set(r.id, 1);
      continue;
    }
    let id = `${r.id}-${r.categoryId}`.slice(0, 80);
    let n = 2;
    while (seen.has(id)) id = `${r.id}-${n++}`;
    seen.set(id, 1);
    r.id = id;
  }
}

export interface CatalogueStats {
  references: number;
  categories: number;
  families: number;
  byFamily: Record<string, number>;
}
export function catalogueStats(refs: Reference[]): CatalogueStats {
  const byFamily: Record<string, number> = {};
  refs.forEach((r) => (byFamily[r.family] = (byFamily[r.family] ?? 0) + 1));
  return {
    references: refs.length,
    categories: new Set(refs.map((r) => `${r.familyId}/${r.categoryId}`)).size,
    families: Object.keys(byFamily).length,
    byFamily,
  };
}

/** Normalised key used to match duplicates across imports (name without accents/punctuation). */
export const duplicateKey = (name: string) => slugify(name).replace(/-/g, '');

export type ImportDecision = 'add' | 'update' | 'skip';
export interface ImportRow {
  incoming: Reference;
  existing?: Reference;
  changes: string[];
  decision: ImportDecision;
}
export interface ImportPreview {
  rows: ImportRow[];
  errors: ParseIssue[];
  format: 'markdown' | 'json';
}

/** Parses an imported file (Markdown or JSON) and matches it against the current catalogue. */
export function previewCatalogueImport(text: string, current: Reference[]): ImportPreview {
  let refs: Reference[] = [];
  let errors: ParseIssue[] = [];
  let format: ImportPreview['format'] = 'markdown';
  const trimmed = text.trim();
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    format = 'json';
    try {
      const data = JSON.parse(trimmed);
      const parsed = catalogueSchema.safeParse(data);
      if (parsed.success) refs = parsed.data.references;
      else errors = parsed.error.issues.slice(0, 20).map((i) => ({ line: 0, message: `${i.path.join('.')} : ${i.message}` }));
    } catch (e) {
      errors = [{ line: 0, message: `JSON illisible : ${(e as Error).message}` }];
    }
  } else {
    const result = parseCatalogueMarkdown(text);
    refs = result.catalogue.references;
    errors = result.issues;
    if (refs.length === 0 && errors.length === 0) errors.push({ line: 0, message: 'Aucune référence reconnue dans ce fichier.' });
  }
  const byKey = new Map(current.map((r) => [duplicateKey(r.name), r]));
  const rows: ImportRow[] = refs.map((incoming) => {
    const existing = byKey.get(duplicateKey(incoming.name));
    if (!existing) return { incoming, changes: [], decision: 'add' };
    const fields = ['nature', 'description', 'whenToUse', 'category', 'family', 'edition'] as const;
    const changes: string[] = fields.filter((k) => existing[k] !== incoming[k]);
    if (JSON.stringify(existing.sources) !== JSON.stringify(incoming.sources)) changes.push('sources');
    return { incoming: { ...incoming, id: existing.id }, existing, changes, decision: changes.length ? 'update' : 'skip' };
  });
  return { rows, errors, format };
}
