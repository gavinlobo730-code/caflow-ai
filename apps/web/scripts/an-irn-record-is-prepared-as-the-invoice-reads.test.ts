// The Prepare IRN picker opens on the INVOICE's own treatment, never on a
// literal (SALES-19).
//
// Run with:
//   node --experimental-strip-types --test scripts/an-irn-record-is-prepared-as-the-invoice-reads.test.ts
//
// WHAT WAS WRONG
//     `einvoice_records.gst_treatment` is a SECOND record of what kind of
//     supply an invoice is. The first is the invoice's own `supply_type` +
//     `invoice_type`, which is what the GSTR-1 is built from and what
//     `domain/gst/treatment.treatment_for_invoice` derives from. The Prepare
//     IRN modal seeded its picker `useState<GstTreatment>("regular")` and was
//     never told what the invoice said, so a CA who had marked an invoice
//     SEZ-without-payment and left the picker alone stored a record
//     contradicting it — and this very panel then rendered both labels at
//     once: "Record prepared (Regular)" above a summary reading "SEZ under
//     LUT/Bond".
//
// THE DOOR IS THE FIX; THIS IS THE INVITATION
//     `POST /api/einvoice/records` now reconciles the two and REFUSES a
//     disagreement (apps/api/tests/test_one_supply_is_declared_one_way.py).
//     So a screen that still offered a free choice would be offering one the
//     server will reject — the same reasoning that makes the journal editor's
//     attachment control read-only on a posted entry rather than letting a CA
//     type something the server refuses.
//
// THE RULE IS THE INITIALISER, NOT A FILE OR A PROP NAME
//     A literal seed is the defect whatever it is called and wherever it
//     moves, so what is asserted is that no treatment state anywhere is
//     seeded from a bare string. Naming the component or the prop would state
//     one spelling of the rule, which is how the guard in this repository
//     goes vacuous.
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

/** `useState<GstTreatment>(…)` — the seed is group 1. */
const SEED = /useState\s*<\s*GstTreatment\s*>\s*\(([^)]*)\)/g;

test("no treatment picker is seeded from a literal", () => {
  const offenders: string[] = [];
  let seen = 0;
  for (const { rel, body } of sources()) {
    for (const m of body.matchAll(SEED)) {
      seen += 1;
      const seed = m[1].trim();
      // A literal is only safe as the TAIL of a fallback off something read —
      // `derived ?? "regular"` is the invoice's answer with a default behind
      // it for the window where the backend has not yet redeployed. A bare
      // `"regular"` asserts the supply is ordinary having asked nothing.
      if (/^["'`]/.test(seed)) offenders.push(`${rel}: useState<GstTreatment>(${seed})`);
    }
  }
  assert.ok(seen > 0, "found no treatment state at all — this guard has gone vacuous");
  assert.deepEqual(offenders, [], (
    "A GST treatment is a fact about the invoice, not a default. Seed it from " +
    "the invoice's own `gst_treatment` (derived server-side from supply_type + " +
    "invoice_type), and keep any literal behind a `??` as the redeploy-window " +
    "fallback:\n  " + offenders.join("\n  ")
  ));
});

// A SCREEN THAT SENDS NO TREATMENT CANNOT CONTRADICT ONE, and one does not:
// `app/einvoice/page.tsx` is the firm-level list, and its create form takes an
// invoice NUMBER and a date with no `sales_invoice_id` and no treatment at all.
// That is a record floating free of any invoice — a different, older gap — and
// the rule here reaches only a screen that states the treatment.
test("a screen that states a treatment reads the invoice's own", () => {
  const posters = sources().filter(({ body }) =>
    /["'`]\/api\/einvoice\/records["'`]/.test(body) && /\bgst_treatment\s*:/.test(body));
  assert.ok(posters.length > 0,
    "nothing posts a treatment with an e-invoice record — this guard has gone vacuous");
  for (const { rel, body } of posters) {
    assert.ok(
      /invoice\.gst_treatment/.test(body),
      `${rel} states a GST treatment on an e-invoice record without reading the ` +
      "invoice's own. The server refuses a record that contradicts its invoice, " +
      "so a screen that does not read it is offering a choice that 422s.",
    );
  }
});
