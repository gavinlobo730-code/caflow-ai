// A failed load of a payroll screen says WHY, in the server's own words. Run with:
//   node --experimental-strip-types --test scripts/a-payroll-load-failure-says-why.test.ts
//
// WHY THIS EXISTS (POST-A-010, third step)
//     The staff payroll screens used to read straight from the database, where a person without payroll access got an empty answer
//     and a thrown error was nearly always a timeout, so "the request failed or timed out" was a fair sentence for every failed
//     load. They ask the server now, and the server refuses a person blocked from payroll with a 403 and a month it will not read
//     with a 422, in words. A screen that kept the old sentence would tell a Manager whose payroll permission was removed that the
//     request "timed out", and a Retry button that can never succeed.
//
// THE RULE, NOT A SPELLING: a payroll screen that asks the server for its list keeps the error it was given and prints it in
// the failed-load branch, falling back to the old sentence only when it was given none. The Reports page already did.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const code = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");
const read = (rel: string) => code(fs.readFileSync(path.join(WEB, rel), "utf8"));

const SCREENS: { rel: string; headline: RegExp }[] = [
  { rel: "app/payroll/attendance/page.tsx", headline: /Couldn&apos;t load attendance data/ },
  { rel: "app/clients/[id]/payroll/page.tsx", headline: /Couldn&apos;t load the payroll dashboard/ },
];

for (const { rel, headline } of SCREENS) {
  test(`${rel} keeps the server's sentence and prints it in its failed-load branch`, () => {
    const src = read(rel);
    assert.match(src, /const \[loadError, setLoadError\] = useState<string \| null>\(null\);/, "no state holds the reason");
    assert.match(src, /setLoadError\(null\);/, "the reason is not cleared when a load starts");
    assert.match(src, /setLoadError\([^;]*(?:e|err)\.message/, "a thrown error's message is not kept");
    const branch = src.split(headline)[1]?.slice(0, 160) ?? "";
    assert.match(branch, /\{loadError \?\? "the request failed or timed out\."\}/,
      "the failed-load branch does not print the reason, or lost its fallback");
  });
}

test("a month in the URL outside 1-12 is ignored by the attendance screen, not sent to the server to be refused", () => {
  const src = read("app/payroll/attendance/page.tsx");
  assert.match(src, /if \(m && Number\(m\[2\]\) >= 1 && Number\(m\[2\]\) <= 12\)/);
});

test("the negative control: a branch that prints the old sentence only is what the rule rejects", () => {
  const old = `<p>Couldn&apos;t load attendance data — the request failed or timed out.</p>`;
  const branch = old.split(/Couldn&apos;t load attendance data/)[1] ?? "";
  assert.doesNotMatch(branch, /\{loadError \?\? "the request failed or timed out\."\}/);
});
