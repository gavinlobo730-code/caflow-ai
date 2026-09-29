/**
 * TrialBalance, FXReports, ProfitAndLoss, BalanceSheet and CashFlow each
 * called `useLedgerSpan(clientId)` on their own (apex-accounting-reports-12)
 * — five separate GET /api/accounting/ledger-span requests for the SAME
 * client — and because each is a sibling tab that unmounts when another is
 * shown, switching back to a report tab re-fetched the span every time
 * instead of once per client for the whole page.
 *
 * THE RULE
 *
 *   `useLedgerSpan(clientId)` is called exactly ONCE on this page, in the
 *   top-level AccountingPage component, and its result is threaded down as
 *   a `ledgerSpan` prop to TrialBalance, FXReports, ProfitAndLoss,
 *   BalanceSheet and CashFlow.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const FILE = join(import.meta.dirname, "..", "app/clients/[id]/accounting/page.tsx");

function code(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((l) => l.replace(/\/\/.*$/, ""))
    .join("\n");
}

test("useLedgerSpan(clientId) is called exactly once on the accounting page", () => {
  const src = code(readFileSync(FILE, "utf8"));
  const calls = src.match(/useLedgerSpan\(clientId\)/g) ?? [];
  assert.equal(
    calls.length, 1,
    `expected exactly one useLedgerSpan(clientId) call (found ${calls.length}) — ` +
    "TrialBalance, FXReports, ProfitAndLoss, BalanceSheet and CashFlow must " +
    "each receive it as a `ledgerSpan` prop from the page instead of calling " +
    "the hook themselves, or switching between report tabs re-fetches the " +
    "client's ledger span on every visit.",
  );
});

const COMPONENTS = ["TrialBalance", "FXReports", "ProfitAndLoss", "BalanceSheet", "CashFlow"];

for (const name of COMPONENTS) {
  test(`${name} takes ledgerSpan as a prop rather than calling the hook itself`, () => {
    const src = code(readFileSync(FILE, "utf8"));
    const sigMatch = src.match(new RegExp(`function ${name}\\(\\{[^}]*\\}:\\s*\\{[^}]*\\}\\)\\s*\\{`));
    assert.ok(sigMatch, `expected to find ${name}'s function signature`);
    assert.match(
      sigMatch![0], /ledgerSpan/,
      `${name}'s props must include ledgerSpan`,
    );
  });

  test(`${name} is passed a ledgerSpan prop where it is rendered`, () => {
    const src = code(readFileSync(FILE, "utf8"));
    const jsxMatches = src.match(new RegExp(`<${name}\\b[^>]*>`, "g")) ?? [];
    assert.ok(jsxMatches.length > 0, `expected to find <${name}> in the JSX`);
    for (const jsx of jsxMatches) {
      assert.match(jsx, /ledgerSpan=\{ledgerSpan\}/, `${jsx} must pass ledgerSpan={ledgerSpan}`);
    }
  });
}
