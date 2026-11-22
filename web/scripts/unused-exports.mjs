// Lists the exports of web/src that nothing uses, and fails when there is one: dead code left by a change.
// An export counts as used when another file imports it (from src/, tests/ or scripts/, statically or with
// `lazyPlace(() => import(X), 'Name')` and `(await import(X)).Name`) or when its own module refers to it, as
// a type that describes the module does. Run: npm run check:exports.
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import ts from 'typescript';

const SOURCE = /\.(ts|tsx|mjs)$/;
const EXTENSIONS = ['', '.ts', '.tsx', '.mjs', '.js', '/index.ts', '/index.tsx'];

function files(folder) {
  if (!existsSync(folder)) return [];
  return readdirSync(folder).flatMap((name) => {
    const path = join(folder, name);
    if (statSync(path).isDirectory()) return name === 'node_modules' ? [] : files(path);
    return SOURCE.test(name) && !name.endsWith('.d.ts') ? [path] : [];
  });
}

function parse(path) {
  const kind = path.endsWith('.tsx') ? ts.ScriptKind.TSX : path.endsWith('.mjs') ? ts.ScriptKind.JS : ts.ScriptKind.TS;
  return ts.createSourceFile(path, readFileSync(path, 'utf8'), ts.ScriptTarget.Latest, true, kind);
}

/** The file a specifier names inside the project, or null for a package. */
function resolveSpecifier(root, from, specifier) {
  let base;
  if (specifier.startsWith('@/')) base = join(root, 'src', specifier.slice(2));
  else if (specifier.startsWith('.')) base = resolve(dirname(from), specifier);
  else return null;
  const found = EXTENSIONS.map((extension) => base + extension).find((path) => existsSync(path) && statSync(path).isFile());
  return found ?? null;
}

const has = (node, kind) => (ts.canHaveModifiers(node) ? ts.getModifiers(node) ?? [] : []).some((m) => m.kind === kind);

function bindingNames(name) {
  if (ts.isIdentifier(name)) return [name.text];
  return name.elements.flatMap((element) => (ts.isOmittedExpression(element) ? [] : bindingNames(element.name)));
}

/** The names a module exports. */
function exportsOf(source) {
  const names = [];
  for (const statement of source.statements) {
    if (ts.isExportDeclaration(statement) && statement.exportClause && ts.isNamedExports(statement.exportClause)) {
      names.push(...statement.exportClause.elements.map((element) => element.name.text));
    } else if (ts.isExportAssignment(statement)) {
      names.push('default');
    } else if (has(statement, ts.SyntaxKind.ExportKeyword)) {
      if (has(statement, ts.SyntaxKind.DefaultKeyword)) names.push('default');
      else if (ts.isVariableStatement(statement)) names.push(...statement.declarationList.declarations.flatMap((d) => bindingNames(d.name)));
      else if (statement.name) names.push(statement.name.text);
    }
  }
  return names;
}

/** The names one file uses from each module it imports; '*' stands for every name. */
function importsOf(root, source) {
  const used = new Map();
  const use = (specifier, names) => {
    const target = resolveSpecifier(root, source.fileName, specifier);
    if (!target) return;
    const set = used.get(target) ?? new Set();
    for (const name of names) set.add(name);
    used.set(target, set);
  };
  const visit = (node) => {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      const clause = node.importClause;
      const names = [];
      if (clause?.name) names.push('default');
      if (clause?.namedBindings) {
        if (ts.isNamespaceImport(clause.namedBindings)) names.push('*');
        else names.push(...clause.namedBindings.elements.map((e) => (e.propertyName ?? e.name).text));
      }
      use(node.moduleSpecifier.text, names);
    } else if (ts.isExportDeclaration(node) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) {
      const clause = node.exportClause;
      use(node.moduleSpecifier.text, clause && ts.isNamedExports(clause) ? clause.elements.map((e) => (e.propertyName ?? e.name).text) : ['*']);
    } else if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
      const [argument] = node.arguments;
      if (argument && ts.isStringLiteralLike(argument)) use(argument.text, dynamicNames(node));
    } else if (ts.isImportTypeNode(node) && ts.isLiteralTypeNode(node.argument) && ts.isStringLiteral(node.argument.literal)) {
      use(node.argument.literal.text, [node.qualifier ? (ts.isIdentifier(node.qualifier) ? node.qualifier.text : '*') : '*']);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return used;
}

/** The names a dynamic import reads: the strings next to it, the properties read on its result, or all of them. */
function dynamicNames(call) {
  let node = call.parent;
  if (ts.isArrowFunction(node) && ts.isCallExpression(node.parent)) {
    const names = node.parent.arguments.filter(ts.isStringLiteralLike).map((a) => a.text);
    if (names.length) return names;
  }
  if (ts.isAwaitExpression(node)) node = node.parent;
  if (ts.isParenthesizedExpression(node)) node = node.parent;
  if (ts.isPropertyAccessExpression(node)) return [node.name.text];
  if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)) {
    const variable = node.name.text;
    const names = new Set();
    const scope = node.getSourceFile();
    const visit = (child) => {
      if (ts.isPropertyAccessExpression(child) && ts.isIdentifier(child.expression) && child.expression.text === variable) names.add(child.name.text);
      ts.forEachChild(child, visit);
    };
    visit(scope);
    if (names.size) return [...names];
  }
  return ['*'];
}

/** Whether the module refers to a name besides declaring it. */
function usedInFile(source, name) {
  let count = 0;
  const visit = (node) => {
    if (ts.isIdentifier(node) && node.text === name) count += 1;
    ts.forEachChild(node, visit);
  };
  visit(source);
  return count > 1;
}

/** Each export of src/ that nothing uses, as "src/path.ts: name". */
export function unusedExports(root) {
  const sources = files(join(root, 'src'));
  const importers = [...sources, ...files(join(root, 'tests')), ...files(join(root, 'scripts')),
    ...['vite.config.ts', 'playwright.config.ts', 'playwright.project.config.ts'].map((name) => join(root, name)).filter(existsSync)];
  const used = new Map();
  for (const path of importers) {
    for (const [target, names] of importsOf(root, parse(path))) {
      if (target === path) continue;
      const set = used.get(target) ?? new Set();
      for (const name of names) set.add(name);
      used.set(target, set);
    }
  }
  const unused = [];
  for (const path of sources) {
    const names = used.get(path) ?? new Set();
    if (names.has('*')) continue;
    const source = parse(path);
    for (const name of exportsOf(source)) {
      if (!names.has(name) && !usedInFile(source, name)) unused.push(`${relative(root, path).split('\\').join('/')}: ${name}`);
    }
  }
  return unused.sort();
}

function main() {
  const root = join(dirname(fileURLToPath(import.meta.url)), '..');
  const unused = unusedExports(root);
  for (const line of unused) console.error(line);
  if (unused.length) {
    console.error(`${unused.length} export(s) of web/src that nothing uses: remove them.`);
    process.exit(1);
  }
  console.log('Every export of web/src is used.');
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
