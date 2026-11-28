/**
 * Client of the local API served by `openguildkit ui`. Every call goes to the same origin with the
 * session token; the server runs the CLI command and returns its exit code, output and parsed JSON.
 */
export interface Session {
  app: 'openguildkit-ui';
  version: string;
  token: string;
  project: { root: string; name: string; initialized: boolean };
  /** What the project keeps for the page (#463); absent from a server older than this page. */
  prefs?: ServerPrefs;
  human_only: string[];
}

/** The preferences `POST /api/prefs` accepts: these keys only, a name on one line of at most 80 characters. */
export interface ServerPrefs {
  mode?: 'explorer' | 'focus';
  motion?: 'system' | 'reduced';
  shortcuts?: 'on' | 'off';
  decider?: string;
  signer?: string;
}

/** reason: the code of a refusal, next to the command to type (a refused batch entry, a CLI refusal at a terminal). */
export interface CliResult<T = unknown> {
  code: number;
  stdout: string;
  stderr: string;
  json: T | null;
  command?: string | null;
  reason?: string | null;
  restored?: boolean;
}

/**
 * A refusal or a failed command. `command` is what a person types in a terminal instead; `reason` is the stable
 * code of a refusal of the local server; `lang` is 'en' when the message is the server's or the CLI's own English.
 */
interface ApiErrorDetails {
  command?: string | null;
  result?: CliResult;
  reason?: string | null;
  lang?: 'en';
}
export class ApiError extends Error {
  command: string | null;
  result?: CliResult;
  reason: string | null;
  lang?: 'en';
  constructor(
    message: string,
    public status: number,
    details: ApiErrorDetails = {},
  ) {
    super(message);
    this.command = details.command ?? null;
    this.result = details.result;
    this.reason = details.reason ?? null;
    this.lang = details.lang;
  }
}

let session: Session | null = null;

/** Detects the local API. Static hosting (the demo) answers with HTML or 404, never this JSON. */
export async function detectSession(): Promise<Session | null> {
  try {
    const response = await fetch('./api/session', { headers: { Accept: 'application/json' }, cache: 'no-store' });
    if (!response.ok || !(response.headers.get('content-type') ?? '').includes('application/json')) return null;
    const data = (await response.json()) as Session;
    if (data.app !== 'openguildkit-ui' || !data.token) return null;
    session = data;
    return data;
  } catch {
    return null;
  }
}

export const currentSession = () => session;

async function post<T>(path: string, body: unknown): Promise<T> {
  if (!session) throw new ApiError('Aucune session : recharge la page.', 0);
  const send = () =>
    fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-OGK-Token': session!.token, Accept: 'application/json' },
      body: JSON.stringify(body),
      cache: 'no-store',
    });
  let response: Response;
  try {
    response = await send();
  } catch {
    // One retry: a refused connection during a burst of requests is not a stopped server.
    try {
      await new Promise((resolve) => setTimeout(resolve, 400));
      response = await send();
    } catch {
      throw new ApiError('Le serveur local ne répond plus. Relance « openguildkit ui » dans ton terminal.', 0);
    }
  }
  const data = await response.json().catch(() => ({ error: `Réponse illisible (${response.status})` }));
  if (!response.ok) {
    const refusal = data as { error?: string; command?: string; reason?: string };
    throw new ApiError(String(refusal.error ?? response.statusText), response.status, {
      command: refusal.command ?? null,
      reason: refusal.reason ?? null,
      lang: 'en',
    });
  }
  return data as T;
}

/** Message of a failed command: the CLI writes "OpenGuildKit: …" on stderr. */
export const cliMessage = (r: CliResult) => (r.stderr || r.stdout).trim().replace(/^OpenGuildKit:\s*/gm, '') || `Code de sortie ${r.code}`;
/** The error of a failed command, in the CLI's English, with the command and refusal code the server added. */
export const cliError = (r: CliResult) =>
  new ApiError(cliMessage(r), 200, {
    command: r.command ?? null,
    reason: r.reason ?? null,
    result: r,
    lang: r.stderr || r.stdout ? 'en' : undefined,
  });

/**
 * Options of a command: `raw` keeps the printed text of a JSON answer (copied as is), `omit` removes keys
 * the screen does not show, at any depth, before they leave the server.
 */
export interface RunOptions {
  allowFailure?: boolean;
  raw?: boolean;
  omit?: string[];
}

export async function run<T = unknown>(argv: string[], uploads?: Record<string, string>, opts: RunOptions = {}): Promise<CliResult<T>> {
  const result = await post<CliResult<T>>('./api/run', { argv, uploads: uploads ?? {}, raw: opts.raw ?? false, omit: opts.omit });
  if (result.code !== 0 && !opts.allowFailure) throw cliError(result);
  return result;
}

export async function batch(commands: Record<string, string[]>, opts: { omit?: string[] } = {}): Promise<Record<string, CliResult>> {
  return (await post<{ results: Record<string, CliResult> }>('./api/run', { batch: commands, omit: opts.omit })).results;
}

export interface FileEntry {
  name: string;
  kind: 'file' | 'folder';
  size: number;
  modified: number;
}
export const listFiles = async (path: string) => (await post<{ entries: FileEntry[] }>('./api/files/list', { path })).entries;
/** The text of a project file, or null when the project has not created it yet. */
export const readFile = async (path: string) => (await post<{ path: string; text: string | null }>('./api/files/read', { path })).text;
/** The text of a file that must exist. */
export async function readText(path: string) {
  const text = await readFile(path);
  if (text === null) throw new ApiError(`Le fichier ${path} n’existe pas.`, 404);
  return text;
}
const parseOrNull = <T>(text: string | null) => (text === null ? null : (JSON.parse(text) as T));
/** A JSON file of the project, or null when it does not exist yet. */
export const readJson = async <T>(path: string) => parseOrNull<T>(await readFile(path));
export const writeFile = (path: string, text: string) => post<{ written: boolean }>('./api/files/write', { path, text });
export const saveProfile = (text: string) => post<CliResult>('./api/profile/save', { text });
export const savePrefs = (prefs: ServerPrefs) => post<{ prefs: ServerPrefs }>('./api/prefs', { prefs });

// Words each shell reads as typed, as src/openguildkit/shell.py lists them (letters and digits are Unicode ones).
// Quoted anyway: a leading = (zsh reads a command path), a leading @ or a comma in PowerShell (splatting, a list), and
// a tilde that does not follow a word character.
const POSIX_PLAIN = /^(?:[\p{L}\p{N}_%+,./@-]~?|:)(?:[\p{L}\p{N}_%+,./@-]~?|[=:])*$/u;
const POWERSHELL_PLAIN = /^(?:[\p{L}\p{N}_%+./-]~?|[=:])(?:[\p{L}\p{N}_%+./@-]~?|[=:])*$/u;

/**
 * Quotes an argument the way a person types it, as shell_word does: single quotes work the same in PowerShell and
 * POSIX shells; only the escape of a single quote differs ('\'' in sh, a doubled quote in PowerShell, which also
 * closes a string at a typographic one: ‘ ’ ‚ ‛).
 */
export const quoteFor = (value: string, windows: boolean) =>
  (windows ? POWERSHELL_PLAIN : POSIX_PLAIN).test(value)
    ? value
    : `'${value.replace(windows ? /['‘’‚‛]/g : /'/g, windows ? '$&$&' : "'\\''")}'`;
export const shellQuote = (value: string) => quoteFor(value, /^[A-Za-z]:[\\/]/.test(session?.project.root ?? ''));
/** A path the CLI records (absolute, the project's own separators) as the file API takes it: relative, with slashes. */
export function projectPath(path: string, root = session?.project.root ?? '') {
  const normalized = path.replace(/\\/g, '/');
  const base = root.replace(/\\/g, '/').replace(/\/$/, '');
  return base && normalized.toLowerCase().startsWith(`${base.toLowerCase()}/`) ? normalized.slice(base.length + 1) : normalized;
}
export const terminalCommand = (argv: string[]) =>
  ['openguildkit', '--project', shellQuote(session?.project.root ?? '.'), ...argv.map(shellQuote)].join(' ');

/** Many read commands in as few requests as the server allows (40 per batch); a failed one gives null. */
export async function batchJson<T>(commands: Record<string, string[]>, opts: { omit?: string[] } = {}): Promise<Record<string, T | null>> {
  const entries = Object.entries(commands);
  const out: Record<string, T | null> = {};
  for (let i = 0; i < entries.length; i += 40) {
    const results = await batch(Object.fromEntries(entries.slice(i, i + 40)), opts);
    Object.entries(results).forEach(([key, r]) => {
      out[key] = r.code === 0 ? (r.json as T) : null;
    });
  }
  return out;
}
