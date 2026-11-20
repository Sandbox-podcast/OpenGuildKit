#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { parseArgs } from 'node:util';

try {
  const { values } = parseArgs({ options: { bundle: { type: 'string' } } });
  if (!values.bundle) throw new Error('Usage: openguildkit-ci-agent --bundle DIR');
  const brief = JSON.parse(readFileSync(join(values.bundle, 'brief.json'), 'utf8'));
  const documents = new Map([
    ['brief', brief],
    ['guidance', readFileSync(join(values.bundle, 'AGENTS.md'), 'utf8')],
  ]);
  for await (const line of createInterface({ input: process.stdin, crlfDelay: Infinity })) {
    let request;
    try { request = JSON.parse(line); } catch { request = null; }
    const method = typeof request?.method === 'string' ? request.method.slice(0, 80) : null;
    const allowed = documents.has(request?.method) && request.params === undefined;
    const id = ['number', 'string'].includes(typeof request?.id) ? request.id : null;
    process.stderr.write(JSON.stringify({
      at: new Date().toISOString(), project: brief.project, profileCommit: brief.profileCommit, method, allowed,
    }) + '\n');
    process.stdout.write(JSON.stringify(allowed
      ? { id, result: documents.get(method) }
      : { id, error: 'Action indisponible dans l’adaptateur en lecture.' }) + '\n');
  }
} catch (error) {
  process.stderr.write(error.message + '\n');
  process.exitCode = 2;
}
