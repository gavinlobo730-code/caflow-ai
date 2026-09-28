// apex-sales-purchases-11: InvoiceEditor's suggested-invoice-number auto-fill
// effect lists `invoiceNo` itself in its own dependency array, so
// setInvoiceNo(suggested) re-triggers the SAME effect (after a debounce) and
// the backend's number-suggestion endpoint was asked a second time about the
// number it just suggested. Separately, the auto-filled number was never
// reflected into `initialSnapshot`, so a brand-new invoice form read as
// "Unsaved changes" the instant it opened, before the CA had typed anything.
//
// THE FIX
//     `lastAutoFilledFor` records the (client, date) a suggestion was FOR;
//     the effect skips its own fetch when the box still reads exactly what it
//     last auto-filled AND neither the client nor the date has moved on since
//     — a plain "same value" check alone would also skip a REAL refetch when
//     the invoice date changes without the box being touched (SALES-24). The
//     auto-fill also now writes into `initialSnapshot.current`, the same
//     technique the line-item rehydration effect uses.
//
// Run with:
//   node --experimental-strip-types --test scripts/invoice-number-autofill-does-not-mark-dirty-or-refetch.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const SRC = stripComments(fs.readFileSync(path.join(WEB, "components/invoices/InvoiceEditor.tsx"), "utf8"));

test("a ref records which (client, date) the last auto-fill was for", () => {
  assert.match(
    SRC,
    /const lastAutoFilledFor = useRef<\{ clientId: string; invoiceDate: string \} \| null>\(null\);/,
  );
});

test("the effect skips its own re-fetch when nothing has changed since its last auto-fill", () => {
  const m = /useEffect\(\(\) => \{\s*\n\s*if \(!clientId \|\| isLocked\) return;\s*\n\s*const typed = invoiceNo\.trim\(\);([\s\S]*?)\n\s*let cancelled = false;/.exec(SRC);
  assert.ok(m, "the number-suggestion effect's guard clause was not found");
  const guard = m[1];
  assert.match(guard, /typed && typed === lastAutoFilled\.current/);
  assert.match(guard, /lastAutoFilledFor\.current\?\.clientId === clientId/);
  assert.match(guard, /lastAutoFilledFor\.current\?\.invoiceDate === invoiceDate/);
  assert.match(guard, /return;/);
});

test("auto-filling the number also stamps lastAutoFilledFor with the (client, date) it answered", () => {
  assert.match(
    SRC,
    /lastAutoFilled\.current = d\.suggested_number;\s*\n\s*lastAutoFilledFor\.current = \{ clientId, invoiceDate \};\s*\n\s*setInvoiceNo\(d\.suggested_number\);/,
  );
});

test("auto-filling the number also updates initialSnapshot.current, so the form does not read as dirty", () => {
  const m = /setInvoiceNo\(d\.suggested_number\);([\s\S]*?)\n\s*\}\s*\n\s*\} catch \{/.exec(SRC);
  assert.ok(m, "the auto-fill block was not found");
  assert.match(
    m[1],
    /initialSnapshot\.current = \{ \.\.\.initialSnapshot\.current, invoiceNo: d\.suggested_number \};/,
  );
});
