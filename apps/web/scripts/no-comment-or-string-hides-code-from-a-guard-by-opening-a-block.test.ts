// No line comment and no string in the web app contains the two characters that open a block comment (POST-A-364).
//
// WHAT WAS WRONG
//   About 170 guards in this folder read source after removing comments with `.replace(/\/\*[\s\S]*?\*\//g, "")` followed by a
//   per-line `//` strip. That regex cannot tell a block comment from the two characters "/*" inside a LINE comment or a string:
//   a comment reading "not the /api/health/* routes" opened a "block" that ended at the next real close, 200 lines later, and
//   every code line in between vanished from every guard that reads the file. It cost one guard its truth on 31-10-2026 (it
//   said HealthDetailClient no longer read a table it read), and it hid pieces of the API client, the portal dashboard and the
//   GST data layer from the rest. Nothing failed: a guard that cannot see the code it is asked about passes.
//
// WHAT THIS HOLDS
//   Rewriting 170 guards onto the quote-aware stripper is a larger change than rewording six comments, and a new comment can
//   bring the hazard back. So the hazard itself is the rule: outside block comments, no `//` comment and no quoted string may
//   contain "/*" ... except the names in KNOWN, each with the reason it cannot be reworded. A path with a wildcard is written
//   as words ("the /api/health routes") or with the star spelt out.
//
// Run with: node --experimental-strip-types --test scripts/no-comment-or-string-hides-code-from-a-guard-by-opening-a-block.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const ROOTS = ["app", "components", "lib"];
const OPEN = "/" + "*";   // spelt in two pieces so this file never contains the hazard itself

/** file -> why a string there must keep the characters. Shrink-only. */
const KNOWN: Record<string, string> = {
  "app/settings/branding/page.tsx": 'the file input\'s accept attribute is the MIME wildcard for images; the logo handler checks the type itself',
};

interface Hit { file: string; line: number; kind: "line comment" | "string"; text: string }

function walk(dir: string, out: string[]): void {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name === ".next" || e.name === "out") continue;
    const full = path.join(dir, e.name);
    if (e.isDirectory()) walk(full, out);
    else if (/\.(ts|tsx)$/.test(e.name) && !/\.test\.tsx?$/.test(e.name)) out.push(full);
  }
}

/** Hits in one file. Block comments are skipped by a small state machine (a JSDoc line may say anything), then each remaining
 *  line is read left to right with its quote state: a "//" outside a string starts a line comment, and the opener after it, or
 *  inside a string, is a hit. A "//" inside a string (a URL) is not a comment. */
export function hitsIn(file: string, src: string): Hit[] {
  const hits: Hit[] = [];
  let inBlock = false;
  src.split("\n").forEach((line, i) => {
    let quote: string | null = null;
    let k = 0;
    while (k < line.length) {
      const c = line[k];
      const n = line[k + 1];
      if (inBlock) { if (c === "*" && n === "/") { inBlock = false; k += 2; } else k++; continue; }
      if (quote) {
        if (c === "\\") { k += 2; continue; }
        if (c === quote) quote = null;
        else if (c === "/" && n === "*") hits.push({ file, line: i + 1, kind: "string", text: line.trim().slice(0, 120) });
        k++;
        continue;
      }
      if (c === '"' || c === "'" || c === "`") { quote = c; k++; continue; }
      if (c === "/" && n === "/") {
        if (line.indexOf(OPEN, k + 2) >= 0) hits.push({ file, line: i + 1, kind: "line comment", text: line.trim().slice(0, 120) });
        break;
      }
      if (c === "/" && n === "*") { inBlock = true; k += 2; continue; }
      k++;
    }
  });
  return hits;
}

test("no web source file has a line comment or a string that contains a block-comment opener, except the known one", () => {
  const files: string[] = [];
  for (const r of ROOTS) walk(path.join(WEB, r), files);
  assert.ok(files.length > 300, `only ${files.length} source files were scanned`);
  const hits = files.flatMap((f) => hitsIn(path.relative(WEB, f).split(path.sep).join("/"), fs.readFileSync(f, "utf8")));
  const unknown = hits.filter((h) => !(h.file in KNOWN));
  assert.deepEqual(
    unknown.map((h) => `${h.file}:${h.line} (${h.kind}) ${h.text}`),
    [],
    "A line comment or a string holding the two characters that open a block comment makes every guard that strips comments with a " +
    "regex delete the code up to the next close. Say the path in words, or spell the star out.",
  );
  for (const k of Object.keys(KNOWN)) assert.ok(hits.some((h) => h.file === k), `${k} no longer holds the hazard: delete it from KNOWN`);
});

// ── The scanner itself, so it cannot go blind ──────────────────────────────────────────────────────────────────

test("it finds an opener in a line comment and in a string, and not in a block comment, a URL or a clean line", () => {
  const star = "*";
  assert.equal(hitsIn("a.ts", `// not the /api/health/${star} routes\nconst x = 1;`).length, 1);
  assert.equal(hitsIn("a.ts", `const a = "image/${star}";`).length, 1);
  assert.equal(hitsIn("a.ts", `/** the /api/health/${star} routes */\nconst x = 1;`).length, 0, "a real block comment may say anything");
  assert.equal(hitsIn("a.ts", `const u = "http://localhost:8000"; // fine`).length, 0, "a URL's slashes are not a comment");
  assert.equal(hitsIn("a.ts", `const x = 1; // nothing to see`).length, 0);
  assert.equal(hitsIn("a.ts", `{/* a JSX comment */}`).length, 0);
});

test("the hazard is real: the regex stripper deletes the code after a line comment holding the opener", () => {
  const naive = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "").split("\n").map((l) => l.replace(/\/\/.*$/, "")).join("\n");
  const src = `// not the /api/health/${"*"} routes\nconst keep = readThis();\n/* a real comment */\nconst after = 1;`;
  assert.ok(!naive(src).includes("readThis"), "the regex stripper was expected to lose the line between the two");
  assert.ok(hitsIn("a.ts", src).length === 1, "and the rule must catch exactly that source");
});

test("a temporary tree with the hazard is reported (negative control)", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "blockopen-"));
  try {
    fs.mkdirSync(path.join(dir, "app"));
    fs.writeFileSync(path.join(dir, "app", "x.tsx"), `// see /x/${"*"}\nexport const a = 1;\n`);
    const text = fs.readFileSync(path.join(dir, "app", "x.tsx"), "utf8");
    assert.equal(hitsIn("app/x.tsx", text).length, 1);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
