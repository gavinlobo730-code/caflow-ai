// A handful of small Year End engagement cosmetics, all found on the same
// walkthrough: a raw ISO date where every other screen formats one, an emoji
// on product UI, and two clickable buttons coloured as though they were
// disabled controls.
//
// Run with: node --experimental-strip-types --test scripts/year-end-cosmetics.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const DIR = "app/clients/[id]/year-end";

function read(rel: string): string {
  return stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
}

test("the engagement list formats Created through the shared date helper", () => {
  // `new Date(x).toLocaleDateString("en-IN")` with no options renders D/M/YYYY
  // with NEITHER field zero-padded — "Created 15/9/2026" — while every other
  // date on this list of screens goes through `formatDate` (day: "2-digit",
  // month: "short", year: "numeric"), which is what makes "15 Sep 2026"
  // consistent regardless of which month or day it lands on.
  const src = read(`${DIR}/page.tsx`);
  assert.match(src, /import \{ formatDate \} from "@\/lib\/services\/formatting";/,
    "the engagement list no longer imports the shared date formatter");
  assert.match(src, /Created \{formatDate\(eng\.created_at\)\}/,
    "the Created date is not run through formatDate");
  assert.ok(!src.includes('new Date(eng.created_at).toLocaleDateString("en-IN")'),
    "the old unpadded, bare toLocaleDateString call is still there");
});

test("the Dashboard status card carries no emoji", () => {
  const src = fs.readFileSync(
    path.join(WEB, `${DIR}/[engagementId]/dashboard/_page.tsx`), "utf8");
  // eslint-disable-next-line no-control-regex -- deliberately outside the BMP
  const emoji = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u;
  const hit = [...src].find((ch) => emoji.test(ch));
  assert.equal(hit, undefined,
    `found ${JSON.stringify(hit)} — CLAUDE.md: no emojis on product UI unless a ` +
    "user explicitly asks, and nobody asked the year-end dashboard for one");
  // Replaced with a named icon per status, not silently dropped.
  const code = stripComments(src);
  assert.match(code, /STATUS_ICON: Record<EngagementStatus, LucideIcon>/);
  assert.match(code, /<StatusIcon /, "the status card renders no icon at all now");
});

test("the checklist's '+ Add note' and 'N/A' are not coloured like disabled controls", () => {
  // `ps.disabled` (#CBD5E1) is deliberately left failing WCAG 1.4.3 —
  // tailwind.config.ts's own comment says so — because it is reserved for a
  // control that IS inactive. Both of these are ordinary buttons a CA clicks
  // constantly while working a checklist, so reaching for the token whose
  // whole point is to read as inert was the defect, not merely the shade.
  const src = read(`${DIR}/[engagementId]/checklist/_page.tsx`);
  assert.ok(!src.includes('className="text-3xs text-ps-disabled hover:text-ps-hint mt-1"'),
    "'+ Add note' still uses the disabled-control colour");
  assert.ok(!src.includes('className="text-3xs text-ps-disabled hover:text-ps-hint flex-shrink-0 disabled:opacity-50"'),
    "the 'Mark N/A' button still uses the disabled-control colour");
  assert.ok(src.includes('className="text-3xs text-ps-hint hover:text-ps-label mt-1"'),
    "'+ Add note' should read as a hint, darkening to label on hover");
  assert.ok(src.includes('className="text-3xs text-ps-hint hover:text-ps-label flex-shrink-0 disabled:opacity-50"'),
    "the 'Mark N/A' button should read as a hint, darkening to label on hover");
});
