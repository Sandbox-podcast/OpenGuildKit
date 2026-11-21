/**
 * Converts the supplied Markdown catalogue into src/fixtures/catalogue.json.
 * Fails when the parsed counts differ from the counts declared by the file.
 * Usage: npm run catalogue [-- path/to/catalogue.md]
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { catalogueStats, parseCatalogueMarkdown } from '../src/adapters/catalogue';

const input = process.argv[2] ?? 'data/SOCLE_Catalogue_395_References.md';
const { catalogue, issues } = parseCatalogueMarkdown(readFileSync(input, 'utf8'));
const stats = catalogueStats(catalogue.references);
const ids = new Set(catalogue.references.map((r) => r.id));
const problems = [
  ...issues.map((i) => `ligne ${i.line} : ${i.message}`),
  ...(ids.size !== catalogue.references.length ? ['identifiants en double'] : []),
  ...(['references', 'categories', 'families'] as const)
    .filter((k) => stats[k] !== catalogue.declared[k])
    .map((k) => `${k} : ${stats[k]} lus, ${catalogue.declared[k]} annoncés`),
];
if (problems.length) {
  console.error(`Catalogue refusé :\n- ${problems.join('\n- ')}`);
  process.exit(1);
}
writeFileSync('src/fixtures/catalogue.json', `${JSON.stringify(catalogue, null, 1)}\n`);
console.log(`Catalogue écrit : ${stats.references} références, ${stats.categories} catégories, ${stats.families} familles (édition ${catalogue.edition}).`);
