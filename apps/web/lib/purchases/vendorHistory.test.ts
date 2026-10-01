/**
 * The bill editor shows what a supplier's earlier bills propose, and applies
 * NOTHING until the CA clicks (ai-23).
 *
 * Two kinds of test. The first reads the payload the way the editor will, and
 * proves a payload that is not the expected shape is NO DATA rather than a crash
 * (`lib/api/shape.ts`'s rule, and the reason this file parses at all). The
 * second holds the editor to the rule that is the point of the feature: the only
 * place a history-derived change reaches a line is an `onClick`.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import {
  accountPatch, chipsForLine, distinctHsns, itcPatch, parseVendorHistory,
  suggestionsFor, type HistorySuggestion,
} from "./vendorHistory.ts";

const RENT = {
  value: "acc-rent", label: "5100 · Rent", times_seen: 3, total_seen: 3, share_bps: 10000,
  last_seen: "2026-03-01", basis: "hsn", scope: "9972", reason: null,
  sentence: "Coded this way 3 of 3 times, for HSN/SAC 9972", alternatives: [],
};
const BLOCKED = {
  value: false, label: "ITC blocked (§17(5))", times_seen: 3, total_seen: 4, share_bps: 7500,
  last_seen: "2026-03-01", basis: "supplier", scope: "", reason: "motor_vehicles",
  sentence: "Coded this way 3 of 4 times, across this supplier's earlier bills",
  alternatives: [{ value: true, label: "ITC eligible", times: 1, last_seen: "2026-01-01" }],
};
const served = (over: Record<string, unknown> = {}) => ({
  checked: true, bills_considered: 3, gaps: [],
  vendor: { expense_account: { ...RENT, basis: "supplier", scope: "" }, itc: BLOCKED },
  by_hsn: { "9972": { expense_account: RENT, itc: null } },
  tds: null,
  ...over,
});

// ── reading the payload ──────────────────────────────────────────────────────

test("the served answer is read into suggestions with their evidence", () => {
  const h = parseVendorHistory(served())!;
  const s = suggestionsFor(h, "9972");
  assert.equal(s.expense_account?.value, "acc-rent");
  assert.equal(s.expense_account?.times_seen, 3);
  assert.equal(s.expense_account?.sentence, "Coded this way 3 of 3 times, for HSN/SAC 9972");
});

test("a payload that is not an object the server marked checked is NO DATA", () => {
  for (const bad of [null, undefined, [], "oops", 7, {}, { checked: false }, { checked: "yes" }]) {
    assert.equal(parseVendorHistory(bad), null, JSON.stringify(bad));
  }
});

test("a half-formed payload degrades field by field rather than throwing", () => {
  const h = parseVendorHistory({ checked: true })!;
  assert.deepEqual(h.vendor, { expense_account: null, itc: null });
  assert.deepEqual(h.byHsn, {});
  assert.equal(h.tds, null);
  assert.deepEqual(h.gaps, []);
  // `{}` passes objectOrNull and its lists are absent: the case lib/api/shape.ts warns about.
  const odd = parseVendorHistory(served({
    by_hsn: { "9972": { expense_account: { ...RENT, alternatives: undefined } } },
    gaps: "not a list",
  }))!;
  assert.deepEqual(odd.byHsn["9972"].expense_account?.alternatives, []);
  assert.deepEqual(odd.gaps, []);
});

test("a suggestion that cannot say how often it happened is not evidence and is dropped", () => {
  for (const key of ["times_seen", "total_seen", "sentence", "value"]) {
    const broken = { ...RENT, [key]: undefined };
    const h = parseVendorHistory(served({ by_hsn: { "9972": { expense_account: broken, itc: null } } }))!;
    assert.equal(h.byHsn["9972"].expense_account, null, key);
  }
});

test("the TDS notice carries only the server's sentence and section", () => {
  const h = parseVendorHistory(served({
    tds: { section: "194J", supplier_record_section: null, sentence: "Earlier bills…" },
  }))!;
  assert.equal(h.tds?.section, "194J");
  assert.equal(h.tds?.supplier_record_section, null);
  assert.equal(parseVendorHistory(served({ tds: { section: "194J" } }))!.tds, null,
    "a notice with no sentence is not a notice");
});

// ── what is shown beside a line ──────────────────────────────────────────────

const line = (over = {}) => ({ hsn_sac: "9972", expense_account_id: "", itc_eligible: true, ...over });

test("the server's answer for the line's own HSN is what is shown", () => {
  const h = parseVendorHistory(served())!;
  assert.equal(chipsForLine(h, line()).expense_account?.value, "acc-rent");
});

test("a line with no HSN gets the supplier-level answer, and an HSN nobody asked about gets none", () => {
  const h = parseVendorHistory(served())!;
  assert.equal(chipsForLine(h, line({ hsn_sac: "" })).expense_account?.basis, "supplier");
  assert.equal(chipsForLine(h, line({ hsn_sac: "  " })).expense_account?.basis, "supplier");
  assert.equal(chipsForLine(h, line({ hsn_sac: "8888" })).expense_account, null,
    "the supplier's answer would be a guess standing in for evidence that was never looked up");
});

test("the account chip disappears once the CA has chosen an account", () => {
  const h = parseVendorHistory(served())!;
  assert.equal(chipsForLine(h, line({ expense_account_id: "acc-fuel" })).expense_account, null);
  assert.equal(chipsForLine(h, line({ expense_account_id: "acc-rent" })).expense_account, null);
});

test("the ITC chip shows only for a line still marked eligible, and only when the history is BLOCKED", () => {
  const h = parseVendorHistory(served())!;
  assert.equal(chipsForLine(h, line({ hsn_sac: "" })).itc?.value, false);
  assert.equal(chipsForLine(h, line({ hsn_sac: "", itc_eligible: false })).itc, null);
  assert.equal(chipsForLine(h, line()).itc, null, "this HSN's own ITC history is eligible, which is not shown");
});

test("no history means no chips and no crash", () => {
  assert.deepEqual(chipsForLine(null, line()), { expense_account: null, itc: null });
});

test("the codes asked about are distinct, trimmed, non-empty and sorted", () => {
  assert.deepEqual(distinctHsns([
    { hsn_sac: " 9983 " }, { hsn_sac: "9972" }, { hsn_sac: "" }, { hsn_sac: "9983" }, { hsn_sac: "  " },
  ]), ["9972", "9983"]);
});

// ── what a click does ────────────────────────────────────────────────────────

test("a click on the account chip sets the account and nothing else", () => {
  const s = parseVendorHistory(served())!.byHsn["9972"].expense_account as HistorySuggestion;
  assert.deepEqual(accountPatch(s), { expense_account_id: "acc-rent" });
});

test("a click on the ITC chip marks the line blocked with the clause the earlier lines carried", () => {
  const s = parseVendorHistory(served())!.vendor.itc as HistorySuggestion;
  assert.deepEqual(itcPatch(s), { itc_eligible: false, blocked_credit_reason: "motor_vehicles" });
});

test("a clause nobody recorded is left BLANK, so the §17(5) select stays flagged, never invented", () => {
  const s = { ...(parseVendorHistory(served())!.vendor.itc as HistorySuggestion), reason: null };
  assert.deepEqual(itcPatch(s), { itc_eligible: false, blocked_credit_reason: "" });
});

test("an ITC suggestion is not an account and cannot be applied as one", () => {
  const s = parseVendorHistory(served())!.vendor.itc as HistorySuggestion;
  assert.equal(accountPatch(s), null);
});

test("building a patch changes nothing it was given", () => {
  const s = parseVendorHistory(served())!.byHsn["9972"].expense_account as HistorySuggestion;
  const before = JSON.stringify(s);
  accountPatch(s); itcPatch(s);
  assert.equal(JSON.stringify(s), before);
});

// ── the rule: NOTHING IS APPLIED WITHOUT A CLICK ─────────────────────────────

const editor = readFileSync(
  join(import.meta.dirname, "../../components/purchases/PurchaseBillEditor.tsx"), "utf8");

/** Comments stripped first: a rule stated about SOURCE must not be satisfied, or
 *  broken, by prose describing it. */
function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").split("\n").map((l) => l.replace(/\/\/.*$/, "")).join("\n");
}
const src = code(editor);

test("the editor reaches a history patch only from an onClick handler", () => {
  const uses = [...src.matchAll(/\b(accountPatch|itcPatch)\s*\(/g)];
  assert.ok(uses.length >= 2, "the editor no longer uses the patch builders at all — vacuous");
  for (const m of uses) {
    const before = src.slice(Math.max(0, m.index! - 260), m.index!);
    // `const patch = s ? accountPatch(s) : null` BUILDS the change for the handler
    // below it; what must not happen is a call that feeds `setLine` / `setLines`
    // directly from an effect or from the extraction path.
    const inHandler = /onClick=\{[^}]*$/.test(before);
    const buildsForHandler = /const\s+patch\s*=\s*[^;]*$/.test(before);
    assert.ok(inHandler || buildsForHandler, `${m[0]} is called outside a click handler:\n${before.slice(-120)}`);
  }
});

test("the data handed to setLine on a history click is the builder's, in a click handler", () => {
  assert.match(src, /onClick=\{\(\) => setLine\(idx, patch\)\}/);
  assert.match(src, /onClick=\{\(\) => setLine\(idx, itcPatch\(s\)\)\}/);
});

test("neither the history effect nor the extraction path writes a line from a suggestion", () => {
  const effect = src.slice(src.indexOf("const historyKey"), src.indexOf("const validation = validateBillEditor"));
  assert.ok(effect.length > 100, "could not find the history effect");
  assert.doesNotMatch(effect, /setLines?\s*\(/, "the history effect must only set `history`");
  assert.doesNotMatch(effect, /Patch\s*\(/);

  // Comments are stripped, so the end marker is the next function, not its banner.
  const from = src.indexOf("async function handleExtract");
  const to = src.indexOf("async function save()");
  assert.ok(from > 0 && to > from, "could not bound handleExtract");
  const extract = src.slice(from, to);
  assert.ok(extract.length > 500, "could not find handleExtract");
  assert.match(extract, /expense_account_id:\s*""/, "extracted lines still arrive with a BLANK account");
  assert.doesNotMatch(extract, /history|Patch\s*\(|vendorHistory/i,
    "the extraction path must not consult the history at all");
});

test("the history is asked for on a new bill only", () => {
  assert.match(src, /const historyKey = isEdit \|\| !vendorId \? ""/);
});

test("the editor reads the history through the parser and not as raw payload fields", () => {
  assert.match(src, /setHistory\(res\.success \? parseVendorHistory\(res\.data\) : null\)/);
});
