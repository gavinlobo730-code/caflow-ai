// Sales > Add Customer, and Sales > Create Credit Note / Create Debit Note.
//
// Live browser testing found two compounding bugs. First: adding a customer
// that the backend genuinely created (HTTP 200, success: true, a real new
// row) was shown to the CA as "already exists — nothing new was created".
// Second: Credit Note and Debit Note creation had nothing stopping a second
// click from sending a second POST, and — believing the first attempt had
// failed (bug one) — a CA who clicked again got a REAL duplicate document:
// two identical ₹1,486 credit notes, two identical ₹7,080 debit notes, from
// what looked like one click each.
//
// `disabled={saving}` alone does not close this: React applies that to the
// DOM asynchronously, and a fast double-click (or a double-tap trackpad
// gesture — physically one action, two browser click events) can fire the
// handler a second time before the re-render lands. The second call then
// races the first's own network request. For the customer form specifically,
// the backend's GSTIN/PAN duplicate guard makes this worse than a plain
// double-write: the SECOND request's code path is shorter (no
// opening-balance sync, no audit/timeline logging) than the first's, so it
// can resolve FIRST and answer `duplicate: true` — because by then the
// first request's insert has already committed — painting "already exists"
// over a customer the first, slower request is still in the middle of
// genuinely creating.
//
// The fix, in every place below: a synchronous guard as the very FIRST
// statement of the save/submit handler, checked before any `await` and
// before `disabled` has any chance to matter — the same pattern already
// established at app/pipeline/page.tsx's handleSubmit
// (`if (saving) return; // guard against duplicate submissions
// (double-click / Enter)`), applied here rather than invented fresh.
//
// This is a SOURCE test, matching this repo's own convention for exactly
// this class of bug (scripts/concurrent-actions.test.ts,
// scripts/one-request-at-a-time.test.ts): the property is syntactic — the
// guard has to be the first thing the handler does — so reading the source
// proves it without standing up a DOM.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");

/** The `{...}` block starting at the `{` found at or after `from`, balanced. */
function braceBlock(src: string, from: number): string {
  const open = src.indexOf("{", from);
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}" && --depth === 0) return src.slice(open, i + 1);
  }
  throw new Error("unbalanced braces");
}

/** The body of the function declared by `signature` (e.g. "async function
 *  save()"), searched from `from` onward — so two same-named functions in
 *  one file (InvoiceViewDrawer.tsx has three `async function submit()`, one
 *  per modal) are told apart by which COMPONENT span they are searched in. */
function functionBodyAfter(src: string, signature: string, from = 0): string {
  const at = src.indexOf(signature, from);
  assert.ok(at >= from, `${JSON.stringify(signature)} not found from offset ${from}`);
  return braceBlock(src, at + signature.length);
}

/** A top-level `function Name(...) { ... }` component's own span, so a
 *  function name that repeats across components in one file (InvoiceViewDrawer
 *  .tsx's three `submit`s) is searched within the right one only. */
function componentSpan(src: string, name: string): [start: number, end: number] {
  const marker = `function ${name}(`;
  const start = src.indexOf(marker);
  assert.ok(start >= 0, `component ${name} not found`);
  const next = src.indexOf("\nfunction ", start + marker.length);
  return [start, next < 0 ? src.length : next];
}

const GUARD = /if\s*\(\s*saving\s*\)\s*return\s*;/;

for (const [file, signature] of [
  ["components/customers/CustomerFormModal.tsx", "async function handleSave()"],
  ["components/sales/SalesCreditNoteEditor.tsx", "async function save()"],
  ["components/sales/SalesDebitNoteEditor.tsx", "async function save()"],
] as const) {
  test(`${file} ignores a repeat click while one save is already in flight`, () => {
    const src = fs.readFileSync(path.join(WEB, file), "utf8");
    const body = functionBodyAfter(src, signature);
    assert.match(body, GUARD,
      `${file}'s handler must bail out synchronously (\`if (saving) return;\`) ` +
      "as its first real statement — disabled={saving} alone does not stop a " +
      "second click that lands before React re-renders the button");
  });
}

// InvoiceViewDrawer.tsx's two "raise this from the invoice" quick-create
// modals — same file, same handler name (`submit`), different components.
{
  const file = "components/invoices/InvoiceViewDrawer.tsx";
  const src = fs.readFileSync(path.join(WEB, file), "utf8");

  for (const component of ["CreateCreditNoteModal", "CreateSalesDebitNoteModal"] as const) {
    test(`${file}'s ${component} ignores a repeat click while one submit is in flight`, () => {
      const [start, end] = componentSpan(src, component);
      const span = src.slice(start, end);
      const body = functionBodyAfter(span, "async function submit()");
      assert.match(body, GUARD,
        `${component}'s submit() must bail out synchronously ` +
        "(`if (saving) return;`) as its first real statement");
    });
  }

  // RecordPaymentModal is a THIRD `submit` in this same file and is
  // deliberately not asserted here — recording a payment is not one of the
  // two document-creation flows this fix targets, and a guard requirement
  // stated broadly enough to catch it by accident would silently start
  // failing the day a fourth modal in this file adds its own `submit`.
  test("the guard is checked per COMPONENT, not merely per function name", () => {
    const spans = ["CreateCreditNoteModal", "CreateSalesDebitNoteModal", "RecordPaymentModal"]
      .map((c) => componentSpan(src, c));
    const [[a0, a1], [b0, b1], [c0, c1]] = spans;
    assert.ok(a1 <= b0 || b1 <= a0, "CreateCreditNoteModal and CreateSalesDebitNoteModal must not overlap");
    assert.ok(b1 <= c0 || c1 <= b0, "CreateSalesDebitNoteModal and RecordPaymentModal must not overlap");
  });
}
