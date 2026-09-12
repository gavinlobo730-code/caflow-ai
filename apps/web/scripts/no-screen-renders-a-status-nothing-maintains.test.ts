// A column that is written once and never updated must not be rendered as a
// status. Run with:
//   node --experimental-strip-types --test scripts/no-screen-renders-a-status-nothing-maintains.test.ts
//
// WHY THIS EXISTS (BANK-25)
//     `bank_statements.import_status` is written exactly once — the literal
//     'pending', by services/banking_service.py at import — and by nothing
//     else, ever. AccountsPanel rendered it as a coloured chip with a
//     three-value palette (pending / reviewed / posted), of which only one
//     value could ever occur. So every statement in the product read "pending"
//     forever, including ones whose every line had been passed to the ledger
//     months earlier.
//
//     That is worse than showing nothing: it tells a CA there is work
//     outstanding on a statement that is finished, and it does so with the
//     confidence of a status badge.
//
// THE RULE THIS PINS, not the one spelling of it: no screen may render
// `import_status`. If the column is ever genuinely maintained — a SQL function
// or a value the pass/undo paths write — delete this test in the same commit
// that makes it true, and say so. Do not weaken it to allow one screen.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");

/** Every .ts/.tsx under app/ and components/, which is everything that renders. */
function sources(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) { if (e.name !== "node_modules") walk(p); }
      else if (/\.(ts|tsx)$/.test(e.name) && !/\.test\.tsx?$/.test(e.name)) out.push(p);
    }
  };
  for (const d of ["app", "components"]) walk(path.join(ROOT, d));
  return out;
}

/** Comments stripped: the note explaining why the chip was removed names the
 *  column, and a guard that its own explanation fails is a guard nobody keeps. */
function code(file: string): string {
  return fs.readFileSync(file, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
}

test("no screen reads bank_statements.import_status", () => {
  const offenders = sources().filter((f) => /\bimport_status\b/.test(code(f)));
  assert.deepEqual(
    offenders.map((f) => path.relative(ROOT, f)), [],
    "import_status is written once at import and never updated — rendering it " +
    "shows every statement as 'pending' forever. Show a figure something maintains.",
  );
});

test("the guard is looking at real files", () => {
  // A walker that silently found nothing would make the test above pass while
  // pinning nothing at all.
  const files = sources();
  assert.ok(files.length > 200, `expected the app to have sources, found ${files.length}`);
  assert.ok(files.some((f) => f.endsWith("components/banking/AccountsPanel.tsx")));
});
