// POST-A-005 (migration 524): the accounting dashboard's "Unmatched Bank Txns" tile counted `bank_transactions` straight
// from the browser. Since 524 the database answers a person whose Banking access is blocked with ZERO ROWS, and a count
// over zero visible rows is 0, which reads as "every bank line is matched" to the one person who cannot see them. The
// count now comes from the server (GET /api/banking/unmatched-count, behind banking:read, which asks the person's access
// on every request); the page asks it only of someone its permission map says holds banking:read and shows a
// dash with "Not part of your access" to anyone else (lib/accounting/unmatchedBankTile.ts decides, with its own tests). This file pins the page
// to that module: the rule, not one spelling of it.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (p: string) => fs.readFileSync(path.join(WEB, p), "utf8");
const PAGE = "app/clients/[id]/accounting/page.tsx";

/** Source with comments removed, so a sentence explaining the old fault is not read as the fault. */
const code = (src: string) => src.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");

test("the dashboard no longer reads bank_transactions from the browser at all", () => {
  const src = code(read(PAGE));
  assert.doesNotMatch(src, /\.from\(\s*"bank_transactions"\s*\)/,
    "the dashboard counts bank_transactions over PostgREST again: a blocked person's count would be a zero");
});

test("the server's count is asked only after the permission decision", () => {
  const src = code(read(PAGE));
  const calls = [...src.matchAll(/api\.banking\.unmatchedCount\(/g)];
  assert.equal(calls.length, 1, "the dashboard asks for the unmatched count in more places than the one guarded effect");
  const at = calls[0].index!;
  const effectStart = src.lastIndexOf("useEffect(", at);
  assert.ok(effectStart >= 0, "the request is not inside an effect");
  const before = src.slice(effectStart, at);
  assert.match(before, /bankDecision === "wait"/, "the effect does not wait for the permission map");
  assert.match(before, /bankDecision === "not_allowed"/, "the effect does not stop for a person without banking:read");
  // the decision comes from the resolved flag and the banking:read pair, through the one module
  assert.match(src, /bankCountDecision\(\s*permissionsResolved\s*,\s*can\("banking",\s*"read"\)\s*\)/,
    "the decision is not made from the resolved permission map and banking:read");
});

test("a count the server did not give is never turned into a zero", () => {
  const src = code(read(PAGE));
  assert.doesNotMatch(src, /unmatched\.count\s*\?\?\s*0/, "a missing count is read as 0 again");
  assert.doesNotMatch(src, /unmatched_bank/, "the dashboard keeps a number for unmatched bank lines outside the tile's reading");
  assert.match(src, /readingFromAnswer\(res\)/, "the finished request is not turned into a reading by the module");
  // a thrown request (a refusal, a timeout) is unknown too
  assert.match(src, /kind: "failed"/, "a failed request is not turned into the unknown reading");
});

test("the tile prints what the module says and does not open the Bank screen for someone who cannot", () => {
  const src = code(read(PAGE));
  assert.match(src, /const bankTile = unmatchedBankTile\(bankReading\)/);
  assert.match(src, /value=\{bankTile\.value\}/);
  assert.match(src, /note=\{bankTile\.note\}/);
  assert.match(src, /bankTile\.opensBank\s*\?/, "the tile opens the Bank screen whatever the person may read");
});

test("a card with no action is a plain card, not a button that does nothing", () => {
  const src = code(read(PAGE));
  const at = src.indexOf("function DashCard(");
  assert.ok(at >= 0, "DashCard is gone");
  const body = src.slice(at, src.indexOf("// ── Chart of Accounts", at));
  assert.match(body, /if \(!action\)/, "DashCard renders a button even when there is nothing to press");
  assert.match(body, /<div className=\{`rounded-xl border p-4 text-left \$\{colors/, "the action-less card is not the plain div");
});
