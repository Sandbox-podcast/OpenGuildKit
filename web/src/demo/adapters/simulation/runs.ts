/**
 * Demo control runner. Steps are deterministic; the verdict of a control is computed from the
 * content of the evaluated deliverable version (for example the tenant filter in the SQL of the
 * export code), so that a correction really changes the outcome. A tool error injected from the
 * demo settings stops the run with a technical error — never with a passing result (RG-27).
 */
import type { Content, ResultState } from '@/demo/domain/types';

export interface Evaluation { outcome: ResultState; observation: string; finding?: { title: string; severity: 'critique' | 'haute' | 'moyenne' | 'basse'; remediation: string } }

export const CONTROL_STEPS = ['Préparer l’environnement simulé', 'Charger la version évaluée', 'Exécuter les vérifications', 'Consigner le résultat et la preuve'];
export const SKILL_STEPS = ['Lire le contexte de la quête', 'Appliquer les règles du Blueprint', 'Rédiger le livrable', 'Enregistrer une nouvelle version'];
export const TOOL_ERROR = 'Erreur d’outil simulée : le service de vérification n’a pas répondu dans le délai (récupérable, relancez l’exécution).';

const textOf = (c?: Content): string => {
  if (!c) return '';
  switch (c.kind) {
    case 'files': return c.files.map((f) => f.body).join('\n');
    case 'markdown': return c.body;
    case 'api': return c.spec;
    case 'component': return JSON.stringify(c);
    default: return JSON.stringify(c);
  }
};

const STRATEGIES: Record<string, (c?: Content) => Evaluation> = {
  'tenant-isolation': (c) => {
    const sql = [...textOf(c).matchAll(/'(SELECT[^']+)'/gi)].map((m) => m[1]);
    if (!sql.length) return { outcome: 'inconclusive', observation: 'Aucune requête SQL trouvée dans la version évaluée : impossible de conclure.' };
    const leaking = sql.filter((q) => /FROM\s+(contacts|accounts|activities)/i.test(q) && !/tenant_id\s*=/.test(q));
    return leaking.length
      ? { outcome: 'failed', observation: `Requête sans filtre client : « ${leaking[0]} ». Les données d’autres clients peuvent être exportées.`, finding: { title: 'Défaut d’isolation entre clients dans l’export', severity: 'critique', remediation: 'Ajouter « tenant_id = $1 » à la requête et couvrir le cas par un test à deux clients.' } }
      : { outcome: 'passed', observation: `${sql.length} requête(s) vérifiée(s) : toutes filtrent par tenant_id.` };
  },
  'tests-present': (c) => {
    const n = (textOf(c).match(/\bit\(/g) ?? []).length;
    return n === 0 ? { outcome: 'inconclusive', observation: 'Aucun cas de test exécutable trouvé.' } : { outcome: 'passed', observation: `${n} cas de test exécutés dans l’environnement simulé, tous réussis.` };
  },
  'permission-check': (c) => {
    const t = textOf(c);
    if (!t) return { outcome: 'inconclusive', observation: 'Aucun code à évaluer.' };
    return /requirePermission\([^)]*'export'\)/.test(t)
      ? { outcome: 'passed', observation: 'Le point d’entrée exige la permission « export ».' }
      : { outcome: 'failed', observation: 'Le point d’entrée ne vérifie pas la permission « export ».', finding: { title: 'Permission d’export non vérifiée', severity: 'haute', remediation: 'Appeler requirePermission(user, \'export\') avant toute opération.' } };
  },
  'deps-scan': (c) => {
    const t = textOf(c);
    if (/csv-forge"?\s*[:@]?\s*"?\^?2\.3\.\d/.test(t) && !/escapeFormula/.test(t)) return { outcome: 'failed', observation: 'csv-forge 2.3.1 est concernée par la vulnérabilité simulée SIM-2026-0042.', finding: { title: 'Dépendance vulnérable (simulation SIM-2026-0042)', severity: 'haute', remediation: 'Échapper les cellules commençant par =, +, -, @ puis passer à csv-forge 2.4.0.' } };
    return { outcome: 'passed', observation: 'Aucune dépendance connue comme vulnérable dans la base de démonstration.' };
  },
  'a11y-check': (c) => {
    if (c?.kind !== 'component') return { outcome: 'not_applicable', observation: 'Le livrable n’est pas un composant.' };
    const names = c.variants.map((v) => String(v.props.state));
    const missing = ['error', 'disabled'].filter((n) => !names.includes(n));
    return missing.length || !/aria-live/.test(c.description)
      ? { outcome: 'failed', observation: `États manquants ou annonce absente : ${missing.join(', ') || 'aria-live'}.`, finding: { title: 'États accessibles incomplets', severity: 'moyenne', remediation: 'Ajouter les états manquants et une annonce aria-live.' } }
      : { outcome: 'passed', observation: `${names.length} états vérifiés ; annonce aria-live présente ; texte et symbole pour chaque état.` };
  },
  'doc-review': (c) => {
    const t = textOf(c);
    return t.length > 200 ? { outcome: 'passed', observation: 'Structure du guide conforme (objectif, étapes, limites).' } : { outcome: 'inconclusive', observation: 'Document trop court pour être évalué.' };
  },
};

export const STRATEGY_LABELS: Record<string, string> = {
  'tenant-isolation': 'Analyse des requêtes SQL du code proposé',
  'tests-present': 'Exécution simulée des tests',
  'permission-check': 'Recherche de la vérification de permission',
  'deps-scan': 'Base de vulnérabilités de démonstration',
  'a11y-check': 'Revue des états et annonces du composant',
  'doc-review': 'Revue de structure documentaire',
};

export function evaluateControl(strategy: string, content?: Content): Evaluation {
  const fn = STRATEGIES[strategy];
  return fn ? fn(content) : { outcome: 'inconclusive', observation: `Stratégie de simulation « ${strategy} » inconnue.` };
}

/** Short, stable fingerprint shown on evidence (not a cryptographic proof). */
export function digest(text: string): string {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return `sim-${(h >>> 0).toString(16).padStart(8, '0')}`;
}
