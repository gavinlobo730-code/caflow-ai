// POST-A-254 — both GST return tabs report what the server said about the compliance obligation when a return was
// recorded as filed and it was not closed by the same click.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-return-recorded-filed-says-whether-its-obligation-closed.test.ts
//
// WHAT WAS WRONG
//     Recording a return as filed in the workspace left its obligation on the compliance calendar Not Started and
//     overdue, and nothing said so. The server closes the obligation now (`compliance_obligation` in the answer); where
//     it did not (no obligation on the calendar, another registration still to file, no Compliance access, a failure)
//     the tab must say so, from the server's own sentence, and decide nothing itself.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = path.join("app", "clients", "[id]", "compliance", "gst", "page.tsx");

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("each of the two client tabs reads the answer of its status call through the one helper and keeps every note", () => {
  const src = code(PAGE);
  assert.match(src, /import \{ obligationNote \} from "@\/lib\/gst\/obligationNote"/);
  const calls = src.match(/if \(status === "submitted"\) \{ const note = obligationNote\(r\.data\); if \(note\) setClosureNotes\(\(n\) => \[\.\.\.n, note\]\); \}/g) ?? [];
  assert.equal(calls.length, 2, "GSTR-1 and GSTR-3B must each report whether the obligation closed, without losing an earlier note");
});

test("both client tabs render the notes and let the CA dismiss them", () => {
  const src = code(PAGE);
  assert.equal((src.match(/closureNotes\.length > 0 && !filingRow/g) ?? []).length, 2);
  assert.equal((src.match(/setClosureNotes\(\[\]\)/g) ?? []).length >= 2, true);
});

test("the two firm-level screens show the note too: the mark-filed helpers return it and the pages render it", () => {
  const data = code(path.join("lib", "data", "gst.ts"));
  for (const fn of ["markGSTR1Filed", "markGSTR3BFiled"]) {
    const start = data.indexOf(`export async function ${fn}(`);
    assert.ok(start > 0, `${fn} is gone`);
    const body = data.slice(start, data.indexOf("\n}\n", start));
    assert.match(body, /Promise<string \| null>/, `${fn} drops the server's answer about the obligation`);
    assert.match(body, /return obligationNote\(/, `${fn} does not return the note`);
  }
  for (const [rel, fn] of [[path.join("app", "gst", "gstr1", "page.tsx"), "markGSTR1Filed"],
                           [path.join("app", "gst", "gstr3b", "page.tsx"), "markGSTR3BFiled"]]) {
    const src = code(rel);
    assert.match(src, new RegExp(`setFilingNote\\(await ${fn}\\(`), `${rel} throws the note away`);
    assert.match(src, /\{filingNote && \(/, `${rel} never shows it`);
  }
});

test("the browser decides nothing about the obligation: it never reads the state", () => {
  for (const rel of [PAGE, path.join("app", "gst", "gstr1", "page.tsx"), path.join("app", "gst", "gstr3b", "page.tsx")]) {
    assert.doesNotMatch(code(rel), /compliance_obligation/, `${rel} reads the block directly instead of through lib/gst/obligationNote`);
  }
});
