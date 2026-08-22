// The arithmetic behind the Cash Flow tab's multi-period view. Run with:
//   node --experimental-strip-types --test lib/accounting/cashFlowMatrix.test.ts
//
// Both mistakes this file guards against produce a plausible-looking wrong
// number rather than an error, which is why they are worth a test at all:
// an account dropped from a column it did not appear in, and cash on hand
// counted once per column instead of once.
import test from "node:test";
import assert from "node:assert/strict";
import {
  cfUnion, cfAmount, aggregateCashFlow, cashFlowTiesOut,
  type CFColumn, type CFData, type CFSection,
} from "./cashFlowMatrix.ts";

const L = (id: string, name: string, paise: number) => ({ account_id: id, account_name: name, amount_paise: paise });
const S = (lines: ReturnType<typeof L>[]): CFSection => ({
  label: "s", lines, total_paise: lines.reduce((t, l) => t + l.amount_paise, 0),
});

function data(over: Partial<CFData> = {}): CFData {
  return {
    start_date: "2026-04-01", end_date: "2026-04-30",
    operating: S([]), investing: S([]), financing: S([]),
    net_change_paise: 0, opening_cash_paise: 0, closing_cash_paise: 0,
    reconciles: true, non_cash_excluded_count: 0,
    operating_reconciliation: {
      net_profit_paise: 0, non_operating_adjust_paise: 0, depreciation_addback_paise: 0,
      working_capital_change_paise: 0, net_cash_operating_paise: 0, ties_out: true,
    },
    ...over,
  };
}
const col = (label: string, d: CFData | null): CFColumn =>
  ({ label, start: "2026-04-01", end: "2026-04-30", data: d, error: d === null });

const op = (d: CFData) => d.operating;

// ── The account union ────────────────────────────────────────────────────────

test("an account appearing in only one column still gets a row", () => {
  const cols = [
    col("Apr", data({ operating: S([L("a", "Cash from Customers", 500)]) })),
    col("May", data({ operating: S([L("b", "Rent Paid", -200)]) })),
  ];
  assert.deepEqual(cfUnion(cols, op).map((a) => a.name), ["Cash from Customers", "Rent Paid"]);
});

test("an account absent from a column reads as zero there, not as missing", () => {
  // The whole point of the union. If April's row vanished in May, the two
  // columns would list different accounts and could not be compared.
  const cols = [
    col("Apr", data({ operating: S([L("a", "Cash from Customers", 500)]) })),
    col("May", data({ operating: S([L("b", "Rent Paid", -200)]) })),
  ];
  assert.equal(cfAmount(cols[0].data, op, "a"), 500);
  assert.equal(cfAmount(cols[1].data, op, "a"), 0, "May did not move this account");
  assert.equal(cfAmount(cols[1].data, op, "b"), -200);
});

test("accounts keep first-seen order across columns", () => {
  const cols = [
    col("Apr", data({ operating: S([L("a", "A", 1), L("b", "B", 2)]) })),
    col("May", data({ operating: S([L("c", "C", 3), L("a", "A", 4)]) })),
  ];
  assert.deepEqual(cfUnion(cols, op).map((a) => a.id), ["a", "b", "c"]);
});

test("two accounts sharing a display name stay separate rows", () => {
  // Keyed on id, so they do not collapse into one row and add together.
  const cols = [col("Apr", data({ operating: S([L("a", "Bank", 100), L("b", "Bank", 250)]) }))];
  const u = cfUnion(cols, op);
  assert.equal(u.length, 2);
  assert.equal(cfAmount(cols[0].data, op, "a"), 100);
  assert.equal(cfAmount(cols[0].data, op, "b"), 250);
});

test("a failed column contributes no rows and reads as zero", () => {
  const cols = [col("Apr", data({ operating: S([L("a", "A", 500)]) })), col("May", null)];
  assert.deepEqual(cfUnion(cols, op).map((a) => a.id), ["a"]);
  assert.equal(cfAmount(cols[1].data, op, "a"), 0);
});

// ── The aggregate ────────────────────────────────────────────────────────────

const THREE = [
  col("Apr", data({ net_change_paise: 1000, opening_cash_paise: 5000, closing_cash_paise: 6000,
                    operating: S([L("a", "A", 1000)]) })),
  col("May", data({ net_change_paise: -400, opening_cash_paise: 6000, closing_cash_paise: 5600,
                    operating: S([L("a", "A", -400)]) })),
  col("Jun", data({ net_change_paise: 900, opening_cash_paise: 5600, closing_cash_paise: 6500,
                    operating: S([L("a", "A", 900)]) })),
];

test("flows add across periods", () => {
  const agg = aggregateCashFlow(THREE)!;
  assert.equal(agg.netChange, 1500);
  assert.equal(agg.operating, 1500);
});

test("opening is the FIRST column's and closing the LAST column's", () => {
  // The mistake this exists to prevent: summing them gives opening 16600 and
  // closing 18100 — both wrong, both plausible, neither flagged by anything.
  const agg = aggregateCashFlow(THREE)!;
  assert.equal(agg.opening, 5000, "opening cash counted more than once");
  assert.equal(agg.closing, 6500, "closing cash counted more than once");
});

test("the aggregate ties out", () => {
  const agg = aggregateCashFlow(THREE)!;
  assert.equal(agg.opening + agg.netChange, agg.closing);
  assert.ok(cashFlowTiesOut(agg));
});

test("one unreconciled column makes the whole window unreconciled", () => {
  const cols = [col("Apr", data({ reconciles: true })), col("May", data({ reconciles: false }))];
  assert.equal(aggregateCashFlow(cols)!.reconciles, false);
});

test("a gap in the columns is reported, not hidden", () => {
  // May failed, so Apr's opening and Jun's closing no longer bracket the flows
  // that were summed. The figures are still shown — a partial answer beats a
  // blank screen — but `complete` is what makes the UI say so.
  const cols = [THREE[0], col("May", null), THREE[2]];
  const agg = aggregateCashFlow(cols)!;
  assert.equal(agg.complete, false);
  assert.equal(agg.netChange, 1900, "only the periods that loaded");
  assert.ok(!cashFlowTiesOut(agg), "5000 + 1900 != 6500 — the gap is arithmetically visible");
});

test("every column loading is complete", () => {
  assert.equal(aggregateCashFlow(THREE)!.complete, true);
});

test("nothing loaded is null, not a screen of zeroes", () => {
  assert.equal(aggregateCashFlow([col("Apr", null), col("May", null)]), null);
  assert.equal(aggregateCashFlow([]), null);
});

test("one column aggregates to exactly itself", () => {
  // The single-period view goes through the same function, so it must be a
  // no-op there — otherwise the split control would change the summary strip.
  const one = [THREE[0]];
  const agg = aggregateCashFlow(one)!;
  assert.equal(agg.opening, 5000);
  assert.equal(agg.closing, 6000);
  assert.equal(agg.netChange, 1000);
  assert.ok(cashFlowTiesOut(agg));
});

test("ties-out is exact, not approximate", () => {
  // Integer paise throughout. A statement out by one paise is out.
  const cols = [col("Apr", data({ opening_cash_paise: 100, net_change_paise: 1, closing_cash_paise: 102 }))];
  assert.equal(cashFlowTiesOut(aggregateCashFlow(cols)), false);
});
