// POST-A-567 (found by its independent review) — the full-and-final settlement drawer sent an unreadable amount box as 0.
//
// `body()` reads each amount box with `paiseFromRupeeInput(text) ?? 0`, so "Notice pay recovered" typed as 12,50 (a comma where nobody writes
// one) drew "Not an amount." beside the box and the settlement was still previewed and RECORDED with nothing recovered, posting to the ledger.
// Preview and Record now ask `unreadableAmounts()` first and say which boxes in words, sending nothing.
//
//   node --experimental-strip-types --test scripts/a-settlement-over-an-amount-nobody-can-read-is-held.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const src = fs.readFileSync(path.join(import.meta.dirname, "..", "components", "payroll", "EmployeeDrawer.tsx"), "utf8");

function body(name: string): string {
  const at = src.indexOf(`async function ${name}() {`);
  assert.ok(at > 0, `${name}() is not in the drawer`);
  return src.slice(at, src.indexOf("\n  }\n", at));
}

test("Preview and Record refuse an unreadable amount box before anything is sent", () => {
  for (const name of ["preview", "record"]) {
    const fn = body(name);
    const ask = fn.indexOf("unreadableAmounts()");
    const send = fn.search(/api\.payroll\.(previewSettlement|recordSettlement)/);
    assert.ok(ask > 0, `${name}() does not ask which amount boxes are unreadable`);
    assert.ok(send > ask, `${name}() sends before it has asked`);
    assert.match(fn.slice(ask, send), /setErr\(unreadable\)/, `${name}() does not say which boxes`);
  }
});

test("every amount box the settlement body reads with a default of nothing is asked about", () => {
  const bodyText = src.slice(src.indexOf("function body(): SettlementInput"), src.indexOf("/** The amount boxes whose text is not an amount."));
  const read = [...bodyText.matchAll(/paiseFromRupeeInput\((\w+)\) \?\? 0/g)].map((m) => m[1]);
  assert.ok(read.length >= 5, `the body reads only ${read.length} boxes with a default`);
  const asked = src.slice(src.indexOf("function unreadableAmounts()"), src.indexOf("async function preview()"));
  for (const box of read) assert.ok(asked.includes(`, ${box}]`), `${box} is read as 0 when unreadable and is not on the list unreadableAmounts() asks about`);
});
