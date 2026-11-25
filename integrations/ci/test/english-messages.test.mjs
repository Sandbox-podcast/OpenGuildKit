import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const packageRoot = fileURLToPath(new URL('..', import.meta.url));
const read = path => readFileSync(join(packageRoot, path), 'utf8');
// The French messages without an accent that the coordinator used to print.
const frenchWords = /\b(?:pour|dans|avec|sans|une|des|les|est|sont|doit|aux|invalides?|requis|absente?|erreur|fichier|depot|regle|identifiant|tentative|reprise|coordinateur|rapport)\b/i;
const filesOf = folder => readdirSync(join(packageRoot, folder), { recursive: true })
  .map(name => join(folder, name)).filter(path => statSync(join(packageRoot, path)).isFile());

test('the scripts and templates of pilot and prototype are in English', () => {
  for (const path of ['pilot', 'prototype'].flatMap(filesOf)) {
    const source = read(path);
    assert.doesNotMatch(source, /[^\x00-\x7f]/, path);
    assert.doesNotMatch(source, frenchWords, path);
  }
});
