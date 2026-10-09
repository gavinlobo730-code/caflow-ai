// The access drawer tells a Partner what a block reaches, in the server's words
// (POST-A-005).
//
// Run with:
//   node --experimental-strip-types --test scripts/the-access-drawer-says-what-a-denial-reaches.test.ts
//
// THE FAULT. The per-person grid is enforced by the API and by the write
// policies of a few tables; no table's READ policy asks it, and several screens
// read tables straight from the browser. A Partner who unticked Payroll for a
// Manager had no way to learn that the Manager's own sign-in could still read
// the data, and the drawer — the one place that makes the promise — said
// nothing about its limits.
//
// WHERE THE RULE LIVES. The sentence is a claim about the database's policies,
// so it is SERVED (`GET /api/identity/permission-vocabulary` → `notice`) from
// the module the real-Postgres guard keeps true, and the guard that the browser
// holds NO COPY of it is written on the Python side
// (`tests/test_a_denial_says_what_it_reaches.py`): a copy-detector written here
// would compare the browser with a sentence it had to copy in to compare. This
// file holds the wiring, which only this side can read:
//
//   * the API client types the field, and as OPTIONAL — a frontend is live
//     before the backend that serves a new field, and an old backend serves
//     none, so a required type would be a lie the compiler then enforces;
//   * the drawer puts the response's field through `denialNotice` (behaviour
//     tested in lib/team/denialNotice.test.ts) and renders the result only
//     when there is one, so "not told" is a screen with nothing extra on it and
//     not a screen with a made-up sentence;
//   * the drawer fabricates nothing in the notice's place: no fallback string
//     is assigned to the notice state.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");

test("the API client types the notice, and as optional", () => {
  const api = read("lib/api/index.ts");
  const at = api.indexOf("permissionVocabulary: () =>");
  assert.ok(at > 0, "api.identity.permissionVocabulary is gone");
  // the response type, up to the URL it is requested from
  const type = api.slice(at, api.indexOf('"/api/identity/permission-vocabulary"', at));
  assert.match(type, /notice\?:\s*string/,
    "the vocabulary response must declare `notice?: string` — optional, because a " +
    "frontend can be live before the backend that serves the field");
});

test("the drawer shows the notice only when the server sent one", () => {
  const drawer = stripComments(read("components/team/MemberAccessDrawer.tsx"));
  assert.match(drawer, /import \{ denialNotice \} from "@\/lib\/team\/denialNotice"/);
  assert.match(drawer, /setNotice\(denialNotice\(vocab\.data\.notice\)\)/,
    "the notice must be read off the vocabulary response and checked before it is kept");
  assert.match(drawer, /\{notice && \(/, "the notice is rendered whether or not there is one");
  assert.match(drawer, /\{notice\}/, "the drawer must render the received value");
  assert.match(drawer, /useState<string \| null>\(null\)/,
    "an unknown notice starts as null — not told — and not as a sentence");
});

test("nothing but the helper's answer is ever assigned to the notice", () => {
  const drawer = stripComments(read("components/team/MemberAccessDrawer.tsx"));
  const assigned = [...drawer.matchAll(/setNotice\(([^;]*)\);/g)].map((m) => m[1].trim());
  assert.ok(assigned.length > 0, "the drawer never sets the notice");
  for (const arg of assigned) {
    assert.match(arg, /^denialNotice\(.+\)$/,
      `setNotice(${arg}) puts something other than the server's sentence on the screen`);
  }
});
