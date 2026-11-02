// Pages talk to the API only through the typed clients in src/api: no direct fetch(), no hand-written /api URLs.
// (Paths passed to the clients are checked by TypeScript against the generated types.)
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '../src');
const bad = [];
const walk = (dir) => {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (['api', 'test'].includes(path.relative(root, p))) continue;
      walk(p);
    } else if (/\.(ts|tsx)$/.test(e.name) && !/\.test\.tsx?$/.test(e.name)) {
      const lines = fs.readFileSync(p, 'utf8').split('\n');
      lines.forEach((l, i) => {
        if (/(^|[^.\w])fetch\(/.test(l)) bad.push(`${path.relative(root, p)}:${i + 1}: direct fetch()`);
        if (/['"`]\/api\//.test(l) && !/api\.\w+\.(GET|POST|PUT|PATCH|DELETE)\(/.test(l))
          bad.push(`${path.relative(root, p)}:${i + 1}: API path outside a typed client call`);
      });
    }
  }
};
walk(root);
if (bad.length) {
  console.error(bad.join('\n'));
  process.exit(1);
}
console.log('api usage ok');
