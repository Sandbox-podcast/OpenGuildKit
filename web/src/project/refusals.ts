import { ApiError } from './api';

/**
 * French texts of the local server's refusals, by their stable code (webui.REFUSALS). A refusal without a code, or
 * with a code the page does not know, keeps the server's English text, marked as English where it is shown.
 */
export const REFUSAL_FR: Record<string, string> = {
  'approve-at-terminal':
    'Approuver une tâche demande une personne devant son terminal, ou une signature dans un projet à approbation signée. L’interface n’enregistre jamais une approbation.',
  'cannot-run-at-terminal':
    'Déclarer qu’une commande de vérification ne peut pas tourner ici, ou retirer cette déclaration, se fait par la personne elle-même, dans son terminal.',
  'clear-at-terminal': 'Lever un point bloquant sans signature se fait par la personne elle-même, dans son terminal.',
  'complete-at-terminal':
    'Clore une tâche malgré des points sensibles demande la personne qui le confirme, dans son terminal, avec ses initiales.',
  'live-plan-at-terminal': 'Brancher un vrai serveur MCP se confirme dans un terminal : il accède aux données de l’entreprise.',
  'waiver-at-terminal': 'Une dérogation se fait par la personne nommée, dans son terminal.',
  'external-action-at-terminal': 'Autoriser une action externe demande une personne devant son terminal.',
  'alert-accept-at-terminal': 'Accepter le risque d’une alerte confirmée se fait par une personne, dans son terminal.',
  'alert-severity-at-terminal': 'Fixer la sévérité d’une alerte se fait par une personne, dans son terminal.',
  'alert-status-at-terminal':
    'Écarter une alerte critique, ou revenir sur une alerte critique confirmée, se fait par une personne, dans son terminal, avec ses initiales et la raison.',
  'withdraw-at-terminal': 'Retirer une approbation se fait par une personne, dans son terminal.',
  'person-at-terminal': 'Cette décision demande une personne devant son terminal : l’interface ne l’enregistre pas.',
  'weakens-protection':
    'Ce changement affaiblit une protection du profil : c’est la décision d’une personne, dans son terminal. Rien n’a été écrit.',
  'invalid-profile': 'Le profil n’est pas valide : rien n’a été écrit, la version précédente reste en place.',
  'send-setup-answers':
    'Depuis la page, l’installation envoie les réponses du questionnaire : elle ne répond pas aux questions posées dans un terminal.',
  'send-task-answers':
    'Depuis la page, une consultation envoie les réponses du questionnaire : elle ne répond pas aux questions posées dans un terminal.',
  'stale-token': 'Le serveur local a redémarré : ouvre la nouvelle adresse que « openguildkit ui » a écrite dans ton terminal.',
  'open-printed-link':
    'Ouvre l’adresse que « openguildkit ui » a écrite dans ton terminal (http://ogk-….localhost:…/?key=…) : elle seule ouvre la session de ce projet.',
  'outside-project': 'Ce chemin sort du projet : donne un chemin relatif à sa racine, avec des barres obliques.',
  'secret-file': 'L’interface ne lit pas ce fichier : il ressemble à un secret, à un fichier de jeton, ou il est dans .git.',
  'not-readable': 'L’interface ne lit que les fichiers Markdown, JSON, YAML et texte.',
  'too-large': 'Le fichier ou la requête est trop lourd pour l’interface.',
  'not-in-page': 'Cette commande ne se lance pas depuis la page : elle appartient au terminal ou à l’agent hôte.',
  'not-initialized': 'Le projet n’est pas encore installé : installe-le d’abord.',
  'project-busy': 'Une autre commande modifie le projet en ce moment : réessaie dans un instant.',
  'foreign-page': 'La requête ne vient pas de la page de ce serveur : ouvre l’interface depuis l’adresse écrite dans ton terminal.',
  'bad-request': 'La page a envoyé une requête que le serveur local ne comprend pas.',
  'not-found': 'Le serveur local ne connaît pas cette adresse.',
  'server-error': 'Le serveur local a rencontré une erreur : le détail est dans le terminal où tourne « openguildkit ui ».',
};

/** What the page says for a refusal: the French text of its code, or the server's English text, marked as such. */
export function refusalText(reason: string | null | undefined, english: string): { text: string; lang?: 'en' } {
  return reason && REFUSAL_FR[reason] ? { text: REFUSAL_FR[reason] } : { text: english, lang: 'en' };
}

/**
 * French texts of the CLI's refusals of a result (task result), each with what to do in the page. The CLI's
 * English stays as the detail. results._check_entry and results._text write them.
 */
const CLI_FR: [RegExp, (m: RegExpExecArray) => string][] = [
  [
    /(\S+) owner must contain text\. A passed evidence needs evidence and owner/,
    (m) => `${m[1]} : indique dans « Fournie par » la personne qui a fourni ou confirmé le document, puis enregistre à nouveau.`,
  ],
  [
    /(\S+) evidence must contain text\./,
    (m) => `${m[1]} : indique la preuve, un chemin du projet ou un lien https, puis enregistre à nouveau.`,
  ],
  [
    /(\S+) (?:reason|owner) must contain text\./,
    (m) => `${m[1]} : indique un motif et un responsable (tes initiales), puis enregistre à nouveau.`,
  ],
  [
    /^(\S+): (.+) does not exist in the project\.$/,
    (m) =>
      `${m[1]} : ${m[2]} n’existe pas dans le projet. Donne un chemin relatif à sa racine, ou un lien https, puis enregistre à nouveau.`,
  ],
  [
    /^(\S+) must be supplied because .+?: ask (.+?) for (.+?) \(a project path or an https link\)\. The agent does not write it\.$/s,
    (m) =>
      `${m[1]} doit être fournie : demande « ${m[3]} » à ${m[2]}, puis choisis « réussie » avec son chemin et la personne qui l’a fournie. L’agent ne la rédige pas.`,
  ],
];
/** The French text of a known CLI refusal, or null. */
export function cliText(message: string): string | null {
  for (const [re, fr] of CLI_FR) {
    const m = re.exec(message.trim());
    if (m) return fr(m);
  }
  return null;
}

/** The answers task result did not record ("Not recorded: …" on stderr, exit 0), in French when the page knows them. */
export function notRecorded(stderr: string): { text: string; lang?: 'en' }[] {
  return stderr
    .split('\n')
    .map((line) => /^(?:OpenGuildKit: )?Not recorded: (.*?)(?: The earlier answer stays recorded\.)?$/.exec(line.trim()))
    .filter((m): m is RegExpExecArray => !!m)
    .map((m) => {
      const fr = cliText(m[1]!);
      return fr ? { text: fr } : { text: m[1]!, lang: 'en' as const };
    });
}

/** What the page shows for an error: the French text of a known refusal, with the server's words as detail, or the
 * message itself, marked English when it is the server's or the CLI's own. */
export function errorText(error: Error): { text: string; lang?: 'en'; detail?: string } {
  if (!(error instanceof ApiError)) return { text: error.message };
  const shown = refusalText(error.reason, error.message);
  if (!shown.lang) return { text: shown.text, detail: error.message };
  const known = cliText(error.message);
  return known ? { text: known, detail: error.message } : { text: error.message, lang: error.lang };
}
