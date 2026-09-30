// An AI-extracted invoice line is built from what the document said and from
// nothing else: a quantity, unit, rate or GST rate it did not state is shown
// empty and flagged, never given a value.
//
// The defect (AI-01 / GST-03): the purchase editor built an extracted line as
//   qty: String(li.quantity ?? 1), unit: "NOS", gst_rate: (li.gst_rate_bps ?? 1800) / 100
// on top of a server that had already turned a read 0% into 18%, so the screen
// showed a quantity of 1, a unit of NOS and a tax rate of 18% as if the document
// had carried them. The rule is stated over every file that calls the extraction
// endpoint rather than over the one spelling that shipped.
//
// Run with: node --experimental-strip-types --test scripts/an-extracted-line-is-never-given-a-default.test.ts
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
    if (entry.name === "node_modules" || entry.name === ".next" || entry.name === "out") continue;
    if (entry.isDirectory()) out.push(...sources(full));
    else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) out.push(full);
  }
  return out;
}

const FILES = ["app", "components", "lib"]
  .flatMap((d) => sources(path.join(WEB, d)))
  .map((f) => ({ file: path.relative(WEB, f), code: stripComments(fs.readFileSync(f, "utf8")) }));

const CALLERS = FILES.filter((f) => f.code.includes("document-intelligence-v1/extract-invoice"));

// What the old loader put on a line it had not read.
const INVENTED = [
  { name: "a quantity of 1", re: /quantity\s*\?\?\s*1\b/ },
  { name: "a unit of NOS", re: /unit\s*:\s*"NOS"/ },
  { name: "a GST rate of 18%", re: /gst_rate(_bps)?\s*\?\?\s*(1800|18)\b/ },
  { name: "a rate of nil", re: /rate_paise\s*\?\?\s*0\b/ },
];

test("the sweep finds the screen that calls the extraction endpoint", () => {
  assert.ok(FILES.length > 500, `only ${FILES.length} source files read; bad roots?`);
  assert.ok(CALLERS.length >= 1, "no caller of extract-invoice found — the guard would be vacuous");
});

test("every caller builds its lines through lineFromExtraction", () => {
  const missing = CALLERS.filter((f) => !f.code.includes("lineFromExtraction(")).map((f) => f.file);
  assert.deepEqual(missing, [], "build extracted lines with lineFromExtraction (lib/purchases/billEditor.ts)");
});

test("no caller hands an extracted line a quantity, unit, rate or GST rate of its own", () => {
  for (const caller of CALLERS) {
    // Only the extraction handler: the same file legitimately defaults a BLANK
    // new line (EMPTY_LINE), which is a line nobody claims the document read.
    const start = caller.code.indexOf("document-intelligence-v1/extract-invoice");
    const handler = caller.code.slice(start, start + 6000);
    for (const { name, re } of INVENTED) {
      assert.ok(!re.test(handler), `${caller.file}: the extraction handler gives a line ${name}`);
    }
  }
});

test("the patterns detect what they claim to", () => {
  assert.ok(INVENTED[0].re.test("qty: String(li.quantity ?? 1)"));
  assert.ok(INVENTED[1].re.test('qty: "1", unit: "NOS",'));
  assert.ok(INVENTED[2].re.test("gst_rate: (li.gst_rate_bps ?? 1800) / 100"));
  assert.ok(INVENTED[3].re.test("Math.floor((li.rate_paise ?? 0)) / 100"));
  assert.ok(!INVENTED[2].re.test("gst_rate: bps / 100"));
});
