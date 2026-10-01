// A statutory due date is never written into a screen. Run with:
//   node --experimental-strip-types --test scripts/a-statutory-due-date-is-never-a-literal.test.ts
//
// WHY THIS EXISTS
//     app/income-tax/tax-audit/page.tsx headed the Tax Audit Tracker with
//
//         IT Act Section 44AB — Form 3CA/3CB/3CD | Due: 30 November
//
//     and that string was wrong twice over. Explanation (ii) to §44AB, as
//     substituted by the Finance Act 2020 w.e.f. AY 2020-21, makes the report's
//     "specified date" ONE MONTH PRIOR to the §139(1) due date — so the report
//     is due 30 September and the return 31 October. 30 November is the §92E
//     transfer-pricing date for the RETURN, and it was being shown as the
//     report's.
//
//     The backend had already been fixed: compliance_engine.tax_audit_report_
//     due_date derives 30 September from the return's own date, so a CBDT
//     extension of one moves the other, and _tax_audit_obligation uses it. None
//     of that could reach this page, because no backend was involved in it.
//     That is the shape worth guarding: not "this date is wrong" but "a date on
//     a screen that no engine produced cannot be corrected by fixing the
//     engine".
//
//     §271B is what makes it expensive — 0.5% of turnover, capped at
//     ₹1,50,000, on the obligation the header was dating two months late.
//
// WHAT THIS DOES NOT DO
//     It reads source, not behaviour. That the ENGINE is right is the Python
//     suite's job (tests/test_compliance_engine.py). What this pins is that no
//     screen states a statutory date of its own, and that this one asks.
//
//     It also strips comments before matching, deliberately. An earlier guard
//     in this repository matched the prose that EXPLAINED the fix and passed on
//     the code — the rule has to be read off the code, not off the file.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const TAX_AUDIT_PAGE = "app/income-tax/tax-audit/page.tsx";

/** Source with comments removed — see the header. */
function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .replace(/\/\/.*$/gm, "");
}

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === "node_modules" || e.name === ".next") continue;
      walk(full, out);
    } else if (e.name.endsWith(".tsx") || e.name.endsWith(".ts")) {
      out.push(path.relative(WEB, full));
    }
  }
  return out;
}

const MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December";
//: "Due: 30 November", "Due 31st October", "Due: November 30" — every spelling
//: of a date being ASSERTED as a deadline. The word "Due" is what makes it a
//: statutory claim rather than a placeholder or an example.
const DUE_LITERAL = new RegExp(
  String.raw`Due\b:?\s*(?:by\s*)?(?:\d{1,2}(?:st|nd|rd|th)?\s*(?:${MONTHS})` +
  String.raw`|(?:${MONTHS})\s*\d{1,2})`,
  "i",
);

//: Known and named, each with its own reason. An allow-list is how this stays a
//: ratchet rather than a wall — but every entry has to say WHY, or it is just a
//: place to put things.
const ALLOWED: Record<string, string> = {
  // Prose citing the SECTION, not this client's deadline: "the annual return is
  // due 31 December following the financial year" is the rule §44 states, in a
  // CA-review notice that explains why filing early shuts the correction window.
  // The dates the screen ACTS on come from the engine.
  "app/clients/[id]/compliance/gst/page.tsx": "a §44 citation in a review notice, not a computed deadline",

  // `app/calendar/page.tsx` LEFT THIS LIST on 01-10-2026 (practice_management-17).
  // It built FOURTEEN deadlines from browser literals — GSTR-1, GSTR-3B, GSTR-9,
  // four advance-tax instalments, four TDS returns, three MCA forms — attached
  // every one to ALL clients, and had already drifted from the engine by a day on
  // AOC-4 and MGT-7. It reads GET /api/compliance/obligations/calendar now, so
  // every date on it is one `compliance_engine` computed for that client, and it
  // holds none of its own. If that entry ever needs to come back, the screen has
  // started stating dates again.
};

test("no screen states a statutory due date of its own", () => {
  const offenders: string[] = [];
  for (const rel of walk(path.join(WEB, "app")).concat(walk(path.join(WEB, "components")))) {
    if (rel in ALLOWED) continue;
    const src = code(rel);
    for (const line of src.split("\n")) {
      if (DUE_LITERAL.test(line)) offenders.push(`${rel}: ${line.trim().slice(0, 120)}`);
    }
  }
  assert.deepEqual(
    offenders, [],
    "a due date written into a screen cannot be corrected by fixing the engine, "
    + "and services/compliance_engine.py is the single source for every one of "
    + "them (CLAUDE.md). Ask the backend instead:\n" + offenders.join("\n"),
  );
});

test("the Tax Audit Tracker asks the backend for both §44AB dates", () => {
  const src = code(TAX_AUDIT_PAGE);
  assert.match(src, /api\.compliance\.taxAuditDueDates\(/,
    "the header's dates must come from GET /api/compliance/tax-audit-due-dates");
  assert.match(src, /report_due_date/, "the report's own date must be shown");
  assert.match(src, /return_due_date/,
    "and the return's, because they are a month apart and a CA needs both");
});

test("every allowed exception still matches, so the list cannot go stale", () => {
  // An allow-list entry for a file that no longer offends is an entry nobody
  // will ever remove — and the next reader takes it as a live exception.
  for (const rel of Object.keys(ALLOWED)) {
    const src = code(rel);
    assert.ok(src.split("\n").some((l) => DUE_LITERAL.test(l)),
      `${rel} no longer states a due date — delete its entry from ALLOWED`);
  }
});

test("the two dates are shown as two, not conflated", () => {
  const src = code(TAX_AUDIT_PAGE);
  const header = src.slice(src.indexOf("Section 44AB"), src.indexOf("Section 44AB") + 600);
  assert.match(header, /report_due_date/i);
  assert.match(header, /return_due_date/i);
  assert.doesNotMatch(header, /30 November|31 October|30 September/,
    "a fallback literal beside the fetched value is the same defect with a "
    + "longer fuse — it is what renders when the request fails");
});
