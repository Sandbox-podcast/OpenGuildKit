import { execFileSync } from 'node:child_process';
import { linkSync, mkdirSync, mkdtempSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

function windowsVolumeFormat(directory) {
  if (process.platform !== 'win32') return null;
  try {
    return execFileSync('powershell.exe', [
      '-NoProfile', '-NonInteractive', '-Command',
      '[System.IO.DriveInfo]::new([System.IO.Path]::GetPathRoot($env:OPENGUILDKIT_STATE_PROBE_PATH)).DriveFormat',
    ], {
      encoding: 'utf8', env: { ...process.env, OPENGUILDKIT_STATE_PROBE_PATH: realpathSync.native(directory) },
      stdio: ['ignore', 'pipe', 'ignore'], timeout: 5000, windowsHide: true,
    }).trim();
  } catch {
    // The actual hard-link attempt is authoritative even if volume metadata is unavailable.
    return null;
  }
}

export function checkStateDirectory(stateDir, { link = linkSync, volumeFormat = windowsVolumeFormat } = {}) {
  const directory = resolve(stateDir);
  let probe;
  try {
    mkdirSync(directory, { recursive: true });
    probe = mkdtempSync(join(directory, '.openguildkit-state-'));
    const source = join(probe, 'probe');
    writeFileSync(source, 'OpenGuildKit state directory test', { flag: 'wx' });
    try {
      link(source, join(probe, 'linked'));
    } catch (error) {
      const format = volumeFormat(directory);
      const reason = format?.toLowerCase() === 'exfat'
        ? 'The volume is exFAT and does not support hard links.'
        : `Could not create a hard link (${error.code ?? error.message}).`;
      throw new Error(
        `${reason} Choose a writable, persistent filesystem that supports hard links (NTFS on Windows), then retry with --state.`,
        { cause: error },
      );
    }
  } catch (error) {
    throw new Error(`OpenGuildKit state directory "${directory}": ${error.message}`, { cause: error });
  } finally {
    if (probe) rmSync(probe, { recursive: true, force: true });
  }
  return directory;
}
