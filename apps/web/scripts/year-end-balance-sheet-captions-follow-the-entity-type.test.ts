// The year-end Balance Sheet's Equity/Liabilities heading and its capital
// line follow the client's own entity type instead of always printing the
// corporate "Shareholders' Funds" / "Share Capital" captions
// (apex-payroll-yearend-13).
//
// Run with:
//   node --experimental-strip-types --test \
//     scripts/year-end-balance-sheet-captions-follow-the-entity-type.test.ts
//
// WHAT WAS WRONG
//     `usesScheduleIII(entity.entityType)` was imported and used ONLY to
//     switch the page's footnote sentence — the Equity/Liabilities group
//     handed to mapBSGroups() was always the hardcoded, corporate
//     EQUITY_LIABILITY_GROUPS constant. So a Proprietorship's real capital
//     balance rendered under "Shareholders' Funds" / "Share Capital", a
//     caption that presupposes shares the client never issued.
//
// THE FIX
//     `equityLiabilityGroupsFor(entityType)` swaps the first group's heading
//     and its "share_capital" line's label for the entity's own caption
//     before mapBSGroups() ever runs — Proprietorship -> "Proprietor's
//     Capital" / "Capital Account", Partnership and LLP -> "Partners'
//     Capital" — and falls back to the existing corporate wording otherwise
//     (Company, and the entity types this finding did not name).
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const FILE = "app/clients/[id]/year-end/[engagementId]/financial-statements/_page.tsx";

function read(): string {
  return fs.readFileSync(path.join(WEB, FILE), "utf8");
}

function stripped(): string {
  return stripComments(read());
}

test("a caption map exists naming the three entity types the finding named", () => {
  const src = stripped();
  assert.match(src, /"proprietorship": \{ heading: "Proprietor's Capital", line: "Capital Account" \}/);
  assert.match(src, /"partnership": \{ heading: "Partners' Capital", line: "Capital Account" \}/);
  assert.match(src, /"llp": \{ heading: "Partners' Capital", line: "Capital Account" \}/);
});

test("equityLiabilityGroupsFor only swaps labels, never the line codes", () => {
  const m = /function equityLiabilityGroupsFor\([\s\S]*?\n\}\n/.exec(stripped());
  assert.ok(m, "equityLiabilityGroupsFor not found");
  const body = m[0];
  assert.match(body, /code === "share_capital" \? \[code, caption\.line\] : \[code, label\]/);
  assert.match(body, /return EQUITY_LIABILITY_GROUPS;/,
    "an entity with no mapping must fall back to the existing corporate captions");
});

test("the Balance Sheet is built from equityLiabilityGroupsFor, not the bare corporate constant", () => {
  const src = stripped();
  assert.match(
    src,
    /const bs = mapBSGroups\(equityLiabilityGroupsFor\(entity\.entityType\),/,
  );
  // The corporate constant must still exist (it is the fallback and Company's
  // own captions), but must no longer be handed to mapBSGroups directly for
  // the equity/liabilities side.
  assert.doesNotMatch(src, /mapBSGroups\(EQUITY_LIABILITY_GROUPS,/);
});

test("usesScheduleIII is still used for the footnote — this fix is additive", () => {
  const src = stripped();
  assert.match(src, /usesScheduleIII\(entity\.entityType\)/);
});

// ── the actual mapping, run rather than pattern-matched ──────────────────────

/** Everything equityLiabilityGroupsFor closes over, concatenated as source
 *  and evaluated with `new Function` — the same technique
 *  a-template-preview-strips-its-markup.test.ts uses, and for the same
 *  reason: this runs the function's OWN extracted body, not a re-typed copy
 *  of its logic that could silently drift from the real one. */
function buildEquityLiabilityGroupsFor(): (entityType: string | null) => unknown {
  const src = stripped();
  const grab = (re: RegExp, label: string) => {
    const m = re.exec(src);
    assert.ok(m, `${label} not found`);
    return m[0];
  };
  // `new Function` runs as plain JS — TypeScript's OWN type annotations (on
  // the const declarations and on each function's parameter/return types)
  // are not valid there, so they are stripped from the exact, known-current
  // signatures before evaluating. This is a TEST-ONLY concession: the page
  // itself is never run through anything but tsc/Next, where the types stay.
  const groups = grab(/const EQUITY_LIABILITY_GROUPS: [\s\S]*?\n\];\n/, "EQUITY_LIABILITY_GROUPS")
    .replace(/^const EQUITY_LIABILITY_GROUPS: [^\n]*= \[/, "const EQUITY_LIABILITY_GROUPS = [");
  const key = grab(/function entityCaptionKey\([\s\S]*?\n\}\n/, "entityCaptionKey")
    .replace(/^function entityCaptionKey\([^)]*\): string \{/, "function entityCaptionKey(entityType) {");
  const captions = grab(
    /const CAPITAL_CAPTION_BY_ENTITY: [\s\S]*?\n\};\n/, "CAPITAL_CAPTION_BY_ENTITY")
    .replace(/^const CAPITAL_CAPTION_BY_ENTITY: [^\n]*= \{/, "const CAPITAL_CAPTION_BY_ENTITY = {");
  const fn = grab(/function equityLiabilityGroupsFor\([\s\S]*?\n\}\n/, "equityLiabilityGroupsFor")
    .replace(
      "function equityLiabilityGroupsFor(\n"
      + "  entityType: string | null | undefined,\n"
      + "): { label: string; lines: [string, string][] }[] {",
      "function equityLiabilityGroupsFor(entityType) {");
  const body = `${groups}\n${key}\n${captions}\n${fn}\nreturn equityLiabilityGroupsFor(entityType);`;
  // eslint-disable-next-line no-new-func
  return new Function("entityType", body) as (entityType: string | null) => unknown;
}

test("Proprietorship gets its own heading and capital-line label", () => {
  const fn = buildEquityLiabilityGroupsFor();
  const groups = fn("Proprietorship") as { label: string; lines: [string, string][] }[];
  assert.equal(groups[0].label, "Proprietor's Capital");
  assert.deepEqual(groups[0].lines[0], ["share_capital", "Capital Account"]);
  // The line CODE — which ledger figure fills the row — must be untouched.
  assert.equal(groups[0].lines[0][0], "share_capital");
  // Everything else in the group (Reserves and Surplus) is unchanged.
  assert.deepEqual(groups[0].lines[1], ["reserves_and_surplus", "Reserves and Surplus"]);
  // The other groups (Non-Current/Current Liabilities) pass through untouched.
  assert.equal(groups[1].label, "Non-Current Liabilities");
  assert.equal(groups[2].label, "Current Liabilities");
});

test("Partnership and LLP both get 'Partners' Capital'", () => {
  const fn = buildEquityLiabilityGroupsFor();
  for (const entityType of ["Partnership", "LLP"]) {
    const groups = fn(entityType) as { label: string; lines: [string, string][] }[];
    assert.equal(groups[0].label, "Partners' Capital", entityType);
    assert.deepEqual(groups[0].lines[0], ["share_capital", "Capital Account"], entityType);
  }
});

test("Private Limited keeps the original corporate captions", () => {
  const fn = buildEquityLiabilityGroupsFor();
  const groups = fn("Private Limited") as { label: string; lines: [string, string][] }[];
  assert.equal(groups[0].label, "Shareholders' Funds");
  assert.deepEqual(groups[0].lines[0], ["share_capital", "Share Capital"]);
});

test("an entity type outside the three named ones also falls back to the corporate captions", () => {
  const fn = buildEquityLiabilityGroupsFor();
  for (const entityType of ["Trust", "Society", "Individual", null]) {
    const groups = fn(entityType) as { label: string; lines: [string, string][] }[];
    assert.equal(groups[0].label, "Shareholders' Funds", String(entityType));
  }
});

test("the match is case- and spacing-insensitive, like lib/entityObligations.ts's own key()", () => {
  const fn = buildEquityLiabilityGroupsFor();
  const groups = fn("  PROPRIETORSHIP  ") as { label: string; lines: [string, string][] }[];
  assert.equal(groups[0].label, "Proprietor's Capital");
});
