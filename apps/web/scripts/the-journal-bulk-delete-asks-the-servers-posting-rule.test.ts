// POST-A-462. Where a firm has a Partner approve every manual journal, the server refuses a member who may not approve each
// POSTED entry they try to delete (services/journal_approval_rule.assert_may_change_posted). The journal list's bulk Delete
// offered them the whole selection anyway, and the server refused it one entry at a time. It now reads the server's own answer
// for the person (`may_post` from GET /api/accounting/journal-approval) and acts on drafts only when that answer is false.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { deleteActsOn, deleteAppliesTo, POSTED_LEFT_ALONE } from "../lib/accounting/journalDeleteScope.ts";

const WEB = join(import.meta.dirname, "..");
const read = (...p: string[]) => readFileSync(join(WEB, ...p), "utf8");
const draft = { is_posted: false };
const posted = { is_posted: true };

test("a member the server says may not post is offered drafts only", () => {
  const acts = deleteActsOn(false);
  assert.equal(acts(draft), true);
  assert.equal(acts(posted), false);
  assert.equal(deleteAppliesTo(false, [posted, posted]), false, "a selection of posted entries alone offers no Delete");
  assert.equal(deleteAppliesTo(false, [posted, draft]), true);
});

test("someone who may post, and an answer not yet read, are offered everything and the server decides", () => {
  for (const answer of [true, null]) {
    assert.equal(deleteActsOn(answer)(posted), true);
    assert.equal(deleteAppliesTo(answer, [posted]), true);
  }
});

test("the confirm says posted entries are left alone and why", () => {
  assert.match(POSTED_LEFT_ALONE, /approved before it posts/);
  assert.match(POSTED_LEFT_ALONE, /skipped/);
});

test("the journal list's Delete reads the server's answer and holds no copy of the rule", () => {
  const src = read("app", "clients", "[id]", "accounting", "page.tsx");
  const start = src.indexOf("function JournalList(");
  const end = src.indexOf("\nfunction ", start + 1);
  const list = src.slice(start, end);
  assert.match(list, /const deleteRule = useJournalApprovalRule\(\);/);
  const discard = list.slice(list.indexOf('id: "discard"'), list.indexOf('id: "reverse-posted"'));
  assert.match(discard, /appliesTo: \(rows\) => deleteAppliesTo\(deleteRule\.mayPost, rows\)/);
  assert.match(discard, /deleteActsOn\(deleteRule\.mayPost\)/);
  assert.match(discard, /deleteRule\.mayPost === false \? POSTED_LEFT_ALONE/);
  // the firm's setting itself is never read here: that would be a second copy of the rule the server applies
  assert.doesNotMatch(list, /approval_required/);
  assert.doesNotMatch(discard, /\(\) => true,/);
  // the scope module decides nothing but what the server said
  const scope = read("lib", "accounting", "journalDeleteScope.ts");
  assert.doesNotMatch(scope.replace(/\/\*[\s\S]*?\*\//g, ""), /approval_required|role|can\(/);
});
