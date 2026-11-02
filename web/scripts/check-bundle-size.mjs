// Performance budget: the JS needed for the first screen (entry + its static imports), gzipped.
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

const BUDGET_KB = Number(process.env.BUNDLE_BUDGET_KB ?? 330);
const dist = path.resolve(import.meta.dirname, '../dist');
const manifest = JSON.parse(fs.readFileSync(path.join(dist, '.vite/manifest.json'), 'utf8'));
const seen = new Set();
const visit = (key) => {
  if (seen.has(key)) return;
  seen.add(key);
  for (const k of manifest[key]?.imports ?? []) visit(k);
};
visit('index.html');
let total = 0;
for (const k of seen) {
  const f = manifest[k]?.file;
  if (!f || !f.endsWith('.js')) continue;
  total += zlib.gzipSync(fs.readFileSync(path.join(dist, f))).length;
}
const kb = Math.round(total / 1024);
console.log(`initial JS: ${kb} KB gzip (budget ${BUDGET_KB} KB)`);
if (kb > BUDGET_KB) process.exit(1);
