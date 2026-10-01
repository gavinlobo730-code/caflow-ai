// A screen offers the SERVER's s.194A limit classes and spells none of its own (TDS-30).
//
// Run with:
//   node --experimental-strip-types --test scripts/a-screen-offers-the-servers-194a-limit-classes-and-spells-none.test.ts
//
// WHAT THE FINDING SUGGESTED, AND WHY THE SCREEN MUST NOT HOLD IT
//     "Bank, senior citizen, other" read as three PAYEE classes. s.194A(3)(i)'s
//     senior-citizen limit (₹1,00,000) exists only INSIDE the bank-deposit limb —
//     the payer is a bank, a co-operative bank or a post office. A screen that
//     offered "senior citizen" as an option of its own would hand ₹1,00,000 to a
//     payee whose payer is a company, and an under-deduction disallows 30% of the
//     expenditure under s.40(a)(ia). The classes are the PRODUCT of two facts,
//     they are served by `GET /api/tds/sections` (`threshold_classes`), and the
//     whole of the browser's part is to render what it is given.
//
// THE RULE
//     No file under app/, components/ or lib/ spells a limit class
//     (`bank_deposit`, `bank_deposit_senior`) or the figures beside them. The
//     one word the browser does hold is `ordinary`, because a PATCH drops a null
//     and that is how a recorded class is taken back — it is the server's word
//     for it and says nothing about a limit.
//
//     And both screens that record a supplier's TDS section — the client
//     workspace's Vendors tab and the firm-level Supplier Master — render the
//     one picker, which renders NOTHING unless the server says the chosen
//     section carries classes. A third vendor form that records a section
//     without it fails here; that is what makes the rule a rule rather than two
//     screens that happen to agree.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");

function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");
}

function sources(): { rel: string; body: string }[] {
  const out: { rel: string; body: string }[] = [];
  const walk = (dir: string) => {
    if (!fs.existsSync(dir)) return;
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name === "node_modules" || e.name === ".next" || e.name.startsWith(".")) continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.tsx?$/.test(e.name)) {
        out.push({ rel: path.relative(WEB, p), body: code(fs.readFileSync(p, "utf8")) });
      }
    }
  };
  for (const d of ["app", "components", "lib"]) walk(path.join(WEB, d));
  return out.sort((a, b) => a.rel.localeCompare(b.rel));
}

const PICKER = "components/tds/InterestThresholdClassSelect.tsx";

test("the guard reads real sources", () => {
  const all = sources();
  assert.ok(all.length > 100, "no sources found — every assertion below would pass vacuously");
  assert.ok(all.some((s) => s.rel === PICKER), "the picker is missing");
});

test("no screen spells a limit class", () => {
  const offenders = sources()
    .filter((s) => /bank_deposit/.test(s.body))
    .map((s) => s.rel);
  assert.deepEqual(offenders, [],
    "a limit class is the SERVER's vocabulary — render `threshold_classes` from " +
    "GET /api/tds/sections instead of spelling one");
});

test("no screen offers a payee's age as a limit of its own", () => {
  // The finding's reading, which would under-deduct. 'senior' as a VALUE of the
  // class (not as a flag on s.80D/80TTB, which are unrelated) is the tell.
  const offenders = sources()
    .filter((s) => /threshold_class[^\n]*senior|interest_threshold_class[^\n]*senior/i.test(s.body))
    .map((s) => s.rel);
  assert.deepEqual(offenders, []);
});

test("the picker renders the server's list and nothing when there is none", () => {
  const src = sources().find((s) => s.rel === PICKER)!.body;
  assert.match(src, /threshold_classes/, "it must read the served list");
  assert.match(src, /classes\.length === 0\) return null/, "it must render nothing for a section without classes");
  assert.doesNotMatch(src, /194A/, "it must not know which section carries the classes");
});

test("both screens that record a supplier's TDS section use it", () => {
  const recordsASection = sources().filter((s) =>
    /app\/(accounting\/suppliers|clients\/\[id\]\/purchases)\/page\.tsx$/.test(s.rel.replace(/\\/g, "/")));
  assert.equal(recordsASection.length, 2, "expected the Supplier Master and the client Vendors tab");
  for (const s of recordsASection) {
    assert.match(s.body, /<InterestThresholdClassSelect/, `${s.rel} records a TDS section without the limit-class picker`);
  }
});

test("a recorded class is taken back with the word for it, never by omission", () => {
  // A PATCH drops a null, so omitting the field leaves the stored class standing
  // while the screen shows 'Not stated'. Both writers send 'ordinary'.
  const writers = sources().filter((s) =>
    /app\/(accounting\/suppliers|clients\/\[id\]\/purchases)\/page\.tsx$/.test(s.rel.replace(/\\/g, "/")));
  for (const s of writers) {
    assert.match(s.body, /"ordinary"/, `${s.rel} cannot take a recorded class back`);
  }
});
