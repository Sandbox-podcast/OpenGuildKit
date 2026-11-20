import assert from 'node:assert/strict';
import { test } from 'node:test';
import { checkKitRelease } from '../lib/releases.mjs';

test('release discovery respects the channel and sorts usable versions numerically', () => {
  const sha256 = 'a'.repeat(64);
  const published = (version, overrides = {}) => ({
    tag_name: `v${version}`, draft: false, prerelease: false, published_at: '2026-11-20T00:00:00Z',
    assets: [{ name: `openguildkit-${version}.tgz`, state: 'uploaded', size: 123, digest: `sha256:${sha256}` }],
    ...overrides,
  });
  const pages = [
    [published('0.9.0'), published('9.0.0', { draft: true }), published('0.14.0', { assets: [] })],
    [published('0.13.0', { prerelease: true }), published('0.12.0')],
  ];
  const request = (...args) => {
    assert.deepEqual(args, ['api', '--paginate', '--slurp', 'repos/team/kit/releases?per_page=100']);
    return JSON.stringify(pages);
  };
  const check = (channel, installedVersion) => checkKitRelease({
    repo: 'team/kit', channel, installedVersion,
  }, request);

  const stable = check('stable', '0.12.0');
  assert.equal(stable.status, 'up-to-date');
  assert.deepEqual(stable.incomplete, ['0.14.0']);
  const pilot = check('pilot', '0.12.0');
  assert.equal(pilot.status, 'available');
  assert.equal(pilot.latest.version, '0.13.0');
  assert.equal(pilot.latest.archive.sha256, sha256);
  assert.equal(pilot.latest.archive.url, 'https://github.com/team/kit/releases/download/v0.13.0/openguildkit-0.13.0.tgz');
  assert.equal(check('stable', '0.13.0').status, 'ahead');
});
