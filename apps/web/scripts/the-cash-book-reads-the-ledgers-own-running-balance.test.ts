/**
 * The Cash Book's Balance column always read ₹0.00 and never highlighted a
 * negative day (apex-accounting-reports-07).
 *
 * THE DEFECT
 *
 *   `GET /api/accounting/cash-book` serves each account's lines straight from
 *   `ReportingService.ledger()` (`domain/reporting/cash_book.py` says so in
 *   its own docstring: "NOT A SECOND LEDGER"), and that engine's per-line
 *   field is `running_balance_paise` (`domain/reporting/builders.py`).
 *   `components/banking/CashBook.tsx` typed the line as carrying
 *   `balance_paise` instead and read `l.balance_paise` to render and to
 *   colour the row — a field the payload never sends, so every row showed
 *   ₹0.00 and the negative-balance colouring (BANK-20's whole point) never
 *   fired.
 *
 * THE RULE
 *
 *   A Cash Book ledger line is read through `running_balance_paise`, never
 *   `balance_paise`. (`components/banking/BankBook.tsx` genuinely does carry
 *   a field named `balance_paise` — that is `services/bank_register_service.py`'s
 *   own vocabulary, a different endpoint entirely, and is out of scope here.)
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const FILE = join(import.meta.dirname, "..", "components/banking/CashBook.tsx");

function code(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((l) => l.replace(/\/\/.*$/, ""))
    .join("\n");
}

test("CashBook never reads a ledger line's balance as `balance_paise`", () => {
  const src = code(readFileSync(FILE, "utf8"));
  const badReads = src.match(/\bl\.balance_paise\b/g) ?? [];
  assert.deepEqual(
    badReads, [],
    "components/banking/CashBook.tsx reads a ledger line's balance as " +
    "`l.balance_paise`, a field the /api/accounting/cash-book payload never " +
    "sends (the reporting engine's field is `running_balance_paise`) — every " +
    "row will render ₹0.00 and the negative-balance highlight will never fire.",
  );
});

test("CashBook's CashLine type and its render both name running_balance_paise", () => {
  const src = code(readFileSync(FILE, "utf8"));
  assert.match(
    src, /running_balance_paise\??:\s*number\s*\|\s*null/,
    "CashLine should declare running_balance_paise (the reporting engine's " +
    "real field name), not balance_paise.",
  );
  const uses = (src.match(/\bl\.running_balance_paise\b/g) ?? []).length;
  assert.ok(
    uses >= 2,
    "expected the Balance column to both colour and render " +
    "l.running_balance_paise (found " + uses + " uses).",
  );
});
