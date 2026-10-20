// The client Health tab says when Calculate was refused (POST-A-289).
//
// The server does not store a score computed through a read that failed (every dimension counts as 100 when its own read fails, so
// the figure would be falsely healthy and would replace the last good one): the single-client Calculate route answers 503 and leaves
// the stored score alone, as the nightly run and the Recalculate button always have. A screen that treated that as "nothing to show"
// (`catch { /* non-fatal */ }`, and no line for `success: false`) would look like a Calculate that worked and found nothing new.
//
// Run with: node --experimental-strip-types --test scripts/the-client-health-tab-says-when-calculate-was-refused.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const PAGE = stripComments(fs.readFileSync(path.join(WEB, "app/clients/[id]/health/page.tsx"), "utf8"));

test("the Calculate handler says a refusal and a failed request, after the re-read that would clear the line", () => {
  const at = PAGE.indexOf("async function handleRecalculate()");
  assert.ok(at > 0, "handleRecalculate is missing");
  const body = PAGE.slice(at, PAGE.indexOf("async function handleAddOverride()"));
  assert.ok(/if \(!json\.success\) setError\(json\.error \?\? json\.detail \?\? /.test(body), "a refused Calculate (success: false, or FastAPI's detail) is not said");
  assert.ok(body.indexOf("await loadAll()") < body.indexOf("if (!json.success) setError("), "the line is set before the re-read, which clears it");
  assert.ok(!/catch \{\s*\/\*|catch \{\s*\}/.test(body), "a failed request is swallowed again");
  assert.ok(/catch \(e\) \{\s*setError\(/.test(body), "a failed request is not said");
});
