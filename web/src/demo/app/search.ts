/** Global search index (projects, quests, decisions, councils, documents, references, experts…). */
import { allReferences, DELIVERABLE_TYPES } from '@/demo/domain/selectors';
import { list } from '@/demo/domain/engine';
import type { AppState, Ref } from '@/demo/domain/types';
import type { Reference } from '@/demo/adapters/catalogue';

import { norm } from '@/shared/text';
export { norm };

const STOP = new Set([
  'de',
  'des',
  'du',
  'la',
  'le',
  'les',
  'sur',
  'et',
  'pour',
  'of',
  'the',
  'and',
  'for',
  'to',
  'a',
  'en',
  'au',
  'aux',
  'par',
  'd',
  'l',
]);
const MANUAL: Record<string, string[]> = {
  'semantic-versioning': ['SemVer'],
  'owasp-application-security-verification-standard-5-0-0': ['OWASP ASVS', 'ASVS'],
  'reglement-general-sur-la-protection-des-donnees-ue-2016-679': ['RGPD', 'GDPR'],
  'iso-iec-27001-2022': ['ISO 27001'],
  'finops-framework': ['FinOps'],
  'wcag-2-2': ['WCAG'],
  diataxis: ['Diataxis'],
};
/** Acronyms: explicit parentheses, initials of significant words, and a few known aliases. */
export function aliasesOf(r: Reference): string[] {
  const out = new Set<string>(MANUAL[r.id] ?? []);
  for (const m of r.name.matchAll(/\(([A-Z0-9][A-Za-z0-9 .-]{1,14})\)/g)) out.add(m[1]);
  const words = r.name
    .replace(/\(.*?\)/g, '')
    .split(/[\s/,:—-]+/)
    .filter((w) => w && !STOP.has(norm(w)) && !/^\d/.test(w));
  const initials = words
    .filter((w) => w !== w.toUpperCase() || w.length === 1)
    .map((w) => w[0])
    .join('');
  if (initials.length >= 2 && initials.length <= 6) out.add(initials.toUpperCase());
  return [...out];
}

export interface Hit {
  ref: Ref;
  title: string;
  subtitle: string;
  score: number;
}

export function searchAll(s: AppState, query: string, limit = 30): Hit[] {
  const tokens = norm(query).split(/\s+/).filter(Boolean);
  if (!tokens.length) return [];
  const orgId = s.session.orgId;
  const items: { ref: Ref; title: string; subtitle: string; extra?: string }[] = [
    ...list(s, 'project', orgId).map((p) => ({
      ref: { kind: 'project' as const, id: p.id },
      title: p.name,
      subtitle: `Projet · ${p.status === 'archived' ? 'archivé' : 'actif'}`,
      extra: p.summary,
    })),
    ...list(s, 'quest', orgId).map((q) => ({
      ref: { kind: 'quest' as const, id: q.id },
      title: q.title,
      subtitle: 'Quête',
      extra: q.objective,
    })),
    ...list(s, 'decision', orgId).map((d) => ({
      ref: { kind: 'decision' as const, id: d.id },
      title: `${d.title} v${d.number}`,
      subtitle: `Décision · ${d.optionTitle}`,
      extra: d.justification,
    })),
    ...list(s, 'council', orgId).map((c) => ({
      ref: { kind: 'council' as const, id: c.id },
      title: c.title,
      subtitle: 'Session du Conseil',
      extra: c.objective,
    })),
    ...list(s, 'deliverable', orgId).map((d) => ({
      ref: { kind: 'deliverable' as const, id: d.id },
      title: d.title,
      subtitle: `${d.docCategory ? 'Document' : 'Livrable'} · ${DELIVERABLE_TYPES[d.type].label}`,
    })),
    ...list(s, 'finding', orgId).map((f) => ({
      ref: { kind: 'finding' as const, id: f.id },
      title: f.title,
      subtitle: `Constat · ${f.severity}`,
      extra: f.observation,
    })),
    ...list(s, 'expert', orgId).map((e) => ({
      ref: { kind: 'expert' as const, id: e.id },
      title: e.name,
      subtitle: `Expertise IA · ${e.domain}`,
      extra: e.specialty,
    })),
    ...list(s, 'signal', orgId).map((x) => ({ ref: { kind: 'signal' as const, id: x.id }, title: x.title, subtitle: 'Signal (fictif)' })),
    ...list(s, 'rule', orgId).map((r) => ({
      ref: { kind: 'rule' as const, id: r.id },
      title: `${r.code} ${r.versions.at(-1)?.title}`,
      subtitle: 'Règle',
      extra: r.versions.at(-1)?.statement,
    })),
    ...allReferences(s).map((r) => ({
      ref: { kind: 'reference' as const, id: r.id },
      title: r.name,
      subtitle: `Référence · ${r.category}`,
      extra: `${aliasesOf(r).join(' ')} ${r.description}`,
    })),
  ];
  const hits: Hit[] = [];
  for (const it of items) {
    const t = norm(it.title);
    const all = `${t} ${norm(it.subtitle)} ${norm(it.extra ?? '')}`;
    if (!tokens.every((k) => all.includes(k))) continue;
    const score =
      tokens.reduce(
        (sc, k) =>
          sc +
          (t.startsWith(k)
            ? 6
            : t.includes(k)
              ? 4
              : norm(it.extra ?? '')
                    .split(' ')
                    .includes(k)
                ? 3
                : 1),
        0,
      ) -
      t.length / 200;
    hits.push({ ref: it.ref, title: it.title, subtitle: it.subtitle, score });
  }
  return hits.sort((a, b) => b.score - a.score).slice(0, limit);
}
