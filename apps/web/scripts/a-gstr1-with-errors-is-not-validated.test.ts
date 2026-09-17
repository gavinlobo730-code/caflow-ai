// A GSTR-1 carrying an error the portal will reject is a DRAFT, and the CA can
// see the error. Run with:
//   node --experimental-strip-types --test scripts/a-gstr1-with-errors-is-not-validated.test.ts
//
// WHY THIS EXISTS
//     domain/gst/validator.validate_gstr1 was reachable from POST
//     /gst/gstr1/build and POST /gst/validate/gstr1 only, and no screen calls
//     either — lib/data/gst.ts posts to /gst/gstr1/from-books. So the checks
//     that stop a return being rejected at the portal never ran on a return.
//
//     Two things in this file made that invisible from the browser side:
//
//       validation_warnings: [],          // a literal empty array
//       status: "validated",              // unconditional
//
//     under a comment reading "the from-books builder raises on anything it
//     will not compute, so a result in hand is a validated one". That was true
//     while the validator was unreachable and false the moment it was wired in:
//     a duplicate invoice number does not raise, it comes back as an error.
//
//     "Validated" is a claim that the checks RAN AND PASSED. It is written to
//     gstr1_returns.status, and ca_approved follows it.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "")
    .replace(/\/\/.*$/gm, "");
}

test("the from-books response type declares both validation fields", () => {
  const src = code("lib/data/gst.ts");
  assert.match(src, /interface FromBooksGSTR1[\s\S]*?validation_errors:\s*ValidationError\[\]/,
    "if the type does not carry them, tsc cannot tell anyone they were dropped");
  assert.match(src, /interface FromBooksGSTR1[\s\S]*?validation_warnings:\s*ValidationError\[\]/);
});

test("neither list is replaced by an empty array on the way through", () => {
  const src = code("lib/data/gst.ts");
  assert.doesNotMatch(src, /validation_warnings:\s*\[\]\s*,/,
    "this was a literal [] discarding whatever the endpoint returned");
  assert.doesNotMatch(src, /validation_errors:\s*\[\]\s*,/);
  assert.match(src, /validation_errors:\s*result\.validation_errors/);
  assert.match(src, /validation_warnings:\s*result\.validation_warnings/);
});

test("status is not unconditionally validated", () => {
  const src = code("lib/data/gst.ts");
  assert.doesNotMatch(src, /status:\s*"validated"\s*,/,
    'an unconditional status: "validated" claims the checks passed without ' +
    "looking at them");
  assert.match(src, /status:\s*readyToFile \? "validated" : "draft"/);
});

test("one predicate decides the status, and it reads BOTH lists", () => {
  // Named rather than inlined twice, so the status and its timestamp cannot
  // disagree about the same return — and asserted on the predicate rather than
  // on a spelling of the condition, which is what the first version of this
  // test did and what broke it the next time the condition grew a term.
  const src = code("lib/data/gst.ts");
  const decl = /const readyToFile\s*=([\s\S]*?);/.exec(src);
  assert.ok(decl, "saveGSTR1Return must name the condition it files on");
  assert.match(decl![1], /validation_errors/,
    "an error the portal rejects must stop a return being called validated");
  assert.match(decl![1], /payload_gaps/,
    "so must a document the payload does not carry — filing SHORT is the " +
    "failure a CA hears about from the recipient, not from us");
});

test("validated_at is not stamped on a draft", () => {
  // A timestamp saying when it was validated, on a return that was not, is the
  // same false claim in a second column.
  assert.match(code("lib/data/gst.ts"), /validated_at:\s*readyToFile \?/);
});

test("both status values are ones the table's CHECK accepts", () => {
  const migration = fs.readFileSync(
    path.resolve(WEB, "..", "api", "migrations", "036_gst_engine.sql"), "utf8");
  const check = /gstr1_returns[\s\S]*?status\s+TEXT[\s\S]*?CHECK \(status IN \(([^)]*)\)\)/.exec(migration);
  assert.ok(check, "gstr1_returns.status CHECK not found");
  const allowed = new Set([...check![1].matchAll(/'([^']+)'/g)].map((m) => m[1]));
  for (const v of ["draft", "validated"]) {
    assert.ok(allowed.has(v),
      `lib/data/gst.ts writes "${v}" and the CHECK rejects it — the write ` +
      "fails and the screen shows a state the database never took.");
  }
});

// BOTH SCREENS THAT COMPUTE A GSTR-1, NOT JUST THE ONE (GST-16).
//
// These two used to assert that app/gst/gstr1/page.tsx rendered
// `result.payload_gaps.map(...)` and `result.validation_errors.map(...)`
// inline — true, and a spelling of the rule rather than the rule. The CLIENT
// workspace's "Compute from Books" panel calls the same endpoint, got the same
// three lists, and rendered none of them: the reconciliation banner, the
// invoice count and two totals. So one computed return looked clean from
// inside a client and carried errors from the firm-level page.
//
// The lists now go through components/gst/Gstr1Findings on both, which is what
// makes them describe one return the same way, so the assertion is about the
// SCREENS THAT COMPUTE rather than about one file's JSX.
const COMPUTES_A_GSTR1 = [
  "app/gst/gstr1/page.tsx",
  "app/clients/[id]/compliance/gst/page.tsx",
];

test("every screen that computes a GSTR-1 renders what the validator said", () => {
  for (const rel of COMPUTES_A_GSTR1) {
    const src = code(rel);
    assert.match(src, /Gstr1Findings/, (
      `${rel} computes a GSTR-1 and does not render components/gst/Gstr1Findings. ` +
      "A gap, an error or a warning the builder computes and no screen shows is " +
      "not a fixed bug — and this is the screen a CA reaches from the client " +
      "they are working on."
    ));
    for (const key of ["validation_errors", "validation_warnings", "payload_gaps"]) {
      assert.match(src, new RegExp(key), `${rel} does not pass ${key} to it`);
    }
  }
});

test("the findings component keeps the three lists apart, in that order", () => {
  const src = code("components/gst/Gstr1Findings.tsx");
  // NOT DECLARED before ERRORS before WARNINGS. A gap is a document the return
  // does not carry at all and is the only one a CA cannot see any other way; an
  // error is a rejection and a warning is a judgement call, and one list would
  // make them look alike.
  const gaps = src.indexOf("Not declared in this return");
  const errors = src.indexOf("Errors — the portal will reject these");
  const warnings = src.indexOf("Warnings");
  assert.ok(gaps > 0 && errors > gaps, "a gap must be shown before an error");
  assert.ok(warnings > errors, "a rejection must be shown before a judgement call");
  // And nothing claims the return is clean: an "all checks passed" banner would
  // be a claim about checks this component does not run.
  assert.match(src, /if \(!errors\.length && !warnings\.length && !gaps\.length\) return null/,
    "with nothing to report it must render nothing rather than a reassurance");
});
