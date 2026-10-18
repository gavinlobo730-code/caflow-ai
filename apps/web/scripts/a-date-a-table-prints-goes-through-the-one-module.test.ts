// A date a PERSON READS is never the API's raw `YYYY-MM-DD` (POST-A-141). Run with:
//   node --experimental-strip-types --test scripts/a-date-a-table-prints-goes-through-the-one-module.test.ts
//
// WHAT WAS WRONG
//     `lib/dates/format.ts` is the one module that writes a date for a person (`05 Sep 2026`), and
//     `a-date-is-written-in-one-format.test.ts` bans every other spelling of a CALL. But a date rendered as
//     `{inv.invoice_date}` calls no function at all, so no rule about calls could see it, and the CA-facing money tables
//     (the sales, purchase and accounting lists, the bank book, the reconciliation, the GST and TDS panels) still printed the
//     API's `2026-09-05` beside amounts written the Indian way. 123 such renders, in 58 files, were found by this scan and
//     routed through `formatDate` / `formatDateTime` in the same change.
//
// THE RULE (stated by what is rendered, not by a list of files)
//     A JSX CHILD EXPRESSION that is a bare property path ending in a date-named field (`…_date`, `…_on`, `…_at`, `date`,
//     `period_start`, `period_end`), optionally followed by `?? "—"` / `|| "—"`, is a raw render. An attribute value
//     (`value={form.start_date}`) is not a child and is not read here, and neither is a template literal.
//
// WHAT THIS CANNOT SEE, AND SAYS SO
//     A date held in a variable first (`const d = row.invoice_date; … {d}`), a date inside a template literal in a toast or an
//     error sentence, a value computed to a string elsewhere, and any export or PDF (those take the same fields through the
//     server's formatter). The scan reads the field NAME, so a field that is not a date but is named like one would be flagged.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");

function* walk(dir: string): Generator<string> {
  for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    const rel = path.posix.join(dir, e.name);
    if (e.isDirectory()) {
      if (["node_modules", ".next", "out"].includes(e.name)) continue;
      yield* walk(rel);
    } else if (/\.tsx$/.test(e.name) && !/\.test\./.test(e.name)) {
      yield rel;
    }
  }
}

const NAME = String.raw`(?:[a-z][a-z0-9]*_)*(?:date|on|at)|date|period_start|period_end`;
/** `{ row.field }` or `{ row.field ?? "—" }` in child position: not after `=` (an attribute), a word, or `$` (a template). */
const BARE_DATE = new RegExp(
  String.raw`(?<![=\w$])\{\s*([A-Za-z_$][\w$]*(?:\??\.[A-Za-z_$][\w$]*)*?\??\.(?:${NAME}))\s*(?:(?:\?\?|\|\|)\s*(?:"[^"]*"|'[^']*'))?\s*\}`,
  "g",
);

/** Raw renders that are NOT an ISO date. Frozen: it may only shrink, and each says why. */
const NOT_ISO: Record<string, string> = {
  "app/gst/page.tsx": "{d.date}: keyDeadlines() builds display text such as '11 October 2026' itself",
  "app/mca/page.tsx": "{d.date}: keyDeadlines() returns _fmtShort(...), already display text",
};

function rawRenders(src: string): string[] {
  return [...stripComments(src).matchAll(BARE_DATE)].map((m) => m[0]);
}

test("no screen prints a date field raw", () => {
  const offenders: string[] = [];
  let scanned = 0;
  for (const dir of ["app", "components"]) {
    for (const rel of walk(dir)) {
      scanned++;
      const hits = rawRenders(fs.readFileSync(path.join(WEB, rel), "utf8"));
      const allowed = NOT_ISO[rel];
      for (const h of hits) {
        if (allowed && allowed.startsWith(h)) continue;
        offenders.push(`${rel}: ${h}`);
      }
    }
  }
  assert.ok(scanned > 300, `the scan read only ${scanned} files: it has gone vacuous`);
  assert.deepEqual(offenders, [], "a date is printed as the API sent it; write it with formatDate / formatDateTime (lib/dates/format.ts)");
});

test("the frozen exceptions still exist, so the list cannot outlive the code it excuses", () => {
  for (const [rel, why] of Object.entries(NOT_ISO)) {
    const hits = rawRenders(fs.readFileSync(path.join(WEB, rel), "utf8"));
    assert.ok(hits.some((h) => why.startsWith(h)), `${rel} no longer renders ${why.split(":")[0]}; remove it from NOT_ISO`);
  }
});

test("the screens that were swept now write their dates through the module", () => {
  const swept = [
    "app/clients/[id]/sales/page.tsx", "app/clients/[id]/purchases/page.tsx", "app/clients/[id]/accounting/page.tsx",
    "components/banking/ReconcileTab.tsx", "components/gst/Itc04Panel.tsx",
  ];
  for (const rel of swept) {
    const code = stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
    assert.match(code, /from "@\/lib\/dates\/format"/, `${rel} does not import the one date module`);
    assert.match(code, /formatDate\(/, `${rel} never calls formatDate`);
  }
});

test("the rule finds the raw shapes and passes the written ones (negative control)", () => {
  assert.deepEqual(rawRenders("<td>{i.invoice_date}</td>"), ["{i.invoice_date}"]);
  assert.deepEqual(rawRenders('<td>{b.bill_date ?? "—"}</td>'), ['{b.bill_date ?? "—"}']);
  assert.deepEqual(rawRenders('<span>{row?.nested?.created_at}</span>'), ["{row?.nested?.created_at}"]);
  assert.deepEqual(rawRenders("<td>{formatDate(i.invoice_date)}</td>"), []);
  assert.deepEqual(rawRenders("<input value={form.start_date} />"), [], "an attribute value is not read");
  assert.deepEqual(rawRenders("<p>{`on ${rec.receipt_date}`}</p>"), [], "a template literal is not read");
  assert.deepEqual(rawRenders("<td>{i.invoice_no}</td>"), [], "a reference number is not a date");
});
