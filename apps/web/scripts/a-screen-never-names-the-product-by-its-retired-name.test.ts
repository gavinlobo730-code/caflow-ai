// No text a person reads, in the product or on the public site, names the product by a name it no longer has.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-screen-never-names-the-product-by-its-retired-name.test.ts
//
// WHAT WAS WRONG (found on 19-11-2026 by the owner, from a screenshot of the HSN/SAC step of firm setup). The product is PracticeSync;
// "Caflow" and "CAflow AI" were its working names. Three sentences a person reads still said "Caflow does not ship or suggest HSN/SAC
// classifications": the firm-setup step, the Settings page for the firm's HSN/SAC library and the note on its add-a-code dialog. Every other
// screen already said PracticeSync, so the three read as a different company's product. A screen says what it is; this is the smallest case of that.
//
// WHAT STAYS, ON PURPOSE (CLAUDE.md, "Naming"): the repository, the database project, the `caflow.*` log and storage-key names, seed data, mock
// URLs, code comments and migration history keep the old name. A rename of those breaks import paths, environment keys and migration history.
// So this reads CODE with comments taken out, and flags the name only where it is spelled with a capital (`Caflow`, `CAflow`, `CAFLOW`): the
// lower-case `caflow` of a storage key or a host name is an identifier, not the name a person is shown.
//
// THE RULE, not the three sentences: no source file under the product's or the public site's `app`, `components` or `lib` carries the retired
// name, spelled with a capital, outside a comment.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const MARKETING = path.resolve(WEB, "..", "marketing");
const ROOTS = ["app", "components", "lib"];

/** Where the retired name is spelled the way a person would read it: any capital in `caflow` makes it the name, all lower-case is an identifier. */
export function retiredNames(code: string): string[] {
  return [...code.matchAll(/caflow/gi)].map((m) => m[0]).filter((s) => s !== "caflow");
}

// Comments out: a block comment, a whole-line `//` comment and a JSX brace comment. A trailing `//` after code is kept (it may sit inside a URL string).
function withoutComments(src: string): string {
  return src
    .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, " ")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

function sourceFiles(root: string): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) { if (!["node_modules", ".next", "out"].includes(e.name)) walk(full); continue; }
      if (/\.(ts|tsx)$/.test(e.name) && !/\.test\.(ts|tsx)$/.test(e.name)) out.push(full);
    }
  };
  for (const r of ROOTS) { const d = path.join(root, r); if (fs.existsSync(d)) walk(d); }
  return out;
}

test("the detector tells a name a person reads from an identifier, and a comment from code", () => {
  assert.deepEqual(retiredNames('<p>Caflow does not ship a list</p>'), ["Caflow"]);
  assert.deepEqual(retiredNames('note="Welcome to CAflow AI"'), ["CAflow"]);
  assert.deepEqual(retiredNames("CAFLOW"), ["CAFLOW"]);
  assert.deepEqual(retiredNames('localStorage.getItem("caflow.financialYear")'), [], "a lower-case storage key is not the name");
  assert.deepEqual(retiredNames("const host = 'caflow-ai.pages.dev'"), [], "a host name is not the name");
  assert.deepEqual(retiredNames("__caflow_meta__"), [], "a data marker is not the name");
  assert.equal(retiredNames(withoutComments("// Caflow ships no data\n/* Caflow too */\n{/* Caflow */}\nconst a = 1;")).length, 0, "a comment was read as code");
  assert.equal(retiredNames(withoutComments('const s = "Caflow";')).length, 1, "a string was read as a comment");
});

test("the product's screens and the public site are scanned, so the rule below is not vacuous", () => {
  const web = sourceFiles(WEB).length;
  const marketing = sourceFiles(MARKETING).length;
  assert.ok(web > 300, `only ${web} product source files were scanned`);
  assert.ok(marketing > 30, `only ${marketing} public-site source files were scanned`);
});

test("no screen or public page names the product by its retired name outside a comment", () => {
  const found: string[] = [];
  for (const file of [...sourceFiles(WEB), ...sourceFiles(MARKETING)]) {
    const code = withoutComments(fs.readFileSync(file, "utf8"));
    const hits = retiredNames(code);
    if (hits.length) found.push(`${path.relative(path.resolve(WEB, "..", ".."), file)}: ${[...new Set(hits)].join(", ")}`);
  }
  assert.deepEqual(found, [], `a text a person reads names the product "Caflow" or "CAflow"; it is PracticeSync:\n  ${found.join("\n  ")}`);
});
