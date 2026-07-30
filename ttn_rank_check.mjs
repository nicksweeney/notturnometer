/* Ranking regression harness. Reads cases as JSON on stdin, writes verdicts as
 * JSON on stdout. Loads the REAL static/search.js so the test exercises the
 * ranking the browser runs -- not a Python reimplementation of it.
 *
 * Usage: node ttn_rank_check.mjs dist/search-index.json < cases.json
 * Case:  {"q": "dvorak", "expect": "/composer/antonin-dvorak/"}
 *   or:  {"q": "mahler proms", "expect_prefix": "/episode/"}
 */
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const catalogue = process.argv[2] ?? "dist/search-index.json";

// search.js and minisearch.min.js are browser globals scripts; give them a
// window to attach to, then pull the exports back off it. minisearch.min.js
// is a UMD bundle: `require()` gives it a CommonJS `module`/`exports`, so it
// takes the module.exports branch and RETURNS the constructor rather than
// attaching to `window` -- capture that return value explicitly. search.js
// has no such branch (a plain IIFE keyed on `window`), so it attaches to
// globalThis.TTNSearch on its own once `window` exists.
globalThis.window = globalThis;
globalThis.MiniSearch = require(`${process.cwd()}/static/minisearch.min.js`);
require(`${process.cwd()}/static/search.js`);
const { buildIndex, runSearch } = globalThis.TTNSearch;

const docs = JSON.parse(readFileSync(catalogue, "utf-8"));
const index = buildIndex(docs);

const cases = JSON.parse(readFileSync(0, "utf-8"));
const out = cases.map((c) => {
  const hits = runSearch(index, docs, c.q);
  const got = hits.length ? hits[0].u : null;
  const ok = c.expect_prefix
    ? Boolean(got && got.startsWith(c.expect_prefix))
    : got === c.expect;
  return { q: c.q, expect: c.expect ?? c.expect_prefix, got, ok,
           n_hits: hits.length };
});
process.stdout.write(JSON.stringify(out, null, 2));
