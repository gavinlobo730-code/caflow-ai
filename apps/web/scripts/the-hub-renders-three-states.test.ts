// The hub's three states, held apart in the browser.
//
// `domain/hub/tiles.py` keeps them distinct in the payload and
// `tests/test_a_hub_tile_shows_what_is_outstanding.py` asserts they are three
// different dicts. This is the other end: a screen that collapsed them would
// make the backend's care pointless, and the collapse is the easy thing to
// write — `tile.signal ?? 0` is one character from correct-looking and turns
// "nobody can tell" into "nothing to do".
//
//   signal 0,    answerable       the finished state
//   signal null, NOT answerable   render the reason, never a number
//   signal null, answerable       this one tile could not be read
//
// AND A TILE WITH NO `href` IS NOT A LINK. Five modules have no firm-level
// screen (question G3) and one of the five, Fixed Assets, has a page that
// renders "this moved to the client workspace" — worse than a 404, because it
// looks like it works. The server answers `href: null`; the card must not
// become an anchor.
//
// Run with: node --experimental-strip-types --test scripts/the-hub-renders-three-states.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const HUB = path.join(WEB, "components/hub/Hub.tsx");
const SRC = stripComments(fs.readFileSync(HUB, "utf8"));

test("the hub component is where this guard thinks it is", () => {
  assert.ok(SRC.length > 1500, `Hub.tsx read as ${SRC.length} chars`);
  // `api.hub` and not `api.hub.get`: the call is written across two lines, so
  // the dotted spelling is not a contiguous string. Asserting the spelling
  // failed on correct code the first time this ran — the rule is that the hub
  // fetches through that namespace, not how the formatter broke the line.
  assert.ok(/\bapi\.hub\b/.test(SRC), "the hub no longer fetches from api.hub");
});

test("a null signal is never coerced to a number", () => {
  // The one-character mistake: `?? 0` or `|| 0` on the signal turns BOTH null
  // states into "nothing outstanding", which is the stub 2.2 is defined
  // against. Zero must only ever come from the server.
  for (const bad of ["signal ?? 0", "signal || 0", "signal ?? '0'", "Number(tile.signal)"]) {
    assert.ok(!SRC.includes(bad),
      `Hub.tsx coerces a null signal with \`${bad}\` — a tile nobody can ` +
      `compute would render as a finished one`);
  }
  // And the two null states are told apart by `answerable`, not by the signal.
  assert.ok(/answerable/.test(SRC), "the component ignores `answerable`");
  assert.ok(SRC.includes("no_signal_because"),
    "the reason a tile has no figure is never rendered");
});

test("a tile with no destination does not render as a link", () => {
  assert.match(
    SRC,
    /if \(!tile\.href\)[\s\S]{0,120}return <div/,
    "a tile with `href: null` must return a plain element — five modules have " +
      "no firm-level screen, and one of them is a tombstone that renders"
  );
});

test("the browser computes no figure of its own", () => {
  // The hub asks fifteen questions at two scopes. A figure derived here would
  // be a second authority on what "unfiled" means — the Schedule III caption
  // lesson, in a new place.
  for (const bad of [".from(\"", "supabase", "filter(", "reduce("]) {
    assert.ok(!SRC.includes(bad),
      `Hub.tsx contains \`${bad}\` — every figure comes from GET /api/hub, ` +
      `which is what stops the browser holding a second definition`);
  }
});

test("the payload is checked before it is treated as a list", () => {
  // CLAUDE.md's rule, and the defect this session found twice: the envelope
  // first (several routers answer a refusal as HTTP 200), then the field.
  assert.ok(SRC.includes("res?.success") || SRC.includes("res.success"),
    "the hub renders without checking the envelope");
  assert.ok(SRC.includes("arrayOrEmpty"),
    "the tiles array is assigned without arrayOrEmpty");
});

test("both hubs use the same component", () => {
  const firm = fs.readFileSync(path.join(WEB, "app/DashboardContent.tsx"), "utf8");
  const client = fs.readFileSync(path.join(WEB, "app/clients/[id]/overview/page.tsx"), "utf8");
  assert.ok(firm.includes("<Hub />"), "the firm dashboard does not render the hub");
  assert.match(client, /<Hub clientId=\{clientId\} \/>/,
    "the client overview does not render the hub at client scope");
  // One component, so the fifteen questions cannot diverge between scopes.
  for (const [name, src] of [["firm", firm], ["client", client]]) {
    assert.ok(src.includes('from "@/components/hub/Hub"'),
      `the ${name} hub imports Hub from somewhere else`);
  }
});

test("the money tiles do not print two rupee signs", () => {
  // The first draft of Hub.tsx wrote `₹${formatWhole(...)}`, and
  // `lib/money/format`'s formatters are `Intl.NumberFormat("en-IN", {style:
  // "currency"})` — they already carry the ₹. All three money tiles rendered
  // "₹₹4,23,517". Cheap to miss, immediately visible to a CA.
  assert.ok(!/[`'"]₹\$\{/.test(SRC) && !SRC.includes('"₹" +'),
    "Hub.tsx prefixes a ₹ onto a value from lib/money/format, which already " +
    "carries one — the tile will render ₹₹");
  // And it must not round: the browser holding a second rounding rule is what
  // `domain/money_text` and `lib/money/format` exist to prevent.
  for (const bad of ["Math.round(", "toFixed(", "/ 100"]) {
    assert.ok(!SRC.includes(bad),
      `Hub.tsx contains \`${bad}\` — money is formatted by lib/money/format, ` +
      `never converted or rounded here`);
  }
});
