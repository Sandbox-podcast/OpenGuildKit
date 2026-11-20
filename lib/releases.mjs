import { gh } from './github.mjs';

const versionPattern = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
const digestPattern = /^sha256:([a-f0-9]{64})$/;

function compareVersions(left, right) {
  const a = left.split('.').map(BigInt);
  const b = right.split('.').map(BigInt);
  const difference = a.findIndex((part, index) => part !== b[index]);
  return difference < 0 ? 0 : a[difference] > b[difference] ? 1 : -1;
}

export function checkKitRelease({ repo, channel, installedVersion }, request = gh) {
  if (typeof repo !== 'string' || !/^[a-z\d][a-z\d-]*\/[a-z\d_.-]+$/i.test(repo) ||
      !['stable', 'pilot'].includes(channel) || !versionPattern.test(installedVersion)) {
    throw new Error('Dépôt GitHub, canal stable ou pilot, et version installée X.Y.Z requis.');
  }
  const pages = JSON.parse(request('api', '--paginate', '--slurp', `repos/${repo}/releases?per_page=100`));
  const candidates = pages.flat().flatMap(release => {
    const version = release.tag_name?.slice(1);
    if (!release.tag_name?.startsWith('v') || !versionPattern.test(version) ||
        release.draft || !release.published_at || (channel === 'stable' && release.prerelease)) return [];
    return [{ release, version }];
  }).sort((left, right) => compareVersions(right.version, left.version));

  const incomplete = [];
  let latest = null;
  for (const { release, version } of candidates) {
    const name = `openguildkit-${version}.tgz`;
    const asset = release.assets?.find(item => item.name === name && item.state === 'uploaded' && item.size > 0);
    const sha256 = digestPattern.exec(asset?.digest)?.[1];
    if (!sha256) {
      incomplete.push(version);
      continue;
    }
    const base = `https://github.com/${repo}/releases`;
    latest = {
      version, prerelease: release.prerelease,
      publishedAt: release.published_at, url: `${base}/tag/${release.tag_name}`,
      archive: { name, url: `${base}/download/${release.tag_name}/${name}`, sha256 },
    };
    break;
  }

  let status = 'no-release';
  if (latest) {
    const comparison = compareVersions(latest.version, installedVersion);
    status = comparison > 0 ? 'available' : comparison < 0 ? 'ahead' : 'up-to-date';
  }
  return { repository: repo, channel, installedVersion, status, latest, incomplete };
}
