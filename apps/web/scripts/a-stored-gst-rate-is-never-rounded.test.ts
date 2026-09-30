// A stored GST rate is never rounded on the way into a screen, never truncated on
// the way out of a select, and every rate dropdown can show a rate that is not one
// of the standard slabs.
//
// The defect (GST-01): six line editors loaded gst_rate_bps with
// Math.round(bps / 100), the sales invoice select saved with parseInt, and the
// rate list stopped at 28. So 7.5% reopened as 8%, 1.5% as 2%, 0.25% as 0%, and a
// re-save wrote the wrong tax back into GSTR-1 and GSTR-3B. This guard states the
// RULE over every file rather than a spelling of it: any rounding applied to a
// gst_rate_bps value, any integer parse of a rate, and any dropdown that renders
// the bare list.
//
// Run with: node --experimental-strip-types --test scripts/a-stored-gst-rate-is-never-rounded.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const ROOTS = ["app", "components", "lib"].map((d) => path.join(WEB, d));

function sources(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sources(full));
    else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) out.push(full);
  }
  return out;
}

const FILES = ROOTS.flatMap(sources).map((f) => ({
  file: path.relative(WEB, f),
  code: stripComments(fs.readFileSync(f, "utf8")),
}));

// Rounding applied to a stored rate: Math.round( … gst_rate_bps … ). The legitimate
// direction, percent -> bps (`gst_rate_bps: Math.round(l.gst_rate * 100)`), names
// gst_rate_bps BEFORE Math.round and is not matched.
const ROUNDS_A_STORED_RATE = /Math\.(round|floor|ceil|trunc)\(\s*\(?[^)\n]*gst_rate_bps/;
// An integer parse on a line that is about a GST rate.
const PARSES_A_RATE_AS_INTEGER = /gst_rate[^\n]*\bparseInt\(|\bparseInt\([^\n]*gst_rate/;
// A dropdown rendering the bare standard list. The one allowed use has no stored
// rate to lose: the HSN quick-add offers "Varies / not set" on a NEW entry.
const BARE_LIST = /GST_RATES\.map\(/;
const BARE_LIST_ALLOWED = new Set([path.join("components", "lookups", "FirmHsnLibraryQuickAddModal.tsx")]);

test("the sweep reads the files it is about", () => {
  assert.ok(FILES.length > 500, `only ${FILES.length} source files read; bad roots?`);
  const loaders = FILES.filter((f) => f.code.includes("gstRateToPercent("));
  assert.ok(loaders.length >= 7, `expected the six editors and the catalogue to use the shared loader, found ${loaders.length}`);
});

test("no stored gst_rate_bps is rounded on the way into a screen", () => {
  const hits = FILES.filter((f) => ROUNDS_A_STORED_RATE.test(f.code)).map((f) => f.file);
  assert.deepEqual(hits, [], "use gstRateToPercent from lib/invoices/gst — it divides and never rounds");
});

test("no rate is parsed as an integer", () => {
  const hits = FILES.filter((f) => PARSES_A_RATE_AS_INTEGER.test(f.code)).map((f) => f.file);
  assert.deepEqual(hits, [], "use gstRatePercentFromSelect — parseInt turned 7.5 into 7");
});

test("every line rate dropdown can show a rate outside the standard list", () => {
  const hits = FILES.filter((f) => BARE_LIST.test(f.code) && !BARE_LIST_ALLOWED.has(f.file)).map((f) => f.file);
  assert.deepEqual(hits, [], "render gstRateOptions(line.gst_rate) so a stored rate always has an option");
});

test("the guard itself catches each spelling of the defect", () => {
  assert.ok(ROUNDS_A_STORED_RATE.test("gst_rate: Math.round((l.gst_rate_bps ?? 0) / 100),"));
  assert.ok(ROUNDS_A_STORED_RATE.test("patch.gst_rate = Math.round(p.gst_rate_bps / 100);"));
  assert.ok(!ROUNDS_A_STORED_RATE.test("{ quantity: q, gst_rate_bps: Math.round(l.gst_rate * 100) }"));
  assert.ok(PARSES_A_RATE_AS_INTEGER.test("setLine(idx, { gst_rate: parseInt(e.target.value) })"));
  assert.ok(BARE_LIST.test("{GST_RATES.map((r) => <option key={r}>{r}</option>)}"));
});
