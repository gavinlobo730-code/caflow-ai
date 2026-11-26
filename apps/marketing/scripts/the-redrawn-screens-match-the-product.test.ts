// The four product screens drawn on the home page are copied from the product,
// and this is what says they still are (POST-A-121).
//
// WHAT WAS WRONG. components/home/screens/ holds hand-built recreations of four
// product screens, made on 16-09-2026 on the argument that a recreation "cannot
// silently go stale" because it is code in the same repository. Nothing tied
// them to the product, so they did: on 25-09-2026 the product replaced the
// client sidebar with a module grid and a 48px top bar (D23 to D25), and the
// home page went on drawing the old sidebar, with its seventeen names, for seven
// weeks. The bank queue lost a tab, the copilot answered with client names and
// GSTINs it is never given, and GSTR-3B Table 6 changed shape, all unseen.
//
// THE RULE. The product's wording the drawings carry lives in one module,
// components/home/screens/productWords.ts, grouped by the product file it was
// copied from, and this test reads those files:
//
//   - the client workspace's modules equal the product's CLIENT_SECTIONS, id
//     and label, in the product's order (the module grid renders exactly that
//     list, so a module added, renamed, moved or removed there fails here);
//   - every other copied label and sentence still appears in its file, compared
//     with runs of whitespace folded, because the product wraps long JSX text
//     across lines;
//   - the copilot's disclosure equals the product's sentence, imported rather
//     than read, so a changed letter fails;
//   - each drawing takes those words from the module and does not keep a
//     second copy of the module names.
//
// WHAT IT DOES NOT CHECK. Layout, spacing, colour and the invented sample data
// (clients, figures, dates). A drawing can still look unlike the product while
// every word on it is the product's; the caption under the showcase says the
// screens are redrawn by hand and that a label may differ, and a rule on the
// Python side keeps that caption (test_the_marketing_site_does_not_claim_what_
// the_code_does_not_do.py).
//
// WHERE IT RUNS. `pnpm test` in apps/marketing, which Marketing CI runs on a
// change to apps/marketing or to any product file named in FROM: the last
// test below holds the workflow's path list to FROM, so a source added there
// and not to the workflow fails here.
//
// Run with: node --experimental-strip-types --test scripts/the-redrawn-screens-match-the-product.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  CLIENT_MODULES,
  COPIED,
  COPILOT_DISCLOSURE,
  FROM,
  fill,
  type ClientModule,
  type Source,
} from "../components/home/screens/productWords.ts";
import { AI_DISCLOSURES } from "../../web/lib/ai/disclosure.ts";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MARKETING = path.resolve(HERE, "..");
const REPO = path.resolve(MARKETING, "..", "..");
const SCREENS = path.join(MARKETING, "components", "home", "screens");
const WORKFLOW = path.join(REPO, ".github", "workflows", "marketing-ci.yml");

/** A product file's code, comments removed (`codeOf`). */
function read(source: Source): string {
  const file = path.join(REPO, FROM[source]);
  assert.ok(
    fs.existsSync(file),
    `${FROM[source]} (FROM.${source}) is gone. The drawing was copied from it: find where the product moved it, ` +
      "re-copy the words from there and point FROM at the new file.",
  );
  return codeOf(fs.readFileSync(file, "utf8"), file);
}

const fold = (s: string) => s.replace(/\s+/g, " ").trim();

/**
 * A source file with its comments removed, so a word is found only where the
 * product SAYS it. A file's header often describes its own labels ("Worth a
 * Look was added as a fourth tab"), and a word found there would keep this check
 * green after the label itself was renamed.
 *
 * Deliberately naive, the way tests/_marketing_copy.py's comment blanking is: it
 * does not track string literals, because JSX text carries apostrophes that a
 * string-aware scanner would read as quotes. Where it errs (a `//` inside a
 * string, a ` #` inside a Python string) it removes too much, which can only
 * report a word as missing, never find one that is not there.
 */
export function codeOf(src: string, file: string): string {
  if (file.endsWith(".py")) {
    return src
      .replace(/("""|''')[\s\S]*?\1/g, " ")
      .replace(/^\s*#.*$/gm, " ")
      .replace(/\s#\s.*$/gm, " ");
  }
  return src.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/(?<![:\\])\/\/.*$/gm, " ");
}

/** `CLIENT_SECTIONS` as the product declares it: each entry's id and label, in order. */
export function clientSectionsIn(src: string): ClientModule[] {
  const start = src.indexOf("export const CLIENT_SECTIONS");
  assert.ok(start >= 0, "the product no longer exports CLIENT_SECTIONS from this file");
  const end = src.indexOf("];", start);
  const body = src.slice(start, end).replace(/\/\/.*$/gm, "");
  const entries = [...body.matchAll(/\{\s*id:\s*"([^"]+)",\s*label:\s*"([^"]+)"/g)].map((m) => ({
    id: m[1],
    label: m[2],
  }));
  // Every entry must have been read. An entry written another way (label before
  // id, single quotes) would otherwise drop out of the list silently and the
  // comparison below would fail for the wrong reason, or pass for one.
  const declared = (body.match(/\bid:\s*["']/g) ?? []).length;
  assert.equal(entries.length, declared, `read ${entries.length} of the ${declared} sections CLIENT_SECTIONS declares`);
  return entries;
}

/** The copied words a source file no longer contains. */
export function missingFrom(src: string, group: Readonly<Record<string, string | readonly string[]>>): string[] {
  const text = fold(src);
  const missing: string[] = [];
  for (const [key, value] of Object.entries(group)) {
    for (const word of typeof value === "string" ? [value] : value) {
      if (!text.includes(fold(word))) missing.push(`${key}: ${JSON.stringify(word)}`);
    }
  }
  return missing;
}

const SECTIONS = clientSectionsIn(read("clientSections"));

test("the product's client sections are read, all of them", () => {
  assert.ok(SECTIONS.length >= 15, `only ${SECTIONS.length} client sections read — the parser has stopped matching`);
  assert.ok(SECTIONS.some((s) => s.id === "bank") && SECTIONS.some((s) => s.id === "overview"));
});

test("the client workspace draws the product's modules, in the product's order", () => {
  assert.deepEqual(
    CLIENT_MODULES.map((m) => ({ id: m.id, label: m.label })),
    SECTIONS,
    "CLIENT_MODULES in components/home/screens/productWords.ts no longer matches CLIENT_SECTIONS in " +
      `${FROM.clientSections}. Copy the product's list (id and label, in its order) into CLIENT_MODULES.`,
  );
});

test("the module grid renders CLIENT_MODULES and keeps no list of its own", () => {
  const src = fs.readFileSync(path.join(SCREENS, "ClientOverview.tsx"), "utf8");
  assert.match(src, /import \{[^}]*\bCLIENT_MODULES\b[^}]*\} from "\.\/productWords"/);
  assert.match(src, /CLIENT_MODULES\.map\(/);
  const copies = CLIENT_MODULES.filter((m) => src.includes(`"${m.label}"`)).map((m) => m.label);
  assert.deepEqual(copies, [], `ClientOverview.tsx spells module names itself: ${copies.join(", ")}`);
});

test("every copied word is still in the product file it was copied from", () => {
  assert.ok(COPIED.length >= 8, "the groups of copied words have gone missing — this would check nothing");
  const stale: string[] = [];
  for (const [source, group] of COPIED) {
    for (const miss of missingFrom(read(source), group)) stale.push(`${FROM[source]}  ${miss}`);
  }
  assert.deepEqual(
    stale,
    [],
    "these words are no longer in the product file they were copied from. Re-copy them from the product " +
      "(and redraw the screen if the product's screen changed):\n  " +
      stale.join("\n  "),
  );
});

test("the copilot's disclosure is the product's sentence, letter for letter", () => {
  assert.equal(COPILOT_DISCLOSURE.sentence, AI_DISCLOSURES.copilot.sentence);
});

test("every drawing takes the product's words from productWords.ts", () => {
  for (const name of ["ClientBar", "ClientOverview", "BankQueue", "Gstr3bReview", "CopilotChat"]) {
    const src = fs.readFileSync(path.join(SCREENS, `${name}.tsx`), "utf8");
    assert.match(src, /from "\.\/productWords"/, `${name}.tsx does not import productWords`);
  }
});

test("a template keeps the product's placeholder and fill puts the sample value in", () => {
  assert.equal(fill("Coded this way {times} of the last {total} times", 7, 9), "Coded this way 7 of the last 9 times");
  assert.equal(fill("${n} ready", 128), "128 ready");
  assert.equal(fill("Rule “{hit.rule_name}”", "Jio broadband"), "Rule “Jio broadband”");
});

// ── the checks can fail ──────────────────────────────────────────────────────

test("a renamed, moved or missing section fails the comparison", () => {
  const real = read("clientSections");
  const renamed = real.replace('label: "Bank"', 'label: "Banking"');
  assert.notEqual(renamed, real, "premise: the product names a section Bank");
  assert.notDeepEqual(clientSectionsIn(renamed), CLIENT_MODULES.map((m) => ({ ...m })));
  const dropped = real.replace(/^\s*\{ id: "health".*$/m, "");
  assert.notDeepEqual(clientSectionsIn(dropped), CLIENT_MODULES.map((m) => ({ ...m })));
  assert.throws(() => clientSectionsIn(real.replace('{ id: "tax",', "{ label: \"Tax\", id: 'tax',")), /read \d+ of the/);
});

test("a word the product reworded is reported, and wrapping is not", () => {
  const src = 'title="GSTR-3B Review"\n  <p>Verify all figures\n      before downloading</p>';
  assert.deepEqual(missingFrom(src, { a: "GSTR-3B Review", b: "Verify all figures before downloading" }), []);
  assert.deepEqual(missingFrom(src, { a: "GSTR-3B Summary" }), ['a: "GSTR-3B Summary"']);
});

test("a word that survives only in a comment is reported as missing", () => {
  // The bank page's header describes its tabs in prose. Renaming the tab and
  // leaving the prose must still fail, which it did not before comments were
  // removed (found by the negative control this test now pins).
  const tsx = '/**\n * Worth a Look  risk-based review\n */\nconst TABS = [{ label: "Worth A Look" }]; // Worth a Look\n{/* Worth a Look */}';
  assert.deepEqual(missingFrom(codeOf(tsx, "page.tsx"), { tab: "Worth a Look" }), ['tab: "Worth a Look"']);
  assert.match(codeOf('const u = "https://x.dev/a";', "a.ts"), /https:\/\/x\.dev\/a/, "a URL is not a comment");
  const py = 'def f():\n    """Coded this way all {total} times before"""\n    # Coded this way all {total} times before\n    return "other"  # Coded this way all {total} times before\n';
  assert.deepEqual(missingFrom(codeOf(py, "history.py"), { every: "Coded this way all {total} times before" }), [
    'every: "Coded this way all {total} times before"',
  ]);
  assert.deepEqual(missingFrom(codeOf('    return f"Coded this way all {total} times before"\n', "h.py"), {
    every: "Coded this way all {total} times before",
  }), []);
});

// ── it runs when a copied file changes ───────────────────────────────────────

/** The `paths:` list under one trigger of a workflow, read without a YAML parser. */
export function triggerPaths(yaml: string, trigger: "push" | "pull_request"): string[] {
  const block = yaml.match(new RegExp(`^  ${trigger}:\\n([\\s\\S]*?)(?=^  \\S|^\\S)`, "m"));
  assert.ok(block, `the workflow has no ${trigger} trigger`);
  const paths = block[1].match(/^\s+paths:\n((?:\s+- .*\n)+)/m);
  assert.ok(paths, `the ${trigger} trigger has no paths list`);
  return [...paths[1].matchAll(/- "([^"]+)"/g)].map((m) => m[1]);
}

/** A GitHub path filter as a regular expression: `**` crosses folders, `*` does not. */
export function globMatches(pattern: string, file: string): boolean {
  const rx = pattern
    .split(/(\*\*|\*)/)
    .map((part) => (part === "**" ? ".*" : part === "*" ? "[^/]*" : part.replace(/[.+?^${}()|[\]\\]/g, "\\$&")))
    .join("");
  return new RegExp(`^${rx}$`).test(file);
}

test("Marketing CI runs these tests when any file they read changes", () => {
  const yaml = fs.readFileSync(WORKFLOW, "utf8");
  assert.match(yaml, /run: pnpm test\b/, "Marketing CI does not run this app's tests");
  for (const trigger of ["push", "pull_request"] as const) {
    const patterns = triggerPaths(yaml, trigger);
    assert.ok(patterns.some((p) => globMatches(p, "apps/marketing/scripts/x.test.ts")));
    const unwatched = Object.values(FROM).filter((file) => !patterns.some((p) => globMatches(p, file)));
    assert.deepEqual(unwatched, [], `Marketing CI's ${trigger} paths do not include: ${unwatched.join(", ")}`);
  }
  assert.ok(globMatches("apps/web/app/clients/*/bank/page.tsx", "apps/web/app/clients/[id]/bank/page.tsx"));
  assert.ok(!globMatches("apps/web/lib/*.ts", "apps/web/lib/ai/disclosure.ts"));
});
