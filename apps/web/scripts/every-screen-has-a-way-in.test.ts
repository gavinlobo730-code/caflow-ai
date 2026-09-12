// A screen nothing links to is a screen nobody can open.
//
// apps/api/tests/test_every_mounted_endpoint_has_a_way_in.py makes this
// argument for endpoints. This is the same argument one level up, and the
// reason it exists NOW is the client-workspace redesign: replacing a sidebar
// with a module hub means every link into every screen is rewritten at once,
// and the failure it carries is silent. The page still builds, still renders
// when you type its URL, and no test fails — there is simply no longer a
// button anywhere that leads to it.
//
// WHAT COUNTS AS A LINK is deliberately loose, and the looseness is the whole
// reason this is an exemption list rather than a clean assertion. A route is
// "reached" if some non-test file under app/, lib/ or components/ names it:
//
//   * as a full path, with any dynamic segment matching anything
//     (`/clients/${id}/gst` reaches /clients/:id/gst);
//   * as the tail after its last dynamic segment, because the client
//     workspace links relatively (`href: "tax/computation"`).
//
// Comments are stripped first — scripts/stripComments.ts — because a comment
// EXPLAINING that a screen is no longer linked is the one thing that must not
// count as linking it. That is not hypothetical: ClientContextPanel.tsx has a
// comment naming "compliance/gst", and before the strip it was the only thing
// in the tree that did.
//
// WHAT IT CANNOT SEE, inherited from the same shape as the backend guard: a
// path assembled from a variable. The compliance landing page renders its
// three workspace cards from a config array and pushes
// `/clients/${clientId}/compliance/${path}` — a real, working link that no
// static scan of this kind can find. Those are in UNLINKED below with that
// as their reason.
//
// Run with: node --experimental-strip-types --test scripts/every-screen-has-a-way-in.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";
import { screenRoutes } from "./refresh-screen-snapshot.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");

/**
 * Screens no static scan of this tree can see a link to, each with the reason.
 *
 * A list rather than a number, because there are six of them and a reason per
 * entry is worth more than a budget. Adding one is a claim, and it belongs in
 * a review; removing one when a screen gets a real link is the ratchet.
 */
const UNLINKED: Record<string, string> = {
  "/accounting/fixed-assets":
    "a MovedToClientWorkspace stub kept so an old bookmark lands somewhere " +
    "rather than 404ing — being unlinked is the point",
  "/accounting/invoices":
    "the same stub, for the Sales tab",
  "/clients/:id/compliance/gst":
    "reached from the compliance landing page's workspace cards, which push " +
    "`/clients/${clientId}/compliance/${path}` from a config array — a real " +
    "link this scan cannot see",
  "/clients/:id/compliance/mca":
    "same config array; offered only for a Companies Act company or an LLP",
  "/clients/:id/compliance/tds":
    "same config array",
  "/portal/employee/activate":
    "the landing page for the invite link emailed by " +
    "services/employee_portal_service.py::_send_invite_email — nothing in " +
    "the product links to it and nothing should",
};

function sourceBlob(): string {
  const parts: string[] = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(p);
      else if (/\.tsx?$/.test(entry.name) && !entry.name.includes(".test."))
        parts.push(stripComments(fs.readFileSync(p, "utf8")));
    }
  };
  for (const folder of ["app", "lib", "components"]) walk(path.join(WEB, folder));
  return parts.join("\n");
}

const BLOB = sourceBlob();
const ROUTES = screenRoutes(path.join(WEB, "app"));

function isReached(route: string): boolean {
  const chunks = route.split(/:[^/]+/);
  const escaped = chunks.map((c) => c.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (new RegExp(escaped.join("[^\\s\"'`]*?")).test(BLOB)) return true;
  // A relative href from inside the client workspace: `href: "tax/computation"`.
  const tail = chunks[chunks.length - 1].replace(/^\//, "");
  return chunks.length > 1 && tail.includes("/") && BLOB.includes(tail);
}

const unreached = ROUTES.filter((r) => r !== "/" && !isReached(r));

test("the scan still sees the app", () => {
  // A walker that stops finding pages, or a blob that comes back empty, would
  // make every assertion below pass while checking nothing.
  assert.ok(ROUTES.length > 100, `only ${ROUTES.length} screens found in app/`);
  assert.ok(BLOB.length > 1_000_000, `source blob is only ${BLOB.length} chars`);
  assert.ok(
    isReached("/clients/:id/overview"),
    "a screen the client nav links from its own config reads as unlinked — the\n" +
      "matcher has stopped working, not the product"
  );
});

test("no screen is unreachable without a recorded reason", () => {
  const surprises = unreached.filter((r) => !(r in UNLINKED));
  assert.deepEqual(
    surprises,
    [],
    `${surprises.length} screen(s) exist that nothing in the product links to:\n  ` +
      surprises.join("\n  ") +
      `\n\nA CA cannot open a page there is no button for, however well it ` +
      `works. Link it from wherever it belongs, or add it to UNLINKED with ` +
      `the reason — an entry saying "this scan cannot see the link" is fine ` +
      `and expected; "we will link it later" is not.`
  );
});

test("no exemption outlives its reason", () => {
  // The half that makes it a ratchet: once a screen gets a real link, its
  // entry has to go, or the list slowly stops meaning anything.
  const stale = Object.keys(UNLINKED).filter((r) => !unreached.includes(r));
  assert.deepEqual(
    stale,
    [],
    `these UNLINKED entries name screens that ARE now reachable (or no longer ` +
      `exist) — delete them:\n  ` + stale.join("\n  ")
  );
});
