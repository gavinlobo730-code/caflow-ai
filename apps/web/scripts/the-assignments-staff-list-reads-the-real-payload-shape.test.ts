// /team/assignments read the wrong key off GET /api/team and never checked
// whether the call had succeeded, so the staff list was permanently empty
// however many staff the firm had.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-assignments-staff-list-reads-the-real-payload-shape.test.ts
//
// WHAT WAS WRONG (sweep-team-hub-06)
//     routers/team.py::list_team answers
//       api_response(True, {"team": workload, "total": len(workload)})
//     — there is no `members` key. app/team/assignments/page.tsx read
//       Array.isArray(t.data) ? t.data : (t.data?.members ?? [])
//     which is always `[]` against that payload, and never looked at
//     `t.success` either — a refusal (this codebase answers some as HTTP 200
//     with `{success: false}`) would have looked identical to an empty firm.
//
// THE FIX
//     The page now reads `objectOrNull(t.data)?.team` through `arrayOrEmpty`
//     (lib/api/shape.ts, the same guard every other screen in this sweep was
//     fixed to use) and throws when `t.success` is false.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");

function read(rel: string): string {
  return stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
}

const PAGE = "app/team/assignments/page.tsx";

test("the staff list is read off the team key GET /api/team actually answers", () => {
  const src = read(PAGE);
  assert.match(src, /objectOrNull<\{\s*team:\s*unknown\s*\}>\(t\.data\)\?\.team/);
  assert.doesNotMatch(src, /t\.data\?\.members/);
});

test("the payload is narrowed through arrayOrEmpty, not trusted as-is", () => {
  const src = read(PAGE);
  assert.match(src, /arrayOrEmpty<Member>\(/);
  assert.match(src, /from "@\/lib\/api\/shape"/);
});

test("a refused response (success: false) is not read as an empty staff list", () => {
  const src = read(PAGE);
  assert.match(src, /if \(!t\.success\)/);
});
