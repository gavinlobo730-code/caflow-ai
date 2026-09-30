// Marking an obligation filed asks for the DATE it was filed, sends it, and tells
// the CA what the server did about the period.
//
// The defect (gst-27, practice_management-15, frontend_ux-26): /deadlines, a
// client's Compliance tab and Practice → Compliance walked an obligation to
// Filed and wrote nothing else, so a return the CA had just recorded as filed
// locked no period. The server now records the filing for a GSTR-1 or GSTR-3B and
// REQUIRES the date (422 without one). This guard states the rule over every
// caller rather than naming the three screens, so a fourth screen — or a
// refactor that goes back to `markFiled(id)` — fails here instead of starting to
// 422 in front of a CA, or worse, ticking without locking.
//
// Run with: node --experimental-strip-types --test scripts/mark-filed-asks-for-the-date-and-says-what-it-locked.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");

function sources(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sources(full));
    else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) out.push(full);
  }
  return out;
}

const FILES = ["app", "components", "lib"].flatMap((d) => sources(path.join(WEB, d))).map((f) => ({
  file: path.relative(WEB, f),
  code: stripComments(fs.readFileSync(f, "utf8")),
}));

/** The argument text of every call to `name(`, balanced on parentheses. */
function callsTo(code: string, name: RegExp): string[] {
  const out: string[] = [];
  const re = new RegExp(name.source + "\\(", "g");
  let m: RegExpExecArray | null;
  while ((m = re.exec(code))) {
    let depth = 1, i = re.lastIndex;
    while (i < code.length && depth > 0) {
      if (code[i] === "(") depth++;
      else if (code[i] === ")") depth--;
      i++;
    }
    out.push(code.slice(re.lastIndex, i - 1));
  }
  return out;
}

// The two names the OBLIGATION path is reached by: the data-layer wrapper (as
// imported under its alias on two screens) and the API client method.
const OBLIGATION_MARK_FILED = /\b(?:markObligationFiled|api\.complianceOps\.markFiled)/;

test("the premise: the obligation path is reached from more than one place", () => {
  const callers = FILES.filter((f) => callsTo(f.code, OBLIGATION_MARK_FILED).length > 0);
  assert.ok(callers.length >= 3, `expected at least the three screens, found ${callers.map((c) => c.file)}`);
});

test("every call that marks an obligation filed sends the date", () => {
  const offenders: string[] = [];
  for (const { file, code } of FILES) {
    for (const args of callsTo(code, OBLIGATION_MARK_FILED)) {
      if (!/\bfiledDate\b/.test(args)) offenders.push(`${file}: markFiled(${args.trim().slice(0, 60)})`);
    }
  }
  assert.deepEqual(offenders, [], "a GSTR-1/3B is refused (422) without the date it was filed on");
});

test("the data layer returns the server's answer and does not discard it", () => {
  const { code } = FILES.find((f) => f.file.endsWith(path.join("lib", "data", "compliance.ts")))!;
  const body = code.slice(code.indexOf("export async function markFiled"));
  const signature = body.slice(0, body.indexOf("{"));
  assert.doesNotMatch(signature, /Promise<void>/, "markFiled used to return void, which is how the lock answer was lost");
  assert.match(body.slice(0, 600), /return res\.data/);
});

test("the screens say what the server did about the period", () => {
  for (const f of ["app/deadlines/page.tsx", "app/clients/[id]/compliance/page.tsx", "app/practice/compliance/page.tsx"]) {
    const { code } = FILES.find((x) => x.file === f.split("/").join(path.sep))!;
    assert.match(code, /describeFilingOutcome\(/, `${f} must tell the CA whether the period was locked`);
  }
});

test("the prompt defaults visibly and never sends a date the CA did not see", () => {
  const { code } = FILES.find((x) => x.file.endsWith("MarkFiledModal.tsx"))!;
  assert.match(code, /type="date"/);
  assert.match(code, /value=\{filedDate\}/);
  assert.match(code, /max=\{today\}/, "a return cannot have been filed tomorrow");
  assert.match(code, /disabled=\{busy \|\| !filedDate\}/, "an empty date cannot be confirmed");
});

test("no screen still marks an obligation filed without the prompt", () => {
  // The old shape: an inline form holding an `arn` and nothing else.
  for (const f of ["app/deadlines/page.tsx", "app/clients/[id]/compliance/page.tsx"]) {
    const { code } = FILES.find((x) => x.file === f.split("/").join(path.sep))!;
    assert.match(code, /<MarkFiledModal/, f);
    assert.doesNotMatch(code, /placeholder="ARN Number \(optional\)"/, `${f} still carries the old ARN-only form`);
  }
});
