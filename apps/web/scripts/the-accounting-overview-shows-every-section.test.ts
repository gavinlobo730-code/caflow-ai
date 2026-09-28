/**
 * The Accounting Overview page (app/accounting/page.tsx) has a quick-access
 * card for every section AccountingPanel's sidebar lists — sweep-accounting-
 * hub-1-04.
 *
 * WHAT WAS WRONG. The sidebar's NAV_GROUPS has five groups — Chart of
 * accounts, Registers, Across clients, Period close, Firm — and the landing
 * page's own ADMIN_CARDS carried a card for Registers and Period close only.
 * A CA who lands on `/accounting` directly (rather than arriving already
 * inside the module, where the sidebar is in front of them) had no way to
 * reach Schedule III Mapping, Account Groups, COA import/export, the
 * cross-client worklists (Banking, Sales, Purchases, Fixed Assets, Year-End),
 * Fee Billing or Data Migration from the one page whose whole job is to be
 * the entry point to firm-level accounting administration.
 *
 * `scripts/a-module-shows-all-of-itself.test.ts` already holds the SIDEBAR to
 * "lists the whole module" and says, in its own docstring, that a landing
 * page may show whatever subset it likes — so that guard cannot see this
 * defect and is not meant to. This is the companion check for the one landing
 * page in this module that specifically claims (in its own H1) to be the
 * administration entry point: every href NAV_GROUPS declares (other than the
 * Overview link to this very page) must appear somewhere on it.
 *
 * HOW IT READS THE SIDEBAR. `AccountingPanel.tsx`'s `NAV_GROUPS` is a plain
 * array literal, so its `heading`/`label`/`href` triples are read off the
 * SOURCE rather than re-declared here — the same reason `panelForWorkspace()`
 * in the sibling guard reads `ContextPanel.tsx` instead of copying its
 * mapping. Comments are stripped first (`stripComments`), because a comment
 * naming an href is not a card for it.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = join(import.meta.dirname, "..");

interface NavEntry { heading: string; label: string; href: string }

function readSidebarSections(): NavEntry[] {
  const src = stripComments(
    readFileSync(join(WEB, "components/panels/AccountingPanel.tsx"), "utf8"),
  );
  const entries: NavEntry[] = [];
  let heading: string | null = null;
  for (const line of src.split("\n")) {
    const headed = line.match(/heading:\s*"([^"]+)"/);
    if (headed) { heading = headed[1]; continue; }
    if (/heading:\s*null\s*,/.test(line)) { heading = null; continue; }
    const item = line.match(/label:\s*"([^"]+)",\s*href:\s*"([^"]+)"/);
    // `heading === null` is the Overview group — the page linking to itself,
    // not a section the page needs a CARD for.
    if (item && heading) entries.push({ heading, label: item[1], href: item[2] });
  }
  return entries;
}

test("NAV_GROUPS is still readable as (heading, label, href) triples", () => {
  const entries = readSidebarSections();
  // Vacuity floor on the POPULATION read, not on the offenders (a floor
  // counting what is still wrong breaks the day the work succeeds). At the
  // time this guard was written the module had 21 sectioned entries across
  // five headings; this only needs to stay in the right ballpark.
  assert.ok(
    entries.length >= 15,
    `only ${entries.length} sidebar entries read off AccountingPanel.tsx — ` +
      "the parser or NAV_GROUPS's own shape has moved.",
  );
  const headings = new Set(entries.map((e) => e.heading));
  for (const h of ["Chart of accounts", "Registers", "Across clients", "Period close", "Firm"]) {
    assert.ok(headings.has(h), `expected a "${h}" heading in NAV_GROUPS and found none`);
  }
});

test("every sidebar section has a quick-access card on the Accounting Overview page", () => {
  const entries = readSidebarSections();
  const pageSrc = stripComments(
    readFileSync(join(WEB, "app/accounting/page.tsx"), "utf8"),
  );
  const missing = entries.filter((e) => !pageSrc.includes(`"${e.href}"`));
  assert.deepEqual(
    missing.map((m) => `${m.href}  (${m.heading} → ${m.label})`),
    [],
    "These sidebar sections have no quick-access card on app/accounting/page.tsx:\n  " +
      missing.map((m) => `${m.href}  (${m.heading} → ${m.label})`).join("\n  "),
  );
});

test("the three sections this guard was written for are the ones now covered", () => {
  // Negative control with teeth: these eleven hrefs are the exact set the
  // sweep found with no card at all (Chart of accounts, Across clients,
  // Firm). A rewrite of the page that made the sweep above vacuous should
  // still have to keep these listed somewhere on it.
  const pageSrc = stripComments(
    readFileSync(join(WEB, "app/accounting/page.tsx"), "utf8"),
  );
  const onceMissing = [
    "/accounting/schedule-iii-mapping",
    "/accounting/account-groups",
    "/accounting/coa-import",
    "/accounting/coa-export",
    "/accounting/banking",
    "/accounting/invoices",
    "/accounting/purchases",
    "/accounting/fixed-assets",
    "/accounting/year-end",
    "/billing",
    "/migration",
  ];
  const stillMissing = onceMissing.filter((h) => !pageSrc.includes(`"${h}"`));
  assert.deepEqual(stillMissing, [], "still missing:\n  " + stillMissing.join("\n  "));
});
