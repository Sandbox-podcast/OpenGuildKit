import { committedFile, git, gitSha, isGitPath, parseProfile, readRule } from './check.mjs';
import { parseJsonObject } from './json.mjs';

const questions = {
  project: 'Which project and which repository does this concern?',
  owner: 'Which maintainer approves the profile?',
  stack: 'Which technologies are used?',
  environments: 'Which environments does this cover?',
  conventions: 'Which existing conventions must be followed?',
  testCommands: 'Which verification commands are approved?',
  sensitivePaths: 'Which areas of the repository are sensitive?',
  tools: 'Which tools are allowed?',
  ticketTracker: 'Where does the team track its tickets? Write "none" if there is no tracker.',
  dataAccess: 'Which data can the agent read?',
  aiModels: 'Which models are allowed?',
  executionBudget: 'Which execution budget has been approved?',
  requiredApprovals: 'Which approvals are required?',
  references: 'Which internal standards or conventions apply?',
  ruleId: 'Which catalog rule should apply in observation mode?',
  targetPath: 'Which file of the repository must be checked?',
};

const arrays = ['stack', 'environments', 'conventions', 'testCommands', 'sensitivePaths',
  'tools', 'dataAccess', 'aiModels', 'requiredApprovals', 'references'];
const text = value => typeof value === 'string' && value.trim().length > 0;

export function loadCatalog({ policyRepo, policyCommit, catalogPath = 'policy/catalog.json' }) {
  if (!policyRepo || !gitSha.test(policyCommit) || !isGitPath(catalogPath)) {
    throw new Error('The catalog needs a repository, a full SHA and a relative Git path.');
  }
  const catalog = parseJsonObject(committedFile(policyRepo, policyCommit, catalogPath), catalogPath);
  if (catalog.schemaVersion !== 1 || !Array.isArray(catalog.rules) || !catalog.rules.length) {
    throw new Error('Invalid catalog: at least one rule is required.');
  }
  const ids = new Set();
  const rules = catalog.rules.map(entry => {
    if (![entry.id, entry.owner, entry.rationale, entry.guidance].every(text) ||
        !Array.isArray(entry.scope) || !entry.scope.length || !entry.scope.every(text) ||
        entry.evaluation !== 'automated' || !isGitPath(entry.policyPath) ||
        !isGitPath(entry.targetPath) || ids.has(entry.id)) {
      throw new Error(`Invalid catalog entry: ${entry.id}`);
    }
    ids.add(entry.id);
    const source = readRule(policyRepo, policyCommit, { ...entry, ruleId: entry.id });
    if (source.format !== 'catalog' && (!Number.isSafeInteger(source.version) || source.version < 1)) {
      throw new Error(`The versioned rule does not match the catalog: ${entry.id}`);
    }
    return { ...entry, version: source.version, supported: entry.id === 'export-link-expiry' };
  });
  return { schemaVersion: 1, policyCommit, catalogPath, rules };
}

export function questionnaire({ repo, ref, catalog, inspect }) {
  const commit = git(repo, 'rev-parse', '--verify', '--end-of-options', `${ref}^{commit}`).toString().trim();
  if (!gitSha.test(commit)) throw new Error('Invalid inventory revision.');
  const answers = Object.fromEntries(Object.keys(questions).map(field => [field, null]));
  const files = inspect ? new Set(git(repo, 'ls-tree', '-rz', '--name-only', commit).toString('utf8').split('\0')) : new Set();
  const stack = [
    [files.has('package.json'), 'Node.js'],
    [files.has('tsconfig.json'), 'TypeScript'],
    [files.has('pyproject.toml'), 'Python'],
    [files.has('go.mod'), 'Go'],
    [files.has('pom.xml') || files.has('build.gradle'), 'JVM'],
  ].filter(([found]) => found).map(([, name]) => name);
  const tools = [
    [[...files].some(file => file.startsWith('.github/workflows/')), 'GitHub Actions'],
    [files.has('Jenkinsfile'), 'Jenkins'],
    [files.has('.gitlab-ci.yml'), 'GitLab CI'],
  ].filter(([found]) => found).map(([, name]) => name);
  const conventions = ['.editorconfig', 'CONTRIBUTING.md', 'AGENTS.md', '.github/CODEOWNERS', 'CODEOWNERS']
    .filter(file => files.has(file));
  if (stack.length) answers.stack = stack;
  if (tools.length) answers.tools = tools;
  if (conventions.length) answers.conventions = conventions;
  if (files.has('package.json')) {
    try {
      const manifest = JSON.parse(git(repo, 'show', `${commit}:package.json`));
      if (text(manifest.scripts?.test)) answers.testCommands = ['npm test'];
    } catch {
      // An unreadable manifest leaves the test command to be confirmed.
    }
  }
  const candidates = catalog.rules.filter(rule => rule.supported && files.has(rule.targetPath));
  if (candidates.length === 1) {
    [answers.ruleId, answers.targetPath] = [candidates[0].id, candidates[0].targetPath];
  }
  return {
    repositoryCommit: commit, inspection: inspect ? 'git-tree' : 'revision-only', catalog,
    questions, answers, toConfirm: Object.keys(questions),
  };
}

export function proposeProfile({ answers, catalog, commit }) {
  if (!answers || typeof answers !== 'object') throw new Error('The questionnaire must contain its answers.');
  const incomplete = Object.keys(questions).filter(field => arrays.includes(field)
    ? !Array.isArray(answers[field]) || !answers[field].every(text)
    : !text(answers[field]));
  if (incomplete.length) throw new Error(`Missing or invalid answers: ${incomplete.join(', ')}.`);
  const rule = catalog.rules.find(item => item.id === answers.ruleId);
  if (!rule?.supported || !gitSha.test(commit)) {
    throw new Error('Catalog rule not available in this kit, or invalid inventory commit.');
  }
  const profile = {
    schemaVersion: 1,
    owner: answers.owner.trim(),
    policyPath: rule.policyPath,
    targetPath: answers.targetPath,
    ruleId: rule.id,
    adoption: {
      state: 'proposed', mode: 'observation', inventoryCommit: commit, catalogCommit: catalog.policyCommit,
      answers: Object.fromEntries(Object.keys(questions).map(key => [key, answers[key]])),
    },
  };
  parseProfile(JSON.stringify(profile), { allowProposal: true });
  return profile;
}
