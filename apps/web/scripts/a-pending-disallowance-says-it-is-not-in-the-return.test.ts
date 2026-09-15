/**
 * A recorded disallowance can be accepted, and a pending one says it is not in
 * the computation.
 *
 * `tax_disallowances.status` is `pending` on creation and this screen sends
 * only the accepted ones to the engine. `PATCH /api/itr/disallowances/{id}
 * /status` is the only way out of pending and had no caller — so every
 * §40A(3) cash disallowance and every §43B unpaid liability a CA recorded was
 * silently left out of the return, in the direction that UNDER-states tax.
 *
 * Two things this file holds:
 *   the CONTROL exists and calls the server; and
 *   a pending row SAYS it is excluded, because four amber rows totalling
 *   ₹4,00,000 look like ₹4,00,000 of add-backs to anyone reading the panel.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = path.join(WEB, "app/clients/[id]/tax/computation/page.tsx");

function withoutComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .split("\n")
    .map((l) => l.replace(/(^|\s)\/\/.*$/, "$1"))
    .join("\n");
}

const raw = fs.readFileSync(PAGE, "utf8");
const code = withoutComments(raw);

test("a pending disallowance says it is not in the return", async (t) => {
  await t.test("the screen can move a disallowance out of pending", () => {
    // ANCHORED. A negative control pointed the fetch at `/status-x` and this
    // still passed, because an unanchored pattern matches a prefix — the
    // screen would have been calling an endpoint that does not exist while
    // the test reported the control present.
    assert.match(code, /`\/api\/itr\/disallowances\/\$\{id\}\/status`/,
      "nothing calls the status endpoint — the panel is read-only again");
    assert.match(code, /method:\s*"PATCH"/);
    assert.match(code, /setDisallowanceStatus\(d\.id,\s*"accepted"\)/);
    assert.match(code, /setDisallowanceStatus\(d\.id,\s*"rejected"\)/);
  });

  await t.test("a row that is not accepted says so", () => {
    assert.match(code, /not in the computation/,
      "an excluded disallowance is shown with no sign that it is excluded");
  });

  await t.test("the panel totals what will actually be added back", () => {
    // The same predicate the compute call uses, shown to the CA.
    assert.match(code, /Added back to income/);
    assert.match(code,
      /disallowances\.filter\(d => d\.status === "accepted"\)\s*\n?\s*\.reduce/,
      "the total shown is not the accepted-only total");
  });

  await t.test("the approve tier comes from the server, not a copy", () => {
    assert.match(code, /can\("income_tax", "approve"\)/);
    // No role names in the screen: the Team screen's own hardcoded ROLE_DEFAULTS
    // had drifted from PERMISSIONS in both directions.
    for (const r of [/"Manager"/, /"Partner"/, /"Executive"/, /role ===/]) {
      assert.ok(!r.test(code), `${r} is a second copy of the permission rule`);
    }
  });

  await t.test("someone who cannot approve is told who can", () => {
    assert.match(code, /a Manager accepts this/,
      "an Executive gets no button and no explanation");
  });

  await t.test("the compute call still sends only accepted disallowances", () => {
    // The half that was already right. Adding a control must not widen it.
    assert.match(code, /\.filter\(d => d\.status === "accepted"\)/);
  });

  await t.test("the comment strip does not make the scan vacuous", () => {
    assert.ok(code.length > raw.length / 2, "too much of the file was stripped");
    assert.match(code, /const setDisallowanceStatus = async/);
  });
});
