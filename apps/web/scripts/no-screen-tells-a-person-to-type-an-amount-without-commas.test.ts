// POST-A-567 — what a screen says about commas in an amount must be what the amount reader does.
//
// WHY THIS EXISTS
//     On 27-11-2026 the owner decided that an amount typed with its commas where amounts are written (1,25,000 the Indian way, 1,250,000 the Western
//     way) is READ, and only a comma in a place nobody writes one (1,2,5 and 12,50) is refused (lib/money/rupeeInput.ts). About fifty refusal
//     sentences had said "without commas" for as long as the reader refused every comma, and each of them became false the day the reader changed:
//     a person who typed 1,25,000, was refused for a different mistake and read "without commas" was told to remove commas that were right.
//
//     The rule is the sentence's, not a spelling of it: no screen's words tell a person to leave the commas out of an AMOUNT. The two places that
//     still say so are about something else and are listed here with what they are about; an entry here that no longer matches is a failure, so
//     the list cannot keep permitting a sentence the screen no longer says.
//
// Run with:
//   node --experimental-strip-types --test scripts/no-screen-tells-a-person-to-type-an-amount-without-commas.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");

/** Sentences that still say "no commas" and are TRUE, each with what it is about. */
const STILL_TRUE: Array<{ file: string; phrase: string; about: string }> = [
  { file: "app/clients/[id]/payroll/page.tsx", phrase: "must be plain percentages, e.g. 50 or 40.5 — without commas.",
    about: "a percentage, which never takes grouping (bpsFromPercentInput refuses any comma: 1,000 there would be a thousand per cent)" },
  { file: "components/currency/FxRatesPanel.tsx", phrase: "The rate must be a plain decimal, e.g. 83.4200 — no commas.",
    about: "an exchange rate, read by its own plain-decimal check and not by the amount reader" },
];

function sourceFiles(dir: string, found: string[] = []): string[] {
  for (const entry of fs.readdirSync(path.join(ROOT, dir), { withFileTypes: true })) {
    const rel = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules" || entry.name === ".next" || entry.name === "out") continue;
      sourceFiles(rel, found);
    } else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.(ts|tsx)$/.test(entry.name)) {
      found.push(rel);
    }
  }
  return found;
}

/** The text of a file with its comments taken out: a comment may explain the old sentence, and only what a person is shown is the rule's concern. */
function codeOf(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("no sentence a person is shown tells them to leave the commas out of an amount", () => {
  // A file with a sentence that is still true is scanned too, with only THAT sentence taken out: a second "no commas" in the same file (the
  // payroll page has many amount boxes) must not hide behind the first.
  const permitted = new Map(STILL_TRUE.map((e) => [e.file, e.phrase]));
  const offenders: string[] = [];
  for (const dir of ["app", "components", "lib"]) {
    for (const rel of sourceFiles(dir)) {
      const posix = rel.split(path.sep).join("/");
      let code = codeOf(rel);
      const phrase = permitted.get(posix);
      if (phrase) code = code.replace(/"\s*\+\s*"/g, "").split(phrase).join("");
      const m = /(?:without|with no|no)\s+commas/i.exec(code);
      if (m) offenders.push(`${posix}: …${code.slice(Math.max(0, m.index - 60), m.index + m[0].length + 20).replace(/\s+/g, " ")}`);
    }
  }
  assert.deepEqual(offenders, [], "a refusal still says to type an amount without commas, which the amount reader no longer asks");
});

test("each sentence that still says no commas is on the list with what it is about, and is still there", () => {
  for (const entry of STILL_TRUE) {
    const code = codeOf(entry.file).replace(/"\s*\+\s*"/g, "");
    assert.ok(code.includes(entry.phrase), `${entry.file} no longer says "${entry.phrase}", so its entry (${entry.about}) permits nothing: remove it`);
  }
});

test("the amount reader reads a grouped amount and refuses a misplaced comma, which is what the screens now say", async () => {
  const { paiseFromRupeeInput, AMOUNT_MAY_LOOK_LIKE } = await import("../lib/money/rupeeInput.ts");
  assert.equal(paiseFromRupeeInput("1,25,000"), 12_500_000);
  assert.equal(paiseFromRupeeInput("1,2,5"), null);
  assert.match(AMOUNT_MAY_LOOK_LIKE, /1,25,000/);
  assert.doesNotMatch(AMOUNT_MAY_LOOK_LIKE, /without commas|no commas/i);
});
