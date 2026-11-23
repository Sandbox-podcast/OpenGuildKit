import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { ApiError } from '@/project/api';
import { BRAIN_FR, DATA_PHRASE, QUESTION_HELP_FR, QUESTION_UNSURE_FR, brainName, checkOutcome, isRequiredCheck, mustSupplyLabel } from '@/project/labels';
import { cliText, errorText, notRecorded } from '@/project/refusals';

const repo = fileURLToPath(new URL('../../../', import.meta.url));
const files = (dir: string): string[] => readdirSync(dir).flatMap((name) => {
  const path = join(dir, name);
  return statSync(path).isDirectory() ? files(path) : [path];
});

describe('the expected checks table', () => {
  it('says a named evidence that must be supplied is mandatory', () => {
    // task checks --json gives a named evidence must_supply and no mandatory field.
    const evidence = { kind: 'evidence', must_supply: "the task's data is personal", concerned: true, result: null };
    expect(isRequiredCheck(evidence)).toBe(true);
    expect(isRequiredCheck({ kind: 'evidence', must_supply: null, concerned: true, result: null })).toBe(false);
    expect(isRequiredCheck({ kind: 'command', mandatory: true, result: null })).toBe(true);
    expect(isRequiredCheck({ kind: 'rule', mandatory: false, result: null })).toBe(false);
  });

  it('does not ask to report a rule the task is not asked', () => {
    const asideRule = { kind: 'rule', mandatory: false, concerned: false, result: null };
    expect(checkOutcome(asideRule).label).toBe('Non demandée');
    expect(checkOutcome(asideRule).label).not.toBe('À rapporter');
    expect(checkOutcome({ kind: 'rule', mandatory: false, concerned: true, result: null }).label).toBe('À rapporter');
    expect(checkOutcome({ kind: 'rule', concerned: false, result: { status: 'passed' } }).label).toBe('Réussi');
  });

  it('says in French why a named evidence must be supplied', () => {
    expect(mustSupplyLabel("the task's data is personal")).toBe('la tâche touche des données personnelles');
    expect(mustSupplyLabel("its rule or pack is listed in the profile's required_rules")).toMatch(/^sa règle ou son pack/);
    expect(mustSupplyLabel('something new')).toBeNull();
  });
});

describe('French of the task questionnaire and the brains', () => {
  it('agrees the data answer in a sentence', () => {
    expect(DATA_PHRASE.personal).toBe('des données personnelles');
    expect(Object.values(DATA_PHRASE).join(' ')).not.toMatch(/données personnelle\b/);
  });

  it('gives the help and the unsure answer of every task question in French', () => {
    const source = readFileSync(join(repo, 'src', 'openguildkit', 'questionnaire.py'), 'utf-8');
    const block = source.slice(source.indexOf('TASK_QUESTION_HELP = {'));
    const ids = [...block.slice(0, block.indexOf('\n}\n')).matchAll(/^ {4}"([a-z_]+)": \{"help"/gm)].map((m) => m[1]);
    expect(ids).toContain('data');
    for (const id of ids) {
      expect([id, QUESTION_HELP_FR[id]]).toEqual([id, expect.any(String)]);
      expect([id, QUESTION_UNSURE_FR[id]]).toEqual([id, expect.any(String)]);
    }
    expect(QUESTION_UNSURE_FR.data).toMatch(/données personnelles/);
  });

  it('names every brain of the catalog in French', () => {
    const boards = readdirSync(join(repo, 'src', 'openguildkit', 'registry', 'boards')).filter((n) => n.endsWith('.json')).map((n) => n.replace(/\.json$/, ''));
    expect(boards.length).toBeGreaterThan(20);
    for (const id of boards) expect([id, BRAIN_FR[id]]).toEqual([id, expect.any(String)]);
    expect(brainName('security', 'Security and privacy')).toBe('Sécurité et protection des données');
    expect(brainName('new-board', 'New board')).toBe('New board');
  });

  it('never writes « retâche », left by a replacement of « quête »', () => {
    const found = files(join(repo, 'web', 'src')).filter((path) => /\.(tsx?|css|html|md)$/.test(path) && /retâche/i.test(readFileSync(path, 'utf-8')));
    expect(found).toEqual([]);
  });
});

describe('refusals of a result', () => {
  it('says in French, with the action in the page, that a named evidence needs who provided it', () => {
    const english = 'result.json: evidence:gdpr/update-processing-record/processing-record owner must contain text. A passed evidence needs evidence and owner (the person who provided or confirmed the document). Run openguildkit task result data-export --template for the shape.';
    const shown = errorText(new ApiError(english, 200, { lang: 'en' }));
    expect(shown.lang).toBeUndefined();
    expect(shown.text).toBe('evidence:gdpr/update-processing-record/processing-record : indique dans « Fournie par » la personne qui a fourni ou confirmé le document, puis enregistre à nouveau.');
    expect(shown.detail).toBe(english);
    expect(cliText('rule:x/y reason must contain text. A skipped rule needs reason and owner.')).toMatch(/motif et un responsable/);
    expect(errorText(new ApiError('Something else.', 200, { lang: 'en' }))).toEqual({ text: 'Something else.', lang: 'en' });
  });

  it('lists the answers task result held back, in French when it knows them', () => {
    const stderr = 'Not recorded: evidence:gdpr/a/b: records/nope.md does not exist in the project.\nNot recorded: rule:x/y odd. The earlier answer stays recorded.\nOther line';
    expect(notRecorded(stderr)).toEqual([
      { text: 'evidence:gdpr/a/b : records/nope.md n’existe pas dans le projet. Donne un chemin relatif à sa racine, ou un lien https, puis enregistre à nouveau.' },
      { text: 'rule:x/y odd.', lang: 'en' },
    ]);
  });
});
