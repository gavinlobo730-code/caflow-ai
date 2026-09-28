// sweep-tds-mca-09: the firm-level TDS workspace (Deductions / Challans /
// Returns / Certificates) has no 26AS Reconciliation and no §197
// Lower-Deduction Certificates tab — those live only on the client-scoped
// Compliance → TDS workspace — and carried no cross-link to them at all.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-firm-tds-workspace-cross-links-to-26as-and-section-197.test.ts
//
// This does not ask the firm page to grow the two tabs (that would duplicate
// a client-scoped workspace on a firm-wide screen with no client context of
// its own — see the client TDS workspace's own 26AS/§197 tabs). It asks for a
// line, shown once a client is picked, pointing at where those two live.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const FIRM_PAGE = "app/tds/page.tsx";
const CLIENT_PAGE = "app/clients/[id]/compliance/tds/page.tsx";

test("the firm TDS page's own tabs are still just the four — no silent duplicate", () => {
  const src = readFileSync(FIRM_PAGE, "utf8");
  assert.match(
    src,
    /const TABS = \["Deductions", "Challans", "Returns", "Certificates"\];/,
    "the firm-wide TDS workspace grew a fifth tab — 26AS Reconciliation and " +
      "§197 Lower-Deduction Certificates belong on the client-scoped " +
      "Compliance → TDS workspace, not duplicated here",
  );
});

test("the firm TDS page cross-links to the client's 26AS / §197 workspace", () => {
  const src = readFileSync(FIRM_PAGE, "utf8");

  assert.match(src, /26AS/, `${FIRM_PAGE} no longer mentions 26AS Reconciliation`);
  assert.match(src, /§197/, `${FIRM_PAGE} no longer mentions §197 Lower-Deduction Certificates`);
  assert.match(
    src,
    /\/clients\/\$\{selectedClientId\}\/compliance\/tds/,
    `${FIRM_PAGE} no longer links to /clients/{id}/compliance/tds`,
  );
});

test("that link points at a route the client workspace actually serves", () => {
  // Not a claim the two tabs are AT that route by name — just that the route
  // itself exists and is the one holding form26as / lower_deduction.
  const src = readFileSync(CLIENT_PAGE, "utf8");
  assert.match(src, /"form26as"/, `${CLIENT_PAGE} no longer has a form26as tab`);
  assert.match(src, /"lower_deduction"/, `${CLIENT_PAGE} no longer has a lower_deduction tab`);
});
