// The stock ledger's Balance column is derived server-side, in display order,
// and the register can be asked for a DATE. Run with:
//   node --experimental-strip-types --test scripts/a-stock-balance-is-a-property-of-its-order.test.ts
//
// WHY THIS EXISTS (INV-01)
//     inventory_stock_ledger carries a per-movement delta AND a stored running
//     total, and the two answer different questions. The running totals are
//     chained in INSERTION order — deliberately, so a bill received late does
//     not fall out of the chain (apps/api/domain/inventory_service.py,
//     _last_ledger_row). get_stock_ledger returns rows in DATE order. This
//     screen rendered the stored columns beside the date order, so with a
//     1 July bill entered after a 10 July sale it showed "+20 → balance 110"
//     above "−10 → balance 90": neither row adds up, and a CA reconciling
//     stock cannot tell why.
//
//     Nothing a behaviour test would notice is broken — every number on screen
//     is a number the database really holds. That is exactly why it survived,
//     and why the guard has to be about WHICH FIELD IS RENDERED.
//
// WHAT IS ASSERTED
//     1. The Balance cells read balance_qty_units / balance_value_paise, and
//        the stored running_* columns are not rendered anywhere.
//     2. The balance is not recomputed in the browser. A second implementation
//        of a running total is how the first one drifted; the server sends the
//        opening, the per-row balance and the closing, and the screen prints
//        them.
//     3. The register can be asked "as at" a date, and says which question it
//        is answering — a closing-stock statement and today's position are not
//        interchangeable.
//     4. The as-at register does not show a Status column. Whether an item is
//        archived TODAY is not a fact about 31 March.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const PAGE = "app/clients/[id]/inventory/page.tsx";
const src = readFileSync(PAGE, "utf8");

function table(): string {
  const i = src.indexOf("<tbody");
  assert.ok(i > 0, "the ledger table must still be a <tbody>");
  const j = src.indexOf("</tbody>", i);
  assert.ok(j > i, "…with a closing tag");
  return src.slice(i, j);
}

test("the Balance cells read the derived balance, never the stored chain", () => {
  const body = table();
  assert.match(body, /\{fmtQty\(l\.balance_qty_units\)\}/,
    "Balance Qty must render balance_qty_units");
  assert.match(body, /formatServicePrice\(l\.balance_value_paise\)/,
    "Balance Value must render balance_value_paise");

  // The stored columns may be TYPED (the payload still carries them) but must
  // not be rendered: beside a date-ordered list they do not foot.
  assert.doesNotMatch(src, /\{fmtQty\(l\.running_qty_units\)\}/,
    "running_qty_units is the insertion-order chain and must not be a Balance cell");
  assert.doesNotMatch(src, /formatServicePrice\(l\.running_value_paise\)/,
    "running_value_paise is the insertion-order chain and must not be a Balance cell");
});

test("the browser does not compute a running total of its own", () => {
  // A reduce/accumulator over the lines would be a second implementation of
  // the rule in apps/api/domain/reporting/stock_position.py. Two of them drift,
  // and the drift is invisible until a CA cannot tie the stock to the GL.
  assert.doesNotMatch(src, /lines\s*\.\s*reduce/,
    "the per-row balance comes from the server, not from a reduce over lines");
  assert.match(src, /const \[opening, setOpening\] = useState<LedgerEdge \| null>/,
    "the opening position is server state");
  assert.match(src, /const \[closing, setClosing\] = useState<LedgerEdge \| null>/,
    "so is the closing position");
  assert.match(src, /setOpening\(res\.data\.opening \?\? null\)/,
    "both are read off the ledger response");
});

test("an opening and a closing row bracket the movements", () => {
  const body = table();
  assert.match(body, />Opening Balance</, "the range must open on a position");
  assert.match(body, />Closing Balance</, "and close on one");
  assert.match(body, /fmtQty\(opening\.qty_units\)/);
  assert.match(body, /fmtQty\(closing\.qty_units\)/);
});

test("a range with no movements still shows what was held", () => {
  // Nothing MOVED is not the same as holding nothing, and an empty box says
  // the second thing.
  const empty = src.slice(src.indexOf("No stock movements for this item"));
  assert.match(empty.slice(0, 700), /Held \{fmtQty\(opening\.qty_units\)\}/,
    "the empty range must still report the position it opened and closed on");
});

test("the register can be asked as at a date, and says which it is showing", () => {
  assert.match(src, /api\.inventory\.stockSummary\(\{ client_id: clientId, as_of: asAt \}\)/,
    "the as-at register must call the server's stock-summary endpoint");
  assert.match(src, /Closing value as at \$\{asAt\}/,
    "the subtitle must name the date when one is asked for");
  assert.match(src, /id="stock-as-at"/, "and there must be a control to ask with");
});

test("the as-at register drops the Status column", () => {
  // The filter grew a second exclusion when INV-10 put row ACTIONS on the
  // register: both modals print their figures as what is on hand "currently",
  // and in as-at mode those are the figures as at the chosen date. So this now
  // asserts the RULE — a today-fact is not shown on a dated statement — rather
  // than one spelling of the expression, and names both things it covers.
  assert.match(src, /c\.key !== "is_active"/,
    "an item's archived flag is a fact about today, not about the date asked for");
  assert.match(src, /c\.key !== "actions"/,
    "and neither is 'currently N on hand', which is what both action modals print");
  assert.match(src, /const columns = asAt/,
    "the exclusion must key off the as-at mode");
});
