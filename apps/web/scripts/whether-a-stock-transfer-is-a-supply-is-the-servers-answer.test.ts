/**
 * INV-03a — the browser renders where the stock is and decides none of it.
 *
 * Three answers on this screen are the server's, and one of them is a decision
 * about a statutory document:
 *
 *   IS A TRANSFER A SUPPLY. CGST s.25(4) makes two registrations of one entity
 *   distinct persons and Schedule I paragraph 2 treats a movement between them
 *   as a supply even without consideration — so it needs a tax invoice.
 *   Comparing the two GSTINs in the browser would be a second implementation
 *   of that, on the question of whether a document is owed.
 *
 *   WHICH EXPIRY BUCKET a lot is in, including the boundary that is easy to
 *   get backwards: stock is still good ON its expiry date. A day's error there
 *   writes off sound stock and reverses §17(5)(h) credit that is not yet due.
 *
 *   WHAT "UNALLOCATED" MEANS. Nothing was back-filled onto the movements that
 *   predate this feature, and the sentence explaining that is the server's.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PANEL = path.join(WEB, "components/inventory/LocationsAndBatches.tsx");
const PAGE = path.join(WEB, "app/clients/[id]/inventory/page.tsx");

function withoutComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .split("\n")
    .map((l) => l.replace(/(^|\s)\/\/.*$/, "$1"))
    .join("\n");
}

const raw = fs.readFileSync(PANEL, "utf8");
const code = withoutComments(raw);

test("whether a stock transfer is a supply is the server's answer", async (t) => {
  await t.test("never compares two GSTINs", () => {
    assert.ok(!/gstin\s*===|gstin\s*!==|gstin\s*==/i.test(code),
      "the browser is deciding whether two godowns are distinct persons");
    assert.ok(!/state_code\s*===|state_code\s*!==/.test(code),
      "and it is not doing it by state either — s.25(2) allows two registrations in one state");
    assert.match(code, /transfer-preview/);
    assert.match(code, /decision\.reason/);
  });

  await t.test("the supply answer is a TRI-state in the render", () => {
    // True, False, and null where a registration is not recorded. Collapsing
    // the third into either is the guess the whole module refuses.
    assert.match(code, /decision\.is_supply === true/);
    assert.match(code, /decision\.is_supply === false/);
  });

  await t.test("names no statute", () => {
    for (const p of [/Schedule I/, /25\(4\)/, /Rule 28/, /distinct persons/]) {
      assert.ok(!p.test(code), `${p} is written into the screen`);
    }
  });

  await t.test("buckets no expiry date", () => {
    assert.ok(!/new Date\(/.test(code), "the browser is bucketing by date");
    assert.ok(!/30\s*\*\s*24|days_to_expiry\s*[<>]/.test(code),
      "the browser is deciding what 'within 30 days' means");
    assert.match(code, /expiry\.bucket_order\.map/);
    assert.match(code, /expiry\.bucket_labels\[/);
    // AND NO BUCKET LABEL IS SPELLED HERE. The pair above passes while one
    // hardcoded label sits beside them, because the other call site keeps them
    // satisfied — which is what a negative control found.
    for (const label of ["Already expired", "Expires within 30", "Expires within 90",
                         "Expires later", "No expiry date recorded"]) {
      assert.ok(!code.includes(label), `the label "${label}" is spelled in the browser`);
    }
    // The bucket NAMES appear only as the colour switch, which is a
    // presentation choice made FROM the server's answer rather than instead
    // of it — and the label rendered is still the server's.
    assert.match(code, /expiry\.bucket_labels\[r\.bucket\]/);
  });

  await t.test("renders the server's sentences rather than its own", () => {
    assert.match(code, /unallocatedMeans/);
    assert.match(code, /expiry\.notes\.map/);
    assert.ok(!/back-filled/.test(code), "a server sentence is written here");
    assert.ok(!/17\(5\)\(h\)/.test(code), "a statutory sentence is written here");
  });

  await t.test("a godown with no registration reads as unrecorded", () => {
    // Not blank and not assumed: whether a transfer out of it is a supply
    // cannot be determined without it.
    assert.match(code, /Not recorded/);
  });

  await t.test("is mounted on the inventory screen", () => {
    const page = withoutComments(fs.readFileSync(PAGE, "utf8"));
    assert.match(page, /<LocationsAndBatches[\s/>]/);
  });

  await t.test("the comment strip does not make the scan vacuous", () => {
    assert.ok(code.length > raw.length / 2, "too much of the file was stripped");
    assert.match(code, /export function LocationsAndBatches/);
  });
});
