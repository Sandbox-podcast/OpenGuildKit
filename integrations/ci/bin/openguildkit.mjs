#!/usr/bin/env node
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { parseArgs } from 'node:util';
import { evaluateRefs, git, gitSha, isGitPath, parseProfile } from '../lib/check.mjs';
import { reconcile, recordEvidence } from '../lib/reconcile.mjs';
import { approveGitHubProfile, readGitHubTicket, reconcileGithub } from '../lib/github.mjs';
import { loadCatalog, proposeProfile, questionnaire } from '../lib/onboard.mjs';
import { linkBrief, prepareBrief } from '../lib/agent.mjs';
import { mergeGithub } from '../lib/merge.mjs';
import { watchGithub } from '../lib/watch.mjs';
import { checkKitRelease } from '../lib/releases.mjs';
import { inspectMergeInstallation, inspectMergeProtection } from '../lib/merge-protection.mjs';

const { version } = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
const help = `OpenGuildKit ${version}

  openguildkit-ci releases --repo OWNER/REPO [--channel stable|pilot] [--installed X.Y.Z]
  openguildkit-ci init --owner OWNER [--profile openguildkit.json]
  openguildkit-ci check --policy-repo DIR --policy-commit SHA --commit SHA
    [--target-repo DIR] [--profile FILE] [--profile-commit SHA] [--output DIR] [--enforce]
    [--brief FILE --pull-request URL]
  openguildkit-ci reconcile --config FILE --state DIR [--run]
  openguildkit-ci github --config FILE --state DIR [--run] [--publish [--report-url URL]]
  openguildkit-ci watch --config FILE --state DIR [--publish]
  openguildkit-ci gate --config FILE --state DIR --project ID --pr NUMBER --commit SHA [--run] [--github]
  openguildkit-ci merge --config FILE --state DIR --project OWNER/REPO --pr NUMBER --commit SHA --base BRANCH [--execute] [--ruleset ID]
  openguildkit-ci merge-protection --repo OWNER/REPO --base BRANCH --ruleset ID [--app-id ID]
  openguildkit-ci merge-installation --repo OWNER/REPO --app-slug SLUG --app-id ID
  openguildkit-ci record --state DIR --work ID --evidence FILE
  openguildkit-ci catalog --policy-repo DIR --policy-commit SHA [--catalog FILE]
  openguildkit-ci onboard --policy-repo DIR --policy-commit SHA [--catalog FILE]
    [--repo DIR] [--ref REF] [--inspect] [--answers FILE --profile FILE]
  openguildkit-ci github-approve-profile --repo OWNER/REPO --pr NUMBER --base BRANCH --maintainer LOGIN
  openguildkit-ci brief --policy-repo DIR --policy-commit SHA --profile-commit SHA
    --task FILE --output DIR [--target-repo DIR]
  openguildkit-ci github-brief --repo OWNER/REPO --pr NUMBER --commit SHA
    --policy-repo DIR --policy-commit SHA --profile-commit SHA --output DIR [--target-repo DIR]

En mode informatif, un écart est enregistré et la commande retourne 0.
Avec --enforce, un écart retourne 1. Une erreur de configuration ou de lecture retourne 2.`;

const profileOption = { type: 'string', default: 'openguildkit.json' };

function mergeProtection(args) {
  const { values } = parseArgs({ args, options: {
    repo: { type: 'string' }, base: { type: 'string' }, ruleset: { type: 'string' }, 'app-id': { type: 'string' },
  } });
  const status = inspectMergeProtection({
    repo: values.repo, base: values.base, ruleset: Number(values.ruleset),
    appId: values['app-id'] === undefined ? undefined : Number(values['app-id']),
  });
  console.log(JSON.stringify(status, null, 2));
  process.exitCode = status.approved ? 0 : 1;
}

function mergeInstallation(args) {
  const { values } = parseArgs({ args, options: {
    repo: { type: 'string' }, 'app-slug': { type: 'string' }, 'app-id': { type: 'string' },
  } });
  const status = inspectMergeInstallation({
    repo: values.repo, appSlug: values['app-slug'], appId: Number(values['app-id']),
  });
  console.log(JSON.stringify(status, null, 2));
  process.exitCode = status.approved ? 0 : 1;
}

function releases(args) {
  const { values } = parseArgs({ args, options: {
    repo: { type: 'string' },
    channel: { type: 'string', default: 'stable' },
    installed: { type: 'string', default: version },
  } });
  const result = checkKitRelease({ repo: values.repo, channel: values.channel, installedVersion: values.installed });
  console.log(JSON.stringify(result, null, 2));
}

function approveProfile(args) {
  const { values } = parseArgs({ args, options: {
    repo: { type: 'string' }, pr: { type: 'string' }, base: { type: 'string' }, maintainer: { type: 'string' },
  } });
  if (!/^[1-9]\d*$/.test(values.pr)) throw new Error('Le numéro de PR est requis.');
  const approved = approveGitHubProfile({ ...values, pullRequest: Number(values.pr) });
  console.log(JSON.stringify(approved, null, 2));
}

function adoption(command, args) {
  const catalogOptions = {
    'policy-repo': { type: 'string' },
    'policy-commit': { type: 'string' },
    catalog: { type: 'string' },
  };
  const { values } = parseArgs({
    args,
    options: command === 'catalog' ? catalogOptions : {
      ...catalogOptions,
      repo: { type: 'string', default: '.' },
      ref: { type: 'string', default: 'HEAD' },
      inspect: { type: 'boolean' },
      answers: { type: 'string' },
      profile: profileOption,
    },
  });
  const catalog = loadCatalog({
    policyRepo: values['policy-repo'], policyCommit: values['policy-commit'], catalogPath: values.catalog,
  });
  if (command === 'catalog') {
    console.log(JSON.stringify(catalog, null, 2));
    return;
  }
  const form = questionnaire({ repo: values.repo, ref: values.ref, catalog, inspect: values.inspect });
  if (!values.answers) {
    console.log(JSON.stringify(form, null, 2));
    return;
  }
  const filled = JSON.parse(readFileSync(values.answers, 'utf8'));
  if (filled.repositoryCommit !== form.repositoryCommit || filled.catalog?.policyCommit !== catalog.policyCommit ||
      filled.catalog?.catalogPath !== catalog.catalogPath) {
    throw new Error('Les références ont changé depuis le questionnaire. Confirmer les réponses pour les révisions voulues.');
  }
  const profile = proposeProfile({ answers: filled.answers, catalog, commit: form.repositoryCommit });
  writeFileSync(values.profile, JSON.stringify(profile, null, 2) + '\n', { flag: 'wx' });
  console.log(values.profile);
}

function init(args) {
  const { values: options } = parseArgs({
    args,
    options: { owner: { type: 'string' }, profile: profileOption },
  });
  const profile = {
    schemaVersion: 1,
    owner: options.owner?.trim(),
    policyPath: 'policy/export-link.json',
    targetPath: 'export.json',
  };
  const content = JSON.stringify(profile, null, 2) + '\n';
  parseProfile(content);
  writeFileSync(options.profile, content, { flag: 'wx' });
  console.log(options.profile);
}

function check(args) {
  const { values: options } = parseArgs({
    args,
    options: {
      'policy-repo': { type: 'string' },
      'policy-commit': { type: 'string' },
      'target-repo': { type: 'string', default: '.' },
      commit: { type: 'string' },
      profile: profileOption,
      'profile-commit': { type: 'string' },
      output: { type: 'string' },
      enforce: { type: 'boolean', default: false },
      brief: { type: 'string' },
      'pull-request': { type: 'string' },
    },
  });
  const policyCommit = options['policy-commit'];
  if (!options['policy-repo'] || !gitSha.test(policyCommit) || !gitSha.test(options.commit)) {
    throw new Error('Un dépôt de règles et les deux SHA Git complets sont requis.');
  }
  const profileCommit = options['profile-commit'];
  if (profileCommit !== undefined && (!gitSha.test(profileCommit) || !isGitPath(options.profile))) {
    throw new Error('Un SHA de profil complet et un chemin de profil relatif à Git sont requis.');
  }
  const targetRepo = options['target-repo'];
  const profileBytes = profileCommit !== undefined
    ? git(targetRepo, 'show', `${profileCommit}:${options.profile}`)
    : readFileSync(options.profile);
  let evidence = evaluateRefs({
    policyRepo: options['policy-repo'], policyCommit, targetRepo,
    commit: options.commit, profileBytes, kitVersion: version,
  });
  if (options.enforce && evidence.mode === 'observation') {
    throw new Error('Le profil approuvé est en observation. Modifier son mode dans une nouvelle révision approuvée.');
  }
  if (profileCommit !== undefined) evidence.profileCommit = profileCommit;
  if (options.brief || options['pull-request']) {
    if (!options.brief) throw new Error('--pull-request requiert --brief.');
    evidence = linkBrief(evidence, options.brief, options['pull-request']);
  }
  const json = JSON.stringify(evidence, null, 2) + '\n';
  if (options.output) {
    mkdirSync(options.output, { recursive: true });
    writeFileSync(join(options.output, 'AGENTS.md'), evidence.guidance + '\n');
    writeFileSync(join(options.output, 'evidence.json'), json);
  }
  process.stdout.write(json);
  if ((options.enforce || evidence.mode === 'required') && evidence.state === 'failure') process.exitCode = 1;
}

function brief(command, args) {
  const fromGithub = command === 'github-brief';
  const { values } = parseArgs({
    args,
    options: {
      'policy-repo': { type: 'string' }, 'policy-commit': { type: 'string' },
      'target-repo': { type: 'string', default: '.' }, 'profile-commit': { type: 'string' },
      output: { type: 'string' },
      ...(fromGithub ? { repo: { type: 'string' }, pr: { type: 'string' }, commit: { type: 'string' } }
        : { task: { type: 'string' } }),
    },
  });
  const result = prepareBrief({
    policyRepo: values['policy-repo'], policyCommit: values['policy-commit'],
    targetRepo: values['target-repo'], profileCommit: values['profile-commit'],
    task: values.task,
    ticket: fromGithub ? readGitHubTicket({ repo: values.repo, pullRequest: Number(values.pr), commit: values.commit }) : undefined,
    output: values.output, kitVersion: version,
  });
  console.log(JSON.stringify(result, null, 2));
}

function coordinate(command, args) {
  const { values } = parseArgs({
    args,
    options: command === 'record'
      ? { state: { type: 'string' }, work: { type: 'string' }, evidence: { type: 'string' } }
      : {
          config: { type: 'string' }, state: { type: 'string' },
          ...(command !== 'watch' ? { run: { type: 'boolean' } } : {}),
          ...(command === 'github' ? { publish: { type: 'boolean' }, 'report-url': { type: 'string' } } : {}),
          ...(command === 'watch' ? { publish: { type: 'boolean' } } : {}),
        },
  });
  if (!values.state || (command === 'record' ? !values.work || !values.evidence : !values.config)) {
    throw new Error('Arguments incomplets. Utiliser --help.');
  }
  const options = {
    configPath: values.config, stateDir: values.state, run: values.run, kitVersion: version,
    publish: values.publish, reportUrl: values['report-url'],
  };
  const result = command === 'record'
    ? recordEvidence(values.state, values.work, JSON.parse(readFileSync(values.evidence, 'utf8')))
    : { github: reconcileGithub, reconcile, watch: watchGithub }[command](options);
  process.stdout.write(JSON.stringify(result, null, 2) + '\n');
  if (result.errors?.length) process.exitCode = 2;
}

function gate(command, args) {
  const extra = command === 'merge'
    ? { base: { type: 'string' }, execute: { type: 'boolean' }, ruleset: { type: 'string' } }
    : { run: { type: 'boolean' }, github: { type: 'boolean' } };
  const { values } = parseArgs({
    args,
    options: {
      config: { type: 'string' }, state: { type: 'string' }, project: { type: 'string' },
      pr: { type: 'string' }, commit: { type: 'string' }, ...extra,
    },
  });
  const pullRequest = Number(values.pr);
  if (!values.config || !values.state || !values.project || !gitSha.test(values.commit) ||
      !/^[1-9]\d*$/.test(values.pr) || !Number.isSafeInteger(pullRequest)) {
    throw new Error('Le contrôle obligatoire demande le projet, le numéro de PR et le SHA complet du commit.');
  }
  const options = {
    configPath: values.config, stateDir: values.state, kitVersion: version,
    selection: { project: values.project, pullRequest, commit: values.commit, mode: 'required' },
  };
  if (command === 'merge') {
    const result = mergeGithub({
      ...options, base: values.base, execute: values.execute,
      ruleset: values.ruleset === undefined ? undefined : Number(values.ruleset),
    });
    process.stdout.write(JSON.stringify(result, null, 2) + '\n');
    process.exitCode = result.exitCode;
    return;
  }
  const synchronize = values.github ? reconcileGithub : reconcile;
  const result = synchronize({ ...options, run: values.run });
  const current = result.current[0];
  process.stdout.write(JSON.stringify({
    current, executedEvidence: result.executedEvidence ?? [], errors: result.errors ?? [],
  }, null, 2) + '\n');
  process.exitCode = result.errors?.length || current.decision.effectiveStatus === 'error'
    ? 2 : current.decision.conditionMet ? 0 : 1;
}

const [command, ...args] = process.argv.slice(2);
try {
  switch (command) {
    case '--version': console.log(version); break;
    case '--help':
    case undefined: console.log(help); break;
    case 'releases': releases(args); break;
    case 'merge-protection': mergeProtection(args); break;
    case 'merge-installation': mergeInstallation(args); break;
    case 'init': init(args); break;
    case 'catalog':
    case 'onboard': adoption(command, args); break;
    case 'github-approve-profile': approveProfile(args); break;
    case 'check': check(args); break;
    case 'brief':
    case 'github-brief': brief(command, args); break;
    case 'gate':
    case 'merge': gate(command, args); break;
    case 'reconcile':
    case 'github':
    case 'watch':
    case 'record': coordinate(command, args); break;
    default: throw new Error(`Commande inconnue : ${command}. Utiliser --help.`);
  }
} catch (error) {
  console.error(error.message);
  process.exitCode = 2;
}
