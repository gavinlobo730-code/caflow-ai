// A GSTR-1 built from the books carries the amendment tables the period owes,
// and BOTH screens that build one say so (gst-33).
//
// CGST Act §37: a filed GSTR-1 can never be revised, so a correction to an earlier
// period is declared in a LATER return's Tables 9A / 9C / 10. Those used to come
// from a second route and a second file, so the file the GSTR-1 screen built was
// the one WITHOUT them. The server carries them by default now and answers with an
// `amendments` block; the browser decides nothing about them. What this holds is
// the half a server cannot: the block is carried through the shaper, both screens
// render it from ONE component, and both can leave the amendments out — a file
// must never carry corrections nobody was told about.
//
// Run with: node --experimental-strip-types --test scripts/a-gstr1-build-says-what-amendments-it-carries.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

const PANEL = read("components/gst/Gstr1Amendments.tsx");
const DATA = read("lib/data/gst.ts");
const FIRM_SCREEN = read("app/gst/gstr1/page.tsx");
const CLIENT_SCREEN = read("app/clients/[id]/compliance/gst/page.tsx");

test("the shaper carries the block through instead of dropping it", () => {
  assert.match(DATA, /amendments: result\.amendments/);
  assert.match(DATA, /export (interface|type) GSTR1AmendmentsBlock/);
});

test("both screens render the one component from the server's block", () => {
  assert.match(FIRM_SCREEN, /<Gstr1Amendments block=\{result\.amendments\} \/>/);
  assert.match(CLIENT_SCREEN, /<Gstr1Amendments block=\{computeResult\.amendments as GSTR1AmendmentsBlock \| undefined\} \/>/);
});

test("both screens can leave the amendments out, and say nothing when they are left in", () => {
  // `include_amendments: false` is sent only when unticked: an absent key is the
  // server's default (in), so an older backend is never handed a field it would
  // have to ignore.
  assert.match(DATA, /include_amendments: false/);
  assert.match(CLIENT_SCREEN, /include_amendments: false/);
  assert.match(CLIENT_SCREEN, /includeAmendments \? \{\} : \{ include_amendments: false \}/);
  assert.match(FIRM_SCREEN, /useState\(true\)/);
  assert.match(FIRM_SCREEN, /includeAmendments/);
  assert.match(CLIENT_SCREEN, /const \[includeAmendments, setIncludeAmendments\] = useState\(true\)/);
});

test("the panel renders nothing for an absent block and never shows an absent count as 0", () => {
  assert.match(PANEL, /if \(!block \|\| typeof block !== "object" \|\| typeof block\.included !== "boolean"\) return null/);
  assert.match(PANEL, /if \(added === null\) return null/);
  assert.doesNotMatch(PANEL, /counts\??\.amendments \?\? 0/);
});

test("a build made without amendments says so", () => {
  assert.match(PANEL, /if \(!block\.included\)/);
  assert.match(PANEL, /This file carries no amendment tables/);
});

test("what is owed is the server's: the panel holds no table, window or section rule", () => {
  for (const banned of [/november/i, /b2ba|cdnra|b2csa/, /filing_window|correction_window/]) {
    assert.doesNotMatch(PANEL, banned);
  }
});
