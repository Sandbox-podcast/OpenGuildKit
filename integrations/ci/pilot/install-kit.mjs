import { execFileSync } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

export function withInstalledKit(kit, use, { cacheDir } = {}) {
  if (!/^[\w.-]+\/[\w.-]+$/.test(kit.repository) || !/^\d+\.\d+\.\d+$/.test(kit.version) ||
    !/^[a-f0-9]{64}$/.test(kit.sha256)) {
    throw new Error('Invalid kit reference.');
  }
  const install = mkdtempSync(join(tmpdir(), 'openguildkit-pilot-'));
  try {
    const asset = `openguildkit-${kit.version}.tgz`;
    const cached = cacheDir && join(cacheDir, `${kit.sha256}.tgz`);
    const cachedAlready = cached && existsSync(cached);
    const archive = join(install, asset);
    if (!cachedAlready) {
      execFileSync('gh', ['release', 'download', `v${kit.version}`, '-R', kit.repository, '-p', asset, '-D', install],
        { stdio: 'inherit', timeout: 120_000 });
    }
    const bytes = readFileSync(cachedAlready ? cached : archive);
    const digest = createHash('sha256').update(bytes).digest('hex');
    if (digest !== kit.sha256) throw new Error('Incorrect digest for the OpenGuildKit archive.');
    if (cachedAlready) writeFileSync(archive, bytes, { flag: 'wx' });
    if (cached && !cachedAlready) {
      mkdirSync(cacheDir, { recursive: true });
      const temporary = `${cached}.${randomUUID()}.tmp`;
      try {
        writeFileSync(temporary, bytes, { flag: 'wx', flush: true });
        renameSync(temporary, cached);
      } finally {
        rmSync(temporary, { force: true });
      }
    }
    if (cached) {
      const source = cachedAlready ? 'local cache' : 'GitHub Releases';
      console.error(`OpenGuildKit archive ${kit.version} verified (${source}).`);
    }
    execFileSync('tar', ['-xf', archive, '-C', install], { stdio: 'inherit' });
    const bin = join(install, 'package/bin');
    const version = execFileSync(process.execPath, [join(bin, 'openguildkit.mjs'), '--version'], { encoding: 'utf8' }).trim();
    if (version !== kit.version) throw new Error(`Unexpected installed version: ${version}.`);
    return use(bin, install);
  } finally {
    rmSync(install, { recursive: true, force: true });
  }
}
