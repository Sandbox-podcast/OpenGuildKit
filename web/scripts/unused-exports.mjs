// Lists the exports of web/src that nothing uses, and fails when there is one: dead code left by a change.
// An export counts as used when another file imports it (from src/, tests/ or scripts/, statically or with
// `lazyPlace(() => import(X), 'Name')` and `(await import(X)).Name`) or when its own module refers to it, as
// a type that describes the module does. Run: npm run check:exports.
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { parseSync } from 'vite';

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

/** The ESTree program of a file, from the parser Vite ships (oxc): TypeScript 7 has no compiler API to parse with. */
function parse(path) {
  const lang = path.endsWith('.tsx') ? 'tsx' : path.endsWith('.mjs') ? 'js' : 'ts';
  return { fileName: path, program: parseSync(path, readFileSync(path, 'utf8'), { lang }).program };
}

/** Calls `visit(node, parent)` on each node under `node`, parents first. */
function walk(node, visit, parent = null) {
  visit(node, parent);
  for (const value of Object.values(node)) {
    for (const child of Array.isArray(value) ? value : [value]) {
      if (child && typeof child.type === 'string') walk(child, visit, node);
    }
  }
}

/** The text of an identifier or of a string literal (`export { x as 'y' }`, `declare module 'm'`). */
const nameOf = (node) => node.name ?? node.value;

/** The text of a string literal or of a template without substitution, else null. */
function stringOf(node) {
  if (node?.type === 'Literal' && typeof node.value === 'string') return node.value;
  if (node?.type === 'TemplateLiteral' && !node.expressions.length) return node.quasis[0].value.cooked;
  return null;
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

function bindingNames(pattern) {
  switch (pattern?.type) {
    case 'Identifier':
      return [pattern.name];
    case 'ArrayPattern':
      return pattern.elements.flatMap(bindingNames);
    case 'ObjectPattern':
      return pattern.properties.flatMap((p) => bindingNames(p.type === 'RestElement' ? p : p.value));
    case 'AssignmentPattern':
      return bindingNames(pattern.left);
    case 'RestElement':
      return bindingNames(pattern.argument);
    default:
      return [];
  }
}

/** The names a module exports. */
function exportsOf(source) {
  const names = [];
  for (const statement of source.program.body) {
    if (statement.type === 'ExportDefaultDeclaration' || statement.type === 'TSExportAssignment') {
      names.push('default');
    } else if (statement.type === 'ExportNamedDeclaration') {
      const { declaration } = statement;
      names.push(...statement.specifiers.map((s) => nameOf(s.exported)));
      if (declaration?.type === 'VariableDeclaration') names.push(...declaration.declarations.flatMap((d) => bindingNames(d.id)));
      else if (declaration?.id) names.push(nameOf(declaration.id));
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
  const parents = new Map();
  walk(source.program, (node, parent) => {
    parents.set(node, parent);
    if (node.type === 'ImportDeclaration') {
      use(node.source.value, node.specifiers.map((s) => {
        if (s.type === 'ImportDefaultSpecifier') return 'default';
        if (s.type === 'ImportNamespaceSpecifier') return '*';
        return nameOf(s.imported);
      }));
    } else if (node.type === 'ExportNamedDeclaration' && node.source) {
      use(node.source.value, node.specifiers.map((s) => nameOf(s.local)));
    } else if (node.type === 'ExportAllDeclaration') {
      use(node.source.value, ['*']);
    } else if (node.type === 'ImportExpression') {
      const specifier = stringOf(node.source);
      if (specifier !== null) use(specifier, dynamicNames(node, parents, source.program));
    } else if (node.type === 'TSImportType') {
      const specifier = stringOf(node.source ?? node.argument?.literal);
      if (specifier !== null) use(specifier, [node.qualifier?.type === 'Identifier' ? node.qualifier.name : '*']);
    }
  });
  return used;
}

/** The names a dynamic import reads: the strings next to it, the properties read on its result, or all of them. */
function dynamicNames(call, parents, program) {
  let node = parents.get(call);
  const outer = parents.get(node);
  if (node.type === 'ArrowFunctionExpression' && outer?.type === 'CallExpression') {
    const names = outer.arguments.map(stringOf).filter((name) => name !== null);
    if (names.length) return names;
  }
  if (node.type === 'AwaitExpression') node = parents.get(node);
  if (node.type === 'ParenthesizedExpression') node = parents.get(node);
  if (node.type === 'MemberExpression' && !node.computed) return [node.property.name];
  if (node.type === 'VariableDeclarator' && node.id.type === 'Identifier') {
    const variable = node.id.name;
    const names = new Set();
    walk(program, (child) => {
      if (child.type === 'MemberExpression' && !child.computed && child.object.type === 'Identifier' && child.object.name === variable)
        names.add(child.property.name);
    });
    if (names.size) return [...names];
  }
  return ['*'];
}

/** Whether the module refers to a name besides declaring it. */
function usedInFile(source, name) {
  // ESTree gives `{ x }` and `export { x }` two nodes at one place: a place counts once.
  const places = new Set();
  walk(source.program, (node) => {
    if ((node.type === 'Identifier' || node.type === 'JSXIdentifier') && node.name === name) places.add(node.start);
  });
  return places.size > 1;
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
