// Exports the twelve header scenes of the RPG style from the three sheets of docs/art/rooms, as the table of its
// README says: crop the rectangle (left, top, right, bottom, in pixels of the sheet), resize to 768 x 192, write WebP.
//   node scripts/export-rooms.mjs [quality]     (82 by default; needs ImageMagick (magick) and cwebp on the PATH)
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const web = join(dirname(fileURLToPath(import.meta.url)), '..');
const sheets = join(web, 'docs', 'art', 'rooms');
const quality = process.argv[2] ?? '82';
// The file of a place is its name without accents, except the Tour de guet (tour.webp).
const fileOf = (place) => (place === 'Tour de guet' ? 'tour' : place.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase());

const rows = readFileSync(join(sheets, 'README.md'), 'utf8').matchAll(
  /^\| ([^|]+) \| \[[^\]]+\]\(([^)]+\.png)\) \| [^|]+ \| (\d+), (\d+), (\d+), (\d+) \|$/gm,
);
for (const [, place, sheet, left, top, right, bottom] of rows) {
  const png = execFileSync(
    'magick',
    [
      join(sheets, sheet),
      '-crop',
      `${right - left}x${bottom - top}+${left}+${top}`,
      '+repage',
      '-filter',
      'Lanczos',
      '-resize',
      '768x192!',
      'png:-',
    ],
    { maxBuffer: 1 << 26 },
  );
  const target = join(web, 'public', 'assets', 'rooms', `${fileOf(place)}.webp`);
  execFileSync('cwebp', ['-quiet', '-q', quality, '-m', '6', '-o', target, '--', '-'], { input: png });
  console.log(`${place.padEnd(14)} ${target.replace(`${web}/`, '')}`);
}
