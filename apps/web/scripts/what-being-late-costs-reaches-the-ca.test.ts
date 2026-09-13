// GST-21, the frontend half. §50 interest can be computed perfectly and the CA
// still work it out by hand, because the screen never asked when the return
// was filed and never rendered Table 5.1.
//
// Narrow on purpose — the panel's copy will change with the design pass. What
// must not change: the filing date is OPTIONAL and never defaulted to today,
// the figures come from the server, and the §47 refusal reaches the CA as the
// server's own sentence rather than being re-worded or hidden.
//
// Run with: node --experimental-strip-types --test scripts/what-being-late-costs-reaches-the-ca.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(__dirname, "..", "app", "clients", "[id]", "compliance", "gst", "page.tsx");
const code = stripComments(fs.readFileSync(PAGE, "utf8"));

test("the screen can be told when the return was filed", () => {
  assert.match(code, /const \[filedOn, setFiledOn\] = useState\(""\)/);
  assert.match(code, /aria-label="Date filed"/);
});

test("the filing date is optional and is never defaulted to today", () => {
  // A default of today would put an interest figure on Table 5.1 that changes
  // every day the return is not filed.
  assert.match(code, /useState\(""\);?\s*$/m);
  assert.doesNotMatch(code, /setFiledOn\(\s*(todayLocalISO|new Date)/,
    "the filing date must start empty");
  // Sent only when the CA has filled it in.
  assert.match(code, /\.\.\.\(filedOn \? \{ filed_on: filedOn \} : \{\}\)/);
});

test("Compute is not gated on the filing date", () => {
  // The date is for the interest, not for the return. Requiring it would stop
  // a CA computing a return they are about to file.
  assert.doesNotMatch(code, /disabled=\{[^}]*!filedOn/);
});

test("the interest figures come from the server", () => {
  assert.match(code, /computeResult\.late_filing/);
  assert.match(code, /interest_total_paise/);
  assert.doesNotMatch(code, /\*\s*0?\.?18|18\s*\/\s*100/,
    "the rate is applied in apps/api — a second computation here is how the " +
    "screen and the return come to disagree");
});

test("the §47 refusal reaches the CA in the server's own words", () => {
  assert.match(code, /late_fee\?\.refused/);
  assert.match(code, /\{lf\.late_fee\.reason\}/,
    "the sentence naming the notification to read is the server's — rewording " +
    "it here would give one gap two descriptions");
});

test("no filing date says why, rather than showing a nil", () => {
  // A nil interest figure reads as "nothing is owed". "Tell me when you filed"
  // is the truth.
  assert.match(code, /if \(!lf\.available\)/);
  assert.match(code, /\{lf\.reason\}/);
});

test("the per-head working is shown, because that is what a CA checks", () => {
  // The RENDER, not the type declaration. A first draft matched
  // `interest_by_head` anywhere and passed with the table switched off — the
  // identifier survives in the type and in the `const heads = …` line.
  assert.match(code, /\{heads\.length > 0 && \(/,
    "the per-head table is not rendered on the heads it has — a CA checking " +
    "18% × days/365 on each head has only the total");
  assert.match(code, /heads\.map\(\(h\) => \(/);
  assert.match(code, /\{rupees\(h\.base_paise\)\} × 18% × \{h\.days\}\/365/,
    "the working is what makes the total checkable");
});
