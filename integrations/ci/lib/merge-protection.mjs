import { gh } from './github.mjs';

const githubApi = (endpoint, ...args) => JSON.parse(gh('api', endpoint, ...args));
const positiveId = value => Number.isSafeInteger(value) && value > 0;
const repository = /^[a-z\d][a-z\d-]*\/[a-z\d_.-]+$/i;

export function inspectMergeProtection({ repo, base, ruleset, appId }, api = githubApi) {
  if (!repository.test(repo) || !/^[\w./-]+$/.test(base) ||
      !positiveId(ruleset) || (appId !== undefined && !positiveId(appId))) {
    throw new Error('Dépôt GitHub, branche et identifiants de protection valides requis.');
  }
  const endpoint = `repos/${repo}/rules/branches/${encodeURIComponent(base)}?per_page=100`;
  const active = api(endpoint, '--paginate', '--slurp').flat().some(rule =>
    rule.ruleset_id === ruleset && rule.ruleset_source_type === 'Repository' &&
    rule.ruleset_source?.toLowerCase() === repo.toLowerCase() &&
    rule.type === 'update' && rule.parameters?.update_allows_fetch_and_merge !== true);
  let exclusiveApp = null;
  if (active && appId !== undefined) {
    const rules = api(`repos/${repo}/rulesets/${ruleset}?includes_parents=false`);
    if (!Array.isArray(rules.bypass_actors)) {
      throw new Error('GitHub masque les exceptions au compte courant. Utiliser un compte autorisé à modifier la protection.');
    }
    const [actor] = rules.bypass_actors;
    exclusiveApp = rules.enforcement === 'active' && rules.rules?.length === 1 &&
      rules.rules[0].type === 'update' && rules.bypass_actors.length === 1 &&
      actor.actor_type === 'Integration' && actor.actor_id === appId && actor.bypass_mode === 'pull_request';
  }
  const approved = active && (appId === undefined || exclusiveApp === true);
  return { repository: repo, base, ruleset, active, appId, exclusiveApp, approved };
}

export function inspectMergeInstallation({ repo, appSlug, appId }, api = githubApi) {
  if (!repository.test(repo) || !/^[a-z\d][a-z\d-]*$/.test(appSlug) || !positiveId(appId)) {
    throw new Error('Dépôt, nom et identifiant de l’application GitHub valides requis.');
  }
  const app = api(`apps/${appSlug}`);
  const matchingApp = app.id === appId && app.slug === appSlug;
  const result = { repository: repo, appSlug, expectedAppId: appId, observedAppId: app.id, matchingApp };
  if (!matchingApp) return { ...result, scoped: null, approved: false };

  const installation = api('installation/repositories?per_page=2');
  const scoped = installation.total_count === 1 && installation.repositories?.length === 1 &&
    installation.repositories[0].full_name?.toLowerCase() === repo.toLowerCase();
  return { ...result, scoped, approved: scoped };
}
