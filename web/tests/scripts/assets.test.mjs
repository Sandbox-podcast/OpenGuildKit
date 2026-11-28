// Weight of what the build ships: the images and the budget of the package.
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const at = (path) => new URL(`../../${path}`, import.meta.url);

describe('images of the build', () => {
  /** Issue #513: the header showed a 543 x 181 logo of 46 KB at 108 x 36. */
  it('serves the header a logo under 15 KB, and keeps the large one for the installation screen', () => {
    expect(statSync(at('public/assets/brand/logo-header.webp')).size).toBeLessThan(15_000);
    const brand = readFileSync(at('src/shared/Brand.tsx'), 'utf8');
    expect(brand).toContain("size === 'hero' ? BRAND.logo : BRAND.logoHeader");
  });

  /** Issue #513: the twelve header scenes weighed 415 KB, exported in quality 90. */
  it('weighs the twelve header scenes under 300 KB', () => {
    const files = readdirSync(at('public/assets/rooms')).filter((name) => name.endsWith('.webp'));
    expect(files).toHaveLength(12);
    expect(files.reduce((total, name) => total + statSync(at(`public/assets/rooms/${name}`)).size, 0)).toBeLessThan(300_000);
  });
});
