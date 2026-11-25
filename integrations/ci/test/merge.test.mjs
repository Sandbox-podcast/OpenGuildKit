import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mergeGithub } from '../lib/merge.mjs';
import { inspectMergeInstallation, inspectMergeProtection } from '../lib/merge-protection.mjs';

test('merge checks the waiver clock after the final read and sends the exact head to GitHub', () => {
  const head = '1'.repeat(40);
  const baseCommit = '2'.repeat(40);
  const mergeCommit = '3'.repeat(40);
  const project = 'team/project';
  const expiresAt = '2026-11-20T11:00:00Z';
  const pull = 'repos/team/project/pulls/3';
  for (const scenario of ['preview', 'expired', 'changed-base', 'changed-rule', 'inactive-protection', 'merge']) {
    const requests = [];
    const reads = [];
    const evaluations = [];
    const api = (endpoint, ...args) => {
      if (endpoint.endsWith('/merge')) {
        requests.push([endpoint, ...args]);
        return { merged: true, sha: mergeCommit };
      }
      if (endpoint === 'repos/team/project/rules/branches/main?per_page=100') {
        return scenario === 'inactive-protection' ? [[]] : [[{
          ruleset_id: 40, ruleset_source_type: 'Repository', ruleset_source: project, type: 'update',
        }]];
      }
      assert.equal(endpoint, pull);
      reads.push(endpoint);
      return {
        state: 'open', draft: false, head: { sha: head },
        base: {
          ref: 'main', repo: { full_name: project },
          sha: scenario === 'changed-base' && reads.length === 2 ? '4'.repeat(40) : baseCommit,
        },
      };
    };
    const reconcile = ({ run, selection }) => {
      assert.deepEqual(selection, { project, pullRequest: 3, commit: head, mode: 'required' });
      evaluations.push(run);
      return { current: [{ decision: !run && scenario === 'changed-rule'
        ? { conditionMet: false, effectiveStatus: 'pending', waiver: null }
        : { conditionMet: true, effectiveStatus: 'waived', waiver: { expiresAt } },
      }] };
    };
    const clock = () => Date.parse(expiresAt) - (scenario === 'expired' && reads.length === 2 ? 0 : 1);
    const invoke = () => mergeGithub({
      base: 'main', ruleset: 40, execute: scenario !== 'preview', selection: { project, pullRequest: 3, commit: head },
    }, { api, reconcile, clock });

    if (scenario === 'changed-base') {
      assert.throws(invoke, /The target branch changed during the check/);
    } else {
      const result = invoke();
      assert.equal(result.exitCode, { expired: 1, 'changed-rule': 1, 'inactive-protection': 2 }[scenario] ?? 0);
      assert.equal(result.reason, {
        expired: 'waiver-expired', 'changed-rule': 'pending', 'inactive-protection': 'inactive-branch-protection',
      }[scenario] ?? null);
      assert.deepEqual(result.merge, scenario === 'merge' ? { commit: mergeCommit, head } : null);
    }
    assert.deepEqual(evaluations, scenario === 'preview' ? [true] : [true, false]);
    assert.deepEqual(requests, scenario === 'merge' ? [[`${pull}/merge`, '-X', 'PUT', '-f', `sha=${head}`]] : []);
  }
});

test('the administrator check only approves a ruleset dedicated to the expected app', () => {
  const request = { repo: 'team/repo', base: 'pilot/base', ruleset: 42, appId: 7 };
  const actor = { actor_id: 7, actor_type: 'Integration', bypass_mode: 'pull_request' };
  const rule = { ruleset_id: 42, ruleset_source_type: 'Repository', ruleset_source: 'Team/Repo', type: 'update' };
  const verify = override => inspectMergeProtection(request, endpoint => endpoint.includes('/rules/branches/')
    ? [[rule]] : { enforcement: 'active', rules: [{ type: 'update' }], bypass_actors: [actor], ...override });
  assert.equal(verify().approved, true);
  assert.equal(verify({ bypass_actors: [] }).approved, false);
  assert.equal(verify({ bypass_actors: [actor, { ...actor, actor_id: 9 }] }).approved, false);
  assert.equal(verify({ bypass_actors: [{ ...actor, bypass_mode: 'always' }] }).approved, false);
  assert.equal(verify({ rules: [{ type: 'update' }, { type: 'pull_request' }] }).approved, false);
  assert.throws(() => verify({ bypass_actors: undefined }), /GitHub hides the bypass actors/);
});

test('the merge installation must match the app and be scoped to the target repository', () => {
  const options = { repo: 'team/repo', appSlug: 'merge-app', appId: 7 };
  const app = { id: 7, slug: 'merge-app' };
  const scoped = { total_count: 1, repositories: [{ full_name: 'Team/Repo' }] };
  assert.equal(inspectMergeInstallation(options, endpoint => endpoint.startsWith('apps/') ? app : scoped).approved, true);
  const extra = { ...scoped, total_count: 2 };
  assert.equal(inspectMergeInstallation(options, endpoint => endpoint.startsWith('apps/') ? app : extra).approved, false);
  const wrong = inspectMergeInstallation(options, endpoint => {
    assert.equal(endpoint, 'apps/merge-app');
    return { ...app, id: 8 };
  });
  assert.equal(wrong.approved, false);
  assert.equal(wrong.scoped, null);
});
