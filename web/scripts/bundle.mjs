// Copies the built front end (web/dist) into the Python package, so `pip install` ships the interface
// that `openguildkit ui` serves. Run after `npm run build`; the copy is ignored by Git.
import { cpSync, existsSync, rmSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const web = join(dirname(fileURLToPath(import.meta.url)), '..');
const source = join(web, 'dist');
const target = join(web, '..', 'src', 'openguildkit', 'web_dist');
if (!existsSync(join(source, 'index.html'))) {
  console.error('web/dist/index.html is missing: run npm run build first.');
  process.exit(1);
}
rmSync(target, { recursive: true, force: true });
// Source drawings (docs/art) are not part of the build; the interface needs only what Vite emitted.
cpSync(source, target, { recursive: true });
console.log(`Copied ${source} to ${target} (${statSync(join(target, 'index.html')).size} bytes of index.html).`);
