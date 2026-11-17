// POST-A-454. The client menu offers a section, and a client screen a tab, only to someone the section's or tab's own first read
// will answer, and each pair is held to that route's `rbac(...)` in the API source.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const WEB = join(import.meta.dirname, "..");
const API = join(WEB, "..", "api");
const read = (...p: string[]) => readFileSync(join(...p), "utf8");

/** The pair a GET route asks, read from the router; a router-level dependency counts when the route names none. */
function routePair(router: string, path: string): string {
  const src = read(API, "routers", router);
  const at = src.indexOf(`@router.get("${path}")`);
  assert.ok(at >= 0, `${router} has no GET "${path}"`);
  const next = src.indexOf("@router.", at + 1);
  const own = src.slice(at, next < 0 ? undefined : next).match(/rbac\("([a-z_]+)",\s*"([a-z_]+)"\)/);
  const m = own ?? src.match(/APIRouter\([^)]*dependencies=\[Depends\(rbac\("([a-z_]+)",\s*"([a-z_]+)"\)\)\]/);
  assert.ok(m, `GET "${path}" in ${router} asks no pair`);
  return `${m[1]}:${m[2]}`;
}

/** The pairs a CLIENT_SECTIONS entry carries, `requires` and `requiresAnyOf` together. */
function sectionPairs(id: string): { requires: string | null; anyOf: string[] } {
  const src = read(WEB, "lib", "workspace", "ClientNavContext.tsx");
  const at = src.indexOf(`{ id: "${id}",`);
  assert.ok(at >= 0, `CLIENT_SECTIONS has no "${id}"`);
  const entry = src.slice(at, src.indexOf("},", at) + 2) + src.slice(src.indexOf("},", at) + 2, src.indexOf("\n  {", at + 1));
  const req = entry.match(/requires:\s*\["([a-z_]+)",\s*"([a-z_]+)"\]/);
  const any = entry.match(/requiresAnyOf:\s*\[(.*?)\]\s*\}/s);
  return {
    requires: req ? `${req[1]}:${req[2]}` : null,
    anyOf: any ? [...any[1].matchAll(/\["([a-z_]+)",\s*"([a-z_]+)"\]/g)].map((m) => `${m[1]}:${m[2]}`) : [],
  };
}

const SECTION_READS: Array<[string, string, string, string, string]> = [
  // section, router, path, the page file the read is made from, how the page makes it
  ["accounting", "accounting.py", "/profit-loss", "app/clients/[id]/accounting/page.tsx", "api.accounting.profitLoss"],
  // The Bank section opens on its Entries tab, which lists the client's accounts (every /api/banking route asks banking read).
  ["bank", "banking.py", "/accounts", "components/banking/EntriesTab.tsx", "api.banking.listBankAccounts"],
  ["inventory", "inventory.py", "/stock-summary", "app/clients/[id]/inventory/page.tsx", "api.inventory.stockSummary"],
  // The Sales section opens on Sales Invoices, whose panel reads the two unfinished-invoice lists (both ask accounting read). The Purchases
  // section is NOT here: its opening tab reads its tables directly under row security and no API route that asks a pair, so there is no
  // pair to hold it to.
  ["sales", "sales_invoices.py", "/maintenance/posted-drafts", "components/invoices/UnfinishedInvoicesPanel.tsx", "api.salesInvoices.postedDrafts"],
  ["fixed-assets", "fixed_assets.py", "", "app/clients/[id]/fixed-assets/page.tsx", "/api/fixed-assets"],
  ["year-end", "year_end.py", "/engagements", "app/clients/[id]/year-end/page.tsx", "/year-end/engagements"],
];

test("each gated section asks what its first read asks, and its page still makes that read", () => {
  for (const [id, router, path, page, call] of SECTION_READS) {
    assert.equal(sectionPairs(id).requires, routePair(router, path), `the ${id} section`);
    assert.ok(read(WEB, ...page.split("/")).includes(call), `${page} no longer reads ${call}: re-read what the ${id} section asks`);
  }
});

test("the Sales section's two opening reads ask the same pair, so one pair is the whole truth", () => {
  assert.equal(routePair("sales_invoices.py", "/maintenance/unposted"), routePair("sales_invoices.py", "/maintenance/posted-drafts"));
  assert.equal(routePair("sales_invoices.py", "/maintenance/unposted"), "accounting:read");
});

test("the reports section is offered to someone who may read the books or the bank, which is what every report reads", () => {
  assert.deepEqual(sectionPairs("reports"), { requires: null, anyOf: ["accounting:read", "banking:read"] });
});

test("a section every member of staff can read carries no pair, so it is never hidden from them", () => {
  for (const id of ["overview", "purchases", "compliance", "tax", "documents", "tasks"]) {
    assert.deepEqual(sectionPairs(id), { requires: null, anyOf: [] }, `the ${id} section`);
  }
});

test("the client menu lists the sections it is offered, not the whole list", () => {
  const grid = read(WEB, "components", "client", "ClientModuleGrid.tsx");
  assert.match(grid, /sectionsOffered\(can, resolved\)/);
  assert.doesNotMatch(grid, /CLIENT_SECTIONS\.map\(/, "the grid draws every section again");
  const nav = read(WEB, "lib", "workspace", "ClientNavContext.tsx");
  assert.match(nav, /CLIENT_SECTIONS\.filter\(\(s\) => workspaceTileOffered\(s, can, resolved\)\)/, "sections are judged by the tile rule");
});

test("the Verify Books tab asks what the reconciliation checks ask, and says so to someone who reaches it anyway", () => {
  assert.equal(routePair("reconciliation.py", "/checks"), "accounting:approve");
  const page = read(WEB, "app", "clients", "[id]", "accounting", "page.tsx");
  assert.match(page, /\{ id: "verify-books",\s+label: "Verify Books", requires: \["accounting", "approve"\] \}/);
  assert.match(page, /TABS\.filter\(\(t\) => !t\.requires \|\| !tabsResolved \|\| tabsCan\(t\.requires\[0\], t\.requires\[1\]\)\)/);
  assert.match(page, /tabsResolved && !tabsCan\("accounting", "approve"\)/);
  assert.match(page, /api\.reconciliation\.checks\(/);
});

test("the GSTR-9 tab asks what GSTR-9 and GSTR-9C compute ask", () => {
  assert.equal(routePair("gst_workspace.py", "/gstr9/compute"), "gst:compute");
  assert.equal(routePair("gst_workspace.py", "/gstr9c/compute"), "gst:compute");
  const page = read(WEB, "app", "clients", "[id]", "compliance", "gst", "page.tsx");
  assert.match(page, /\{ id: "gstr9", label: "GSTR-9", requires: \["gst", "compute"\] \}/);
  assert.match(page, /TABS\.filter\(\(t\) => !t\.requires \|\| !resolved \|\| can\(t\.requires\[0\], t\.requires\[1\]\)\)/);
  assert.doesNotMatch(page, /\{TABS\.map\(/, "the GST tabs are drawn from the whole list again");
});
