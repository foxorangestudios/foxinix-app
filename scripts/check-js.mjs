// Valida sintaxis ES2020 (== nivel de Firefox 78 / Mypal 78) de los .js del frontend
// y el LINK de módulos: todo `import { x } from './local.js'` debe existir como export
// (un nombre faltante rompe la app entera con SyntaxError en el navegador, y acorn
// por sí solo no lo detecta).
// Uso: node scripts/check-js.mjs [acornPath]
// Acorn: https://cdn.jsdelivr.net/npm/acorn@8.14.0/dist/acorn.js (UMD, funciona con require)
import { createRequire } from 'node:module';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const acornPath = process.argv[2] || '/tmp/opencode/acorn.js';
const acorn = require(acornPath);

const root = join(here, '..', 'server', 'web');
const files = [];
(function walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p);
    else if (p.endsWith('.js') && !p.includes('vendor')) files.push(p);
  }
})(root);

let fail = 0;

/* ---------- 1) parseo + recolección de exports/imports ---------- */
const mods = new Map(); // path abs → { ast, exports:Set, imports:[{source, names, line}] }

function declNames(decl, out) {
  if (!decl) return;
  if (decl.type === 'VariableDeclaration') {
    for (const d of decl.declarations) {
      if (d.id.type === 'Identifier') out.add(d.id.name);
      else if (d.id.type === 'ObjectPattern') {
        for (const p of d.id.properties) {
          if (p.type === 'Property' && p.value.type === 'Identifier') out.add(p.value.name);
        }
      }
      // ArrayPattern/AssignmentPattern: raro en exports; se ignora
    }
  } else if (decl.id && decl.id.type === 'Identifier') {
    out.add(decl.id.name);
  }
}

for (const f of files) {
  const src = readFileSync(f, 'utf8');
  let ast;
  try {
    ast = acorn.parse(src, { ecmaVersion: 2020, sourceType: 'module' });
    console.log('OK   ' + f.replace(root, 'web'));
  } catch (e) {
    fail++;
    console.log('FAIL ' + f.replace(root, 'web') + ' → ' + e.message);
    continue;
  }
  const exports = new Set();
  const imports = [];
  for (const n of ast.body) {
    if (n.type === 'ExportNamedDeclaration') {
      declNames(n.declaration, exports);
      for (const s of n.specifiers) {
        exports.add(s.exported.type === 'Identifier' ? s.exported.name : String(s.exported.value));
      }
    } else if (n.type === 'ExportDefaultDeclaration') {
      exports.add('default');
    } else if (n.type === 'ImportDeclaration' && n.source.value.endsWith('.js')) {
      const names = [];
      for (const s of n.specifiers) {
        if (s.type === 'ImportSpecifier') {
          names.push(s.imported.type === 'Identifier' ? s.imported.name : String(s.imported.value));
        }
      }
      imports.push({ source: n.source.value, names, line: n.loc ? n.loc.start.line : 0 });
    }
  }
  mods.set(f, { exports, imports });
}

/* ---------- 2) verificación de links ---------- */
for (const [f, m] of mods) {
  const dir = dirname(f);
  for (const imp of m.imports) {
    const target = resolve(dir, imp.source);
    const tm = mods.get(target);
    if (!tm) {
      fail++;
      console.log('FAIL ' + f.replace(root, 'web') + ' → no existe el módulo ' + imp.source);
      continue;
    }
    for (const name of imp.names) {
      if (!tm.exports.has(name)) {
        fail++;
        console.log('FAIL ' + f.replace(root, 'web') + ' → ' + imp.source +
          ' no exporta "' + name + '"');
      }
    }
  }
}

/* Vue vendor: script clásico (no module) */
try {
  acorn.parse(readFileSync(join(root, 'vendor', 'vue.global.prod.js'), 'utf8'), { ecmaVersion: 2020 });
  console.log('OK   web/vendor/vue.global.prod.js');
} catch (e) {
  fail++;
  console.log('FAIL web/vendor/vue.global.prod.js → ' + e.message);
}

/* ---------- 3) CSS: compatibilidad Mypal (Gecko 78) ----------
   Lista negra de propiedades/pseudoclases que llegaron DESPUÉS de FF78
   (W5). El caso histórico: `gap` en flexbox recién llegó en FF84, así
   que en XP los huecos colapsaban — hoy todo va por márgenes. */
const CSS_BAD = [
  [/\bgap\s*:/, 'gap en flex (FF84+; en XP colapsa — usar márgenes, ver bloque W5)'],
  [/backdrop-filter/, 'backdrop-filter (FF103+)'],
  [/:has\(/, ':has() (FF121+)'],
  [/:focus-visible/, ':focus-visible (FF85+)'],
  [/aspect-ratio/, 'aspect-ratio (FF89+)'],
  [/\b(dvh|svh|lvh)\b/, 'unidades dvh/svh/lvh (FF101+)'],
  [/overflow\s*:\s*clip/, 'overflow: clip (FF81+)'],
  [/scrollbar-gutter/, 'scrollbar-gutter (FF97+)'],
  [/accent-color/, 'accent-color (FF92+)'],
  [/image-set\(/, 'image-set() (FF88+)'],
];
const cssFiles = [];
(function walkCss(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walkCss(p);
    else if (p.endsWith('.css') && !p.includes('vendor')) cssFiles.push(p);
  }
})(root);

for (const f of cssFiles) {
  const src = readFileSync(f, 'utf8');
  let bad = 0;
  for (const [re, why] of CSS_BAD) {
    // ignora coincidencias dentro de comentarios de bloque
    const commentless = src.replace(/\/\*[\s\S]*?\*\//g, '');
    const m = commentless.match(re);
    if (m) {
      bad++;
      fail++;
      console.log('FAIL ' + f.replace(root, 'web') + ' → ' + why);
    }
  }
  if (!bad) console.log('OK   ' + f.replace(root, 'web') + ' (css FF78)');
}

/* JS: APIs posteriores a FF78 que acorn no puede detectar (no son syntax) */
const JS_API_BAD = [
  [/Promise\.any\s*\(/, 'Promise.any (FF79+; Mypal es 78)'],
  [/structuredClone\s*\(/, 'structuredClone (FF94+)'],
  [/Object\.hasOwn\s*\(/, 'Object.hasOwn (FF92+)'],
  [/\.findLast\s*\(/, 'Array.findLast (FF104+)'],
  [/\.(toSorted|toReversed|toSpliced)\s*\(/, 'métodos toSorted/toReversed (FF111+)'],
  [/WeakRef|AggregateError/, 'WeakRef/AggregateError (FF79+/89+)'],
];
for (const f of files) {
  const src = readFileSync(f, 'utf8').replace(/\/\/[^\n]*/g, '');
  for (const [re, why] of JS_API_BAD) {
    if (re.test(src)) {
      fail++;
      console.log('FAIL ' + f.replace(root, 'web') + ' → ' + why);
    }
  }
}

console.log(fail ? `\n${fail} error(es)` : '\nlink OK (' + mods.size + ' módulos)');
process.exit(fail ? 1 : 0);
