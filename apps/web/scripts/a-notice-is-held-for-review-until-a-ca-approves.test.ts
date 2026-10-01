// A notice the model read is HELD for review, and the screen says so. Run with:
//   node --experimental-strip-types --test scripts/a-notice-is-held-for-review-until-a-ca-approves.test.ts
//
// WHAT WAS WRONG (ai-16)
//   The extractor created a high-priority task, a timeline event and a notification
//   for every partner before any CA had looked at what the model read, and the
//   screen's copy said only "CA must approve before action" — true of nothing the
//   server did. The Approve button awaited its POST and dropped the answer, so a
//   refusal looked like success.
//
// WHAT THIS HOLDS FROM THE SCREEN'S SIDE
//   The server decides (apps/api/tests/test_a_notice_reading_stages_and_a_ca_approves.py
//   is the rule); the screen must not CONTRADICT it. It must say that nothing is
//   created until approval, mark an unapproved row as pending review, and read the
//   approval's answer rather than assume it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const WEB = join(import.meta.dirname, "..");
const PAGE = "app/clients/[id]/compliance/page.tsx";

function code(rel: string): string {
  return readFileSync(join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

const raw = readFileSync(join(WEB, PAGE), "utf8");

test("the panel tells the CA that nothing is created or announced until they approve", () => {
  assert.match(raw, /no task is created and nobody is alerted until a CA approves/,
    "the copy must say what the server does, not only that a CA 'must approve'");
});

test("an unapproved row is marked pending review beside its Approve button", () => {
  const src = code(PAGE);
  assert.match(src, /Pending review/, "an unapproved notice reads like an approved one");
  assert.match(src, /CA Approve/);
});

test("approving reads the answer and shows the server's sentence on a refusal", () => {
  const src = code(PAGE);
  const at = src.indexOf("async function approveNotice");
  assert.ok(at > 0, "approveNotice is gone");
  const fn = src.slice(at, src.indexOf("\n  }\n", at));
  assert.match(fn, /const res = await apiFetch\(/, "the approval's answer is dropped again");
  assert.match(fn, /if \(!res\?\.success\)[\s\S]*?setApproveError\(/,
    "a refusal must be shown, not assumed away");
  assert.match(src, /role="alert"[^>]*>\{approveError\}/, "the error is never rendered");
});

test("the screen does not itself create a task or a notification from a notice", () => {
  const src = code(PAGE);
  const extract = src.slice(src.indexOf("async function extract()"), src.indexOf("async function approveNotice"));
  assert.doesNotMatch(extract, /\.from\("tasks"\)|\.from\("notifications"\)|\/api\/tasks/,
    "creating work from a reading is the server's job, and only at approval");
});
