import { committedFile, git, gitSha, isGitPath, parseProfile, readRule } from './check.mjs';
import { parseJsonObject } from './json.mjs';

const questions = {
  project: 'Quel projet et quel dépôt sont concernés ?',
  owner: 'Quel mainteneur approuve le profil ?',
  stack: 'Quelles technologies sont utilisées ?',
  environments: 'Quels environnements sont concernés ?',
  conventions: 'Quelles conventions existantes faut-il respecter ?',
  testCommands: 'Quelles commandes de vérification sont approuvées ?',
  sensitivePaths: 'Quelles zones du dépôt sont sensibles ?',
  tools: 'Quels outils sont autorisés ?',
  ticketTracker: 'Où l’équipe suit-elle ses tickets ? Indiquer « aucun » le cas échéant.',
  dataAccess: 'Quelles données l’agent peut-il consulter ?',
  aiModels: 'Quels modèles sont autorisés ?',
  executionBudget: 'Quel budget d’exécution a été approuvé ?',
  requiredApprovals: 'Quelles validations sont requises ?',
  references: 'Quels référentiels ou conventions internes s’appliquent ?',
  ruleId: 'Quelle règle du catalogue appliquer en observation ?',
  targetPath: 'Quel fichier du dépôt doit être vérifié ?',
};

const arrays = ['stack', 'environments', 'conventions', 'testCommands', 'sensitivePaths',
  'tools', 'dataAccess', 'aiModels', 'requiredApprovals', 'references'];
const text = value => typeof value === 'string' && value.trim().length > 0;

export function loadCatalog({ policyRepo, policyCommit, catalogPath = 'policy/catalog.json' }) {
  if (!policyRepo || !gitSha.test(policyCommit) || !isGitPath(catalogPath)) {
    throw new Error('Le catalogue demande un dépôt, un SHA complet et un chemin Git relatif.');
  }
  const catalog = parseJsonObject(committedFile(policyRepo, policyCommit, catalogPath), catalogPath);
  if (catalog.schemaVersion !== 1 || !Array.isArray(catalog.rules) || !catalog.rules.length) {
    throw new Error('Catalogue invalide : au moins une règle est requise.');
  }
  const ids = new Set();
  const rules = catalog.rules.map(entry => {
    if (![entry.id, entry.owner, entry.rationale, entry.guidance].every(text) ||
        !Array.isArray(entry.scope) || !entry.scope.length || !entry.scope.every(text) ||
        entry.evaluation !== 'automated' || !isGitPath(entry.policyPath) ||
        !isGitPath(entry.targetPath) || ids.has(entry.id)) {
      throw new Error(`Entrée de catalogue invalide : ${entry.id}`);
    }
    ids.add(entry.id);
    const source = readRule(policyRepo, policyCommit, { ...entry, ruleId: entry.id });
    if (source.format !== 'catalog' && (!Number.isSafeInteger(source.version) || source.version < 1)) {
      throw new Error(`La règle versionnée ne correspond pas au catalogue : ${entry.id}`);
    }
    return { ...entry, version: source.version, supported: entry.id === 'export-link-expiry' };
  });
  return { schemaVersion: 1, policyCommit, catalogPath, rules };
}

export function questionnaire({ repo, ref, catalog, inspect }) {
  const commit = git(repo, 'rev-parse', '--verify', '--end-of-options', `${ref}^{commit}`).toString().trim();
  if (!gitSha.test(commit)) throw new Error('Révision d’inventaire invalide.');
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
  if (!answers || typeof answers !== 'object') throw new Error('Le questionnaire doit contenir ses réponses.');
  const incomplete = Object.keys(questions).filter(field => arrays.includes(field)
    ? !Array.isArray(answers[field]) || !answers[field].every(text)
    : !text(answers[field]));
  if (incomplete.length) throw new Error(`Réponses manquantes ou invalides : ${incomplete.join(', ')}.`);
  const rule = catalog.rules.find(item => item.id === answers.ruleId);
  if (!rule?.supported || !gitSha.test(commit)) {
    throw new Error('Règle du catalogue indisponible dans ce kit ou commit d’inventaire invalide.');
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
