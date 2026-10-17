// A foreign amount is shown with its currency's own number of decimals. Run with:
//   node --experimental-strip-types --test scripts/a-foreign-amount-is-formatted-with-its-currencys-own-decimals.test.ts
//
// WHY THIS EXISTS (ledger POST-A-129)
//     A foreign amount is integer MINOR units, and how many of them make one major unit is a fact about the currency:
//     JPY 0, INR and USD 2, KWD 3 (`currencies.minor_unit`). `formatMoney(minor, currency, minorUnits = 2)` honours the
//     exponent but none of its ten call sites passed it, so it divided every foreign amount by 100: a yen figure read a
//     hundredth of itself and a dinar lost its third decimal. The editors already load the master; the FX reports now
//     receive `minor_unit` on every row from the server (`fx_reporting_service._with_minor_units`).
//
//     THE RULE, not the ten spellings: no call to `formatMoney` may leave its exponent out.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const SKIP = new Set(["node_modules", ".next", "out"]);

function sources(dir: string): string[] {
  const found: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (SKIP.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) found.push(...sources(full));
    else if (/\.(ts|tsx)$/.test(entry.name) && !entry.name.endsWith(".test.ts")) found.push(full);
  }
  return found;
}

/** The arguments of every `formatMoney(` call in `text`, split on top-level commas. */
function callsOf(text: string): string[][] {
  const calls: string[][] = [];
  let at = text.indexOf("formatMoney(");
  while (at !== -1) {
    // `export function formatMoney(` is the definition, not a call
    const before = text.slice(Math.max(0, at - 16), at);
    let i = at + "formatMoney(".length, depth = 1, arg = "", args: string[] = [];
    while (i < text.length && depth > 0) {
      const c = text[i];
      if ("([{".includes(c)) depth++;
      else if (")]}".includes(c)) depth--;
      if (depth === 0) break;
      if (c === "," && depth === 1) { args.push(arg); arg = ""; } else arg += c;
      i++;
    }
    if (arg.trim()) args.push(arg);
    if (!/function\s*$/.test(before)) calls.push(args);
    at = text.indexOf("formatMoney(", at + 1);
  }
  return calls;
}

test("the scan finds the call sites, so a rename cannot make the rule vacuous", () => {
  const all = sources(ROOT).flatMap((f) => callsOf(fs.readFileSync(f, "utf8")));
  assert.ok(all.length >= 10, `expected at least the ten known call sites, found ${all.length}`);
});

test("no call to formatMoney leaves its exponent out", () => {
  const bare: string[] = [];
  for (const file of sources(ROOT)) {
    for (const args of callsOf(fs.readFileSync(file, "utf8"))) {
      if (args.length < 3) bare.push(`${path.relative(ROOT, file)}: formatMoney(${args.join(",").trim()})`);
    }
  }
  assert.deepEqual(bare, [], "pass the currency's minor unit (currencies.minor_unit) as the third argument");
});

test("formatMoney shows an unknown exponent as unknown and never divides by a guess", () => {
  const s = fs.readFileSync(path.join(ROOT, "lib/services/formatting.ts"), "utf8");
  assert.match(s, /minorUnits: number \| null = 2/);
  assert.match(s, /if \(minorUnits === null\) return "—";/);
});

test("the editors and pages take the exponent from the master they already load", () => {
  for (const rel of ["components/purchases/PurchaseBillEditor.tsx", "components/invoices/InvoiceEditor.tsx",
                     "app/clients/[id]/sales/page.tsx", "app/clients/[id]/purchases/page.tsx"]) {
    const s = fs.readFileSync(path.join(ROOT, rel), "utf8");
    assert.match(s, /formatMoney\((paise|minor), currency, currencies\.find\(\(c\) => c\.code === currency\)\?\.minor_unit\)/,
      `${rel} must pass the master's minor_unit`);
  }
});

test("the FX report rows carry the server's exponent into the formatting", () => {
  const s = fs.readFileSync(path.join(ROOT, "app/clients/[id]/accounting/page.tsx"), "utf8");
  for (const field of ["receivable_foreign_minor", "payable_foreign_minor", "bank_foreign_minor", "net_foreign_minor"]) {
    assert.match(s, new RegExp(`formatMoney\\(r\\.${field}, r\\.currency, r\\.minor_unit\\)`), field);
  }
  assert.match(s, /formatMoney\(r\.foreign_outstanding_minor, r\.currency, r\.minor_unit\)/);
  assert.match(s, /formatMoney\(b\.foreign_balance_minor, b\.currency, b\.minor_unit\)/);
});
