// A firm-level tracker says which list it shows and where the full one is (POST-A-208).
//
// WHAT WAS WRONG
//   The product keeps obligations in two stores. `compliance_records` is the obligation store: the Deadlines screen, the hub's Compliance
//   tile, the executive dashboard, the client health score, the risk engine and the assistant read it and agree on what is overdue.
//   The firm-level /gst and /income-tax trackers read `compliance_calendar`, a different table with a different population (it holds no
//   rows on the seeded demo firm), so the two screens showed none of the obligations the rest of the product shows, with nothing to say
//   why. Both trackers lock the period on Mark Filed, which is why they keep reading the table that door writes (the decision of
//   2-11-2026; moving them is a change to how a period is locked and is not made here).
//
// WHAT THIS HOLDS
//   * each tracker carries one sentence, in the page and not in a tooltip, that says it lists the returns recorded in the filing
//     calendar, that this is not the full list of what is due, and links to Deadlines, which is;
//   * the link is to the route the app really has.
//
// Run with: node --experimental-strip-types --test scripts/a-firm-level-tracker-says-what-list-it-shows.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

for (const [page, what] of [["app/gst/page.tsx", "GST returns"], ["app/income-tax/page.tsx", "income-tax returns"]] as const) {
  test(`${page} says which list it shows and where the full one is`, () => {
    const src = read(page);
    assert.ok(src.includes('data-testid="tracker-source-note"'), `${page} carries no source note`);
    const note = src.slice(src.indexOf('data-testid="tracker-source-note"'));
    const sentence = note.slice(0, note.indexOf("</p>")).replace(/\s+/g, " ");
    assert.ok(sentence.includes(`This tracker lists the ${what} recorded in the filing calendar. It is not the full list of what is due:`), sentence);
    assert.ok(/<Link href="\/deadlines"[^>]*>Deadlines<\/Link> lists every obligation\./.test(sentence), "the sentence does not point at Deadlines");
  });
}

test("the route the note points at exists", () => {
  assert.ok(fs.existsSync(path.join(WEB, "app/deadlines/page.tsx")), "app/deadlines/page.tsx is gone");
});
