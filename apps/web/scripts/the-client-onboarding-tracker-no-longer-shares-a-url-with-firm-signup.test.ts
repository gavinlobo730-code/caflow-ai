// sweep-auth-and-public-05: /onboarding/checklist was the staff CLIENT-
// onboarding workflow tracker ("Client Onboarding" heading, breadcrumb
// Clients / Onboarding), sharing the /onboarding/* prefix with the unrelated
// pre-auth firm-SIGNUP wizard at /onboarding — confusing enough that even a
// route-grouping sweep treated it as step 2 of firm signup.
//
// The tracker moved to /clients/onboarding, in the Clients workspace it
// actually belongs to. The old URL was kept for a while as a forwarding page
// for bookmarks; nothing in the product, its mail or its documents linked to
// it, so POST-A-562 deleted it (26-11-2026).
//
// Run with:
//   node --experimental-strip-types --test scripts/the-client-onboarding-tracker-no-longer-shares-a-url-with-firm-signup.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { stripComments } from "./stripComments.ts";
import { getActiveWorkspaceForPathname } from "../lib/workspace/routeOwnership.ts";
import { isPublicPath } from "../lib/auth/public-paths.ts";
import { SCREENS, UNLISTED } from "../lib/navigation/screens.ts";

const NEW_PAGE = "app/clients/onboarding/page.tsx";
const OLD_PAGE = "app/onboarding/checklist/page.tsx";
const CLIENTS_PANEL = "components/panels/ClientsPanel.tsx";

test("the real tracker now lives under /clients", () => {
  assert.ok(existsSync(NEW_PAGE), `${NEW_PAGE} does not exist — the move did not happen`);
  const src = readFileSync(NEW_PAGE, "utf8");
  assert.match(src, /Client Onboarding/, `${NEW_PAGE} is missing its own heading`);
  assert.match(src, /api\.onboarding\.listActive/, `${NEW_PAGE} is missing the workflow it tracks`);
});

test("the old URL has no page: the tracker lives only under /clients", () => {
  assert.ok(!existsSync(OLD_PAGE), `${OLD_PAGE} is back — the tracker has one address, /clients/onboarding`);
});

test("ClientsPanel links to the new path, not the old one", () => {
  const src = stripComments(readFileSync(CLIENTS_PANEL, "utf8"));
  assert.match(src, /"\/clients\/onboarding"/, `${CLIENTS_PANEL} does not link to /clients/onboarding`);
  assert.doesNotMatch(src, /"\/onboarding\/checklist"/, `${CLIENTS_PANEL} still links to the old URL`);
});

test("/clients/onboarding resolves to the Clients workspace with no special case needed", () => {
  assert.equal(getActiveWorkspaceForPathname("/clients/onboarding"), "clients");
});

test("the old URL is neither public nor owned by a workspace, same as /onboarding itself", () => {
  assert.equal(isPublicPath("/onboarding/checklist"), false);
  assert.equal(getActiveWorkspaceForPathname("/onboarding/checklist"), null);
});

test("the palette points at the new path and names the old one nowhere", () => {
  const hrefs = new Set(SCREENS.map((s) => s.href));
  assert.ok(hrefs.has("/clients/onboarding"), "the palette has no /clients/onboarding entry");
  assert.ok(!hrefs.has("/onboarding/checklist"), "the palette still names the old URL as a live screen");
  assert.ok(
    !("/onboarding/checklist" in UNLISTED),
    "UNLISTED still gives a reason for a page that no longer exists",
  );
});
