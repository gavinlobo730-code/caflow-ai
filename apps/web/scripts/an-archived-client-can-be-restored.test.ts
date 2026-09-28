// An archived client can be brought back, from the list AND from the client.
//
// Run with:
//   node --experimental-strip-types --test scripts/an-archived-client-can-be-restored.test.ts
//
// WHAT WAS WRONG (sweep-clients-admin-05)
//     POST /api/clients/{id}/restore has existed, guarded and tested, since the
//     lifecycle work — and a CA could not find it. The client list's bulk bar
//     offered Archive and nothing else, so on the Archived tab selecting a
//     client and pressing the only button said "already archived" and wrote
//     nothing. The per-row Restore sat in a menu whose trigger is invisible
//     until the row is hovered. And the archived client's own workspace opened
//     exactly like an active one, with nothing saying it was archived.
//
// WHAT THIS HOLDS
//     The bulk bar has a restore path; the workspace bar knows the client's
//     status and offers Restore. Each assertion names a BEHAVIOUR it needs
//     (a call to the restore function, a status in the lookup) rather than a
//     label, so rewording a button does not fail it.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (p: string) => fs.readFileSync(path.join(WEB, p), "utf8");
const code = (p: string) => read(p).replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");

test("the client list can restore a selection, not only archive one", () => {
  const src = code("app/clients/page.tsx");
  const bulk = src.match(/async function bulkRestore\(\)[\s\S]*?\n {2}\}\n/);
  assert.ok(bulk, "no bulk restore on the client list");
  assert.match(bulk[0], /restoreClient\(/, "the bulk restore never calls the restore endpoint");
  assert.match(src, /onClick=\{bulkRestore\}/, "nothing on the bulk bar reaches the restore");
});

test("the per-row menu can be reached without a mouse hover", () => {
  const src = code("app/clients/page.tsx");
  const trigger = src.match(/className="[^"]*"\s*title="More actions"/);
  assert.ok(trigger, "the row's action trigger has moved — update this guard");
  assert.match(trigger[0], /focus-visible:opacity-100/);
});

test("the workspace bar knows the client is archived and can restore it", () => {
  assert.match(code("lib/workspace/ClientNavContext.tsx"),
    /\.select\("[^"]*\bstatus\b[^"]*"\)/, "the client lookup does not read status");
  const bar = code("components/shell/ClientTopBar.tsx");
  assert.match(bar, /status === "archived"/);
  assert.match(bar, /restoreClient\(clientId\)/);
  assert.match(bar, /reloadClient\(\)/, "a restore must re-resolve the client, not patch a copy");
});
