#!/usr/bin/env node
// Local stand-in for the `gh` commands that `openguildkit-ci watch` calls. Nothing leaves the machine.
// Repositories are bare Git repositories under FAKE_GH_ROOT/<owner>/<repo>.git, and PRs are their
// refs/pull/<n>/head. A dispatched run executes the steps of pilot/recheck-workflow.yml with the
// archive under test, against the references it reads when it starts.
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { appendFileSync, copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const root = process.env.FAKE_GH_ROOT;
const statePath = join(root, 'state.json');
const load = () => existsSync(statePath)
  ? JSON.parse(readFileSync(statePath, 'utf8'))
  : { nextRun: 101, runs: {}, killAfterDispatch: [], hold: true, startOnRelease: false, artifactFrom: {} };
const save = state => writeFileSync(statePath, JSON.stringify(state, null, 2) + '\n');
const log = entry => appendFileSync(join(root, 'calls.jsonl'),
  JSON.stringify({ at: new Date().toISOString(), ...entry }) + '\n');
const bare = project => join(root, `${project}.git`);
const git = (repo, ...args) => execFileSync('git', ['-C', repo, ...args], { encoding: 'utf8' }).trim();
const fail = message => {
  process.stderr.write(`${message}\n`);
  process.exit(1);
};

// On Windows the stand-in is gh.exe, a parent of this process. Its parent is the watcher.
function coordinatorPid() {
  if (process.platform !== 'win32') return process.ppid;
  const output = execFileSync('powershell.exe', ['-NoProfile', '-Command',
    `(Get-CimInstance Win32_Process -Filter "ProcessId=${process.ppid}").ParentProcessId`],
    { encoding: 'utf8' });
  const pid = Number(String(output).trim());
  if (!Number.isInteger(pid) || pid <= 0) fail(`cannot identify the watcher to interrupt (parent of ${process.ppid})`);
  return pid;
}

function option(args, name) {
  const index = args.indexOf(name);
  return index === -1 ? undefined : args[index + 1];
}

function fields(args) {
  const values = {};
  for (let i = 0; i < args.length; i += 1) {
    if (args[i] === '-f' || args[i] === '-F') {
      const [key, ...rest] = args[i + 1].split('=');
      values[key] = rest.join('=');
    }
  }
  return values;
}

function pulls(project) {
  const refs = git(bare(project), 'for-each-ref', '--format=%(refname) %(objectname)', 'refs/pull/');
  return refs.split('\n').filter(Boolean).flatMap(line => {
    const [ref, sha] = line.split(' ');
    const match = /^refs\/pull\/(\d+)\/head$/.exec(ref);
    return match ? [{
      number: Number(match[1]), state: 'open', head: { sha },
      base: { ref: 'main', repo: { full_name: project } },
      html_url: `https://github.com/${project}/pull/${match[1]}`,
    }] : [];
  });
}

// The steps of pilot/recheck-workflow.yml, with the release asset and the clones taken from FAKE_GH_ROOT.
function execute(run) {
  const folder = join(root, 'runs', String(run.id));
  const ws = join(folder, 'ws');
  mkdirSync(ws, { recursive: true });
  const { pr, commit, work, expected } = run.inputs;
  const step = [];
  try {
    git(ws, 'init', '--quiet');
    git(ws, 'fetch', '--quiet', '--no-tags', bare(run.project), `+refs/heads/${run.ref}:refs/heads/${run.ref}`);
    git(ws, 'checkout', '--quiet', run.ref);
    const pins = JSON.parse(readFileSync(join(ws, 'pilot/recheck.json'), 'utf8'));
    const [digest, asset] = readFileSync(join(ws, 'pilot/recheck-kit.sha256'), 'utf8').trim().split(/\s+/);
    const kitVersion = /^openguildkit-(\d+\.\d+\.\d+)\.tgz$/.exec(asset)?.[1];
    if (expected && JSON.parse(expected).kitVersion !== kitVersion) throw new Error('kit pin differs');
    const archive = join(root, 'releases', asset);
    if (createHash('sha256').update(readFileSync(archive)).digest('hex') !== digest) throw new Error('kit digest');
    const kit = join(folder, 'kit');
    mkdirSync(kit);
    execFileSync('tar', ['-xzf', archive, '-C', kit]);
    git(ws, 'fetch', '--quiet', '--no-tags', bare(run.project),
      `+${pins.profileRef}:refs/openguildkit/profile`, `+refs/pull/${pr}/head:refs/openguildkit/pr`);
    const head = git(ws, 'rev-parse', 'refs/openguildkit/pr');
    if (head !== commit) throw new Error(`PR head ${head} instead of ${commit}`);
    git(ws, 'fetch', '--quiet', '--no-tags', bare(pins.policyRepository), `+${pins.policyRef}:refs/openguildkit/policy`);
    step.push({ policyTip: git(ws, 'rev-parse', 'refs/openguildkit/policy'), prHead: head });
    writeFileSync(join(ws, 'integration.json'), JSON.stringify({
      policyRepo: { path: '.', ref: 'refs/openguildkit/policy' },
      projects: [{ id: run.project, path: '.', profileRef: 'refs/openguildkit/profile',
        pullRequests: [{ number: Number(pr), ref: 'refs/openguildkit/pr', sha: commit }] }],
    }));
    const cli = join(kit, 'package', 'bin', 'openguildkit.mjs');
    const reconcile = (...extra) => JSON.parse(execFileSync(process.execPath,
      [cli, 'reconcile', '--config', 'integration.json', '--state', 'state', ...extra], { cwd: ws, encoding: 'utf8' }));
    const plan = reconcile();
    if (plan.current.length !== 1 || plan.current[0].work !== work) {
      throw new Error(`This workflow computed another work key than the coordinator: ${plan.current[0]?.work}`);
    }
    const observed = reconcile('--run');
    const evidence = JSON.parse(readFileSync(join(ws, observed.current[0].evidence[0]), 'utf8')).evidence;
    writeFileSync(join(folder, 'result.json'), JSON.stringify({
      work, project: run.project, pullRequest: Number(pr), proof: evidence,
    }, null, 2) + '\n');
    return { conclusion: 'success', ...step[0] };
  } catch (error) {
    return { conclusion: 'failure', error: error.message.split('\n')[0], ...step[0] };
  }
}

function start(state, run) {
  Object.assign(run, execute(run), { startedAt: new Date().toISOString() });
  log({ event: 'run-executed', id: run.id, conclusion: run.conclusion, policyTip: run.policyTip, prHead: run.prHead });
}

const args = process.argv.slice(2);
const state = load();
const [command, sub] = args;

if (command === 'workflow' && sub === 'run') {
  const project = option(args, '-R');
  const inputs = JSON.parse(readFileSync(0, 'utf8'));
  const id = state.nextRun++;
  const run = {
    id, project, file: args[2], ref: option(args, '--ref'), inputs, event: 'workflow_dispatch',
    display_title: `OpenGuildKit recheck ${inputs.work}${inputs.attempt ? ` ${inputs.attempt}` : ''}`,
    created_at: new Date().toISOString(), released: !state.hold,
    html_url: `https://github.com/${project}/actions/runs/${id}`,
  };
  state.runs[id] = run;
  log({ event: 'dispatch-accepted', id, project, work: inputs.work, attempt: inputs.attempt, commit: inputs.commit,
    policyCommit: JSON.parse(inputs.expected).policyCommit });
  if (!state.startOnRelease) start(state, run);
  const dispatches = Object.keys(state.runs).length;
  save(state);
  if (state.killAfterDispatch.includes(dispatches)) {
    const target = coordinatorPid();
    log({ event: 'coordinator-killed', afterRun: id, pid: target });
    process.kill(target, 'SIGKILL');
  }
  process.stdout.write(`${run.html_url}\n`);
} else if (command === 'run' && sub === 'view') {
  const run = state.runs[args[2]];
  if (!run || run.project !== option(args, '-R')) fail('HTTP 404: Not Found');
  const done = run.released && run.conclusion;
  process.stdout.write(JSON.stringify(done ? { status: 'completed', conclusion: run.conclusion }
    : { status: run.released || run.startedAt ? 'in_progress' : 'queued', conclusion: '' }) + '\n');
} else if (command === 'run' && sub === 'download') {
  const run = state.runs[args[2]];
  if (!run || run.conclusion !== 'success') fail('no artifact matches openguildkit-recheck');
  const from = state.artifactFrom[run.id] ?? run.id;
  log({ event: 'artifact-download', id: run.id, servedFrom: from });
  copyFileSync(join(root, 'runs', String(from), 'result.json'), join(option(args, '-D'), 'result.json'));
} else if (command === 'run' && sub === 'cancel') {
  log({ event: 'run-cancel', id: args[2] });
} else if (command === 'api') {
  const endpoint = args.find(arg => arg.startsWith('repos/'));
  let match;
  if ((match = /^repos\/([^/]+\/[^/]+)\/pulls\?/.exec(endpoint))) {
    process.stdout.write(JSON.stringify([pulls(match[1])]) + '\n');
  } else if ((match = /^repos\/([^/]+\/[^/]+)\/contents\/([^?]+)\?ref=(.+)$/.exec(endpoint))) {
    const content = git(bare(match[1]), 'show', `${decodeURIComponent(match[3])}:${match[2]}`);
    process.stdout.write(JSON.stringify({ content: Buffer.from(content + '\n').toString('base64') }) + '\n');
  } else if ((match = /^repos\/([^/]+\/[^/]+)\/actions\/workflows\/([^/]+)\/runs$/.exec(endpoint))) {
    const filter = fields(args);
    const since = filter.created?.replace(/^>=/, '');
    const runs = Object.values(state.runs).filter(run => run.project === match[1] &&
      run.file === decodeURIComponent(match[2]) && run.ref === filter.branch && run.event === filter.event &&
      (!since || run.created_at >= since));
    log({ event: 'runs-listed', project: match[1], found: runs.map(run => run.id) });
    process.stdout.write(JSON.stringify([{ total_count: runs.length, workflow_runs: runs }]) + '\n');
  } else {
    fail(`fake-gh: unsupported endpoint ${endpoint}`);
  }
} else if (command === '__release') {
  // Test control, not a gh command: let the listed runs finish (and start the deferred ones).
  for (const id of args.slice(1)) {
    const run = state.runs[id];
    if (!run.startedAt) start(state, run);
    run.released = true;
    log({ event: 'run-completed', id: run.id, conclusion: run.conclusion });
  }
  save(state);
} else {
  fail(`fake-gh: unsupported command ${args.join(' ')}`);
}
