// CGST Rule 59(2) — the Invoice Furnishing Facility, on the screen (GST-11).
//
// A QRMP filer's GSTR-1 covers a quarter, and their customers' input tax credit
// waits for it unless the first two months are furnished early. The return's own
// caveats have said so since GST-11 (`return_period.IFF_AVAILABLE`); this asserts
// the CA can now act on the sentence rather than only read it.
//
// WHAT IS ASSERTED
//   1. ONE panel, rendered by BOTH GSTR-1 screens. The per-client and the
//      firm-level pages described one return differently before (GST-16, GST-22)
//      and the fix both times was one component; a second copy here would be the
//      same defect a third time.
//   2. It decides NOTHING. No cap figure, no due date, no month arithmetic in
//      the browser — every one of those is `domain/gst/iff.py`'s or the server's
//      resolved window's.
//   3. `buildGSTR1` CARRIES `period_window`. Dropping it is exactly what left
//      the firm-level GSTR-3B screen unable to render its own panels (GST-22),
//      and without it this panel cannot tell a quarterly filer from a monthly.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { panelSource } from "./panelSource.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (p: string) => fs.readFileSync(path.join(WEB, p), "utf8");

const SCREENS = [
  "app/gst/gstr1/page.tsx",
  "app/clients/[id]/compliance/gst/page.tsx",
];

test("one panel renders the facility, and it is not a page", () => {
  // Resolved by a phrase only the panel contains — never by a path, because a
  // guard that names a location fails on a move that does not break its rule.
  const src = panelSource("Invoice Furnishing Facility\n        </h4>");
  assert.match(src, /Rule 59\(2\)/);
});

test("both GSTR-1 screens render it", () => {
  for (const screen of SCREENS) {
    const src = read(screen);
    assert.match(src, /<IffPanel/,
      `${screen} does not render the facility — a quarterly filer opening ` +
      "this screen is the CA whose customers are waiting");
    assert.match(src, /from "@\/components\/gst\/IffPanel"/,
      `${screen} must import the one panel rather than spell it out`);
  }
});

test("the panel decides nothing the server decides", () => {
  const src = panelSource("Invoice Furnishing Facility\n        </h4>");

  // STATED AS WHERE EACH FIGURE COMES FROM, not as words the panel may not
  // contain. The first draft forbade the string "13th" and failed on the
  // sentence that TELLS the CA what the rule is — which is exactly the prose a
  // statutory screen should carry. A guard that fails on the documentation of
  // its own rule is a guard nobody keeps.
  assert.match(src, /formatPaise\(data\.cap_paise\)/,
    "the Rule 59(2) limit must be the server's figure — it is [S]-graded and " +
    "held once, in domain/gst/iff.py");
  assert.match(src, /data\.due_date/,
    "the furnishing deadline must be compliance_engine.iff_due_date's answer");
  assert.match(src, /formatPaise\(data\.cumulative_value_paise\)/,
    "the cumulative value must be the server's — which base it is measured on " +
    "is a reading of the rule, and the module says which it took");

  // NO DATE ARITHMETIC AT ALL. Which calendar months make a GST quarter is
  // `core.ist_clock.fy_quarters`'s answer and arrives as
  // `period_window.months`; a second answer here is one more place for a
  // quarter to mean something different.
  const code = src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1");
  assert.doesNotMatch(code, /new Date\(/,
    "the panel does date arithmetic instead of taking the server's window");
  assert.doesNotMatch(code, /months\[2\]/,
    "the third month of a quarter has no facility — offering it would ask the " +
    "server to declare the same documents twice");
});

test("it renders nothing for a monthly filer", () => {
  const src = panelSource("Invoice Furnishing Facility\n        </h4>");
  assert.match(src, /if \(!isQuarter/,
    "a monthly filer furnishes every month on the 11th; offering the facility " +
    "there is a control that does nothing");
});

test("buildGSTR1 carries the resolved window through", () => {
  const src = read("lib/data/gst.ts");
  const shaped = src.slice(src.indexOf("const shaped: GSTR1BuildResult"),
                           src.indexOf("await saveGSTR1Return"));
  assert.match(shaped, /period_window: result\.period_window/,
    "period_window is dropped on the way through, so the firm-level screen " +
    "cannot tell a quarterly filer from a monthly one — GST-22's shape");
  assert.match(shaped, /gstin: result\.gstin/,
    "the registration is dropped, so the facility could be prepared under a " +
    "different GSTIN from the return it belongs to (GST-20)");
});
