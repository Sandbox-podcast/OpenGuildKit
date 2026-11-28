/**
 * Reuses the OpenGuildKit CLI registry (../src/openguildkit/registry) instead of duplicating it:
 * rule packs become configurable Library packs, boards enrich the expert sheets.
 * Pack sources are matched to catalogue references by URL host and path.
 */
import type { Reference } from '@/demo/adapters/catalogue';

interface CliPack { id: string; title: string; version: string; description: string; sources: { title: string; url: string }[]; depends_on?: string[]; rules: { id: string; instruction: string; verification: string }[] }
interface CliBoard { id: string; title: string; description: string; questions: string[]; sources: { title: string; url: string }[]; review?: { specialists?: { id: string; title: string; focus: string }[] } }

const packModules = import.meta.glob<CliPack>('../../../../src/openguildkit/registry/packs/*.json', { eager: true, import: 'default' });
const boardModules = import.meta.glob<CliBoard>('../../../../src/openguildkit/registry/boards/*.json', { eager: true, import: 'default' });

export const CLI_PACKS: CliPack[] = Object.values(packModules).sort((a, b) => a.title.localeCompare(b.title));
export const CLI_BOARDS: Record<string, CliBoard> = Object.fromEntries(Object.values(boardModules).map((b) => [b.id, b]));

const norm = (url: string) => { try { const u = new URL(url); return `${u.host.replace(/^www\./, '')}${u.pathname.replace(/\/$/, '')}`; } catch { return url; } };

/** Catalogue references cited by a CLI pack, matched by source URL. */
export function packReferenceIds(pack: CliPack, refs: Reference[]): string[] {
  const urls = new Set(pack.sources.map((s) => norm(s.url)));
  return refs.filter((r) => r.sources.some((s) => urls.has(norm(s.url)))).map((r) => r.id);
}
