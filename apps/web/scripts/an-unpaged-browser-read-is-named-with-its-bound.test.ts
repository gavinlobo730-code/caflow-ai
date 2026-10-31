// Every browser read that nothing bounds is either paged or named here with the reason it cannot outgrow the row ceiling (POST-A-135).
//
// WHAT WAS WRONG
//   PostgREST answers a read with at most ~1000 rows and says nothing when it stopped there. A browser read with no `.limit`,
//   `.range`, `.single` or pager therefore goes quietly short once the table outgrows the cap, and a list, a pick-list or a
//   total drawn from it is wrong without any sign. `an-export-reads-every-row.test.ts` holds the reads somebody had already
//   found; the ledger carried "about 60 reads, judged bounded by their scope and NOT read individually" for weeks, which is
//   the state in which the next unbounded read is added by accident.
//
// WHAT THIS HOLDS
//   Every `.from(t).select(...)` in app, components and lib that has no limit, range, single, count-only head request, id
//   lookup or enclosing `selectAll`/`selectAllKeyset` is a key in BOUNDED below, with the number of such reads in that file for
//   that table and the reason it is bounded. A new one fails until somebody decides. An entry whose read is gone, paged or
//   changed in number also fails, so the list can only be as long as the truth. On 31-10-2026 the 14 firm-wide reads that grow
//   with a firm's volume (the client lists, health scores and alerts, MCA filings, loans, notices) and the 8 per-client or
//   per-party lists that accumulate over years (a vendor's bills, a client's obligations, unresolved alerts) were paged; what
//   is left is below.
//
// Run with: node --experimental-strip-types --test scripts/an-unpaged-browser-read-is-named-with-its-bound.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { findUnboundedReads } from "./unboundedReads.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");

const ONE_CLIENT = "one client's own rows, a handful a year";
const BY_IDS = "catalogue items named by ids or HSN codes already on the document's own lines, so bounded by the lines";
const CHUNK = "document numbers looked up in chunks of 200, so bounded by the chunk";
const ONE_ENGAGEMENT = "one year-end engagement's rows";

/** "file::table" -> how many unbounded reads of that table the file holds, and why none can outgrow the ceiling. */
const BOUNDED: Record<string, { reads: number; why: string }> = {
  "app/client-portal/page.tsx::shared_reports": { reads: 1, why: "the reports the firm shared with ONE client, a few a month" },
  "app/clients/[id]/compliance/page.tsx::government_notices": { reads: 1, why: `${ONE_CLIENT} (government notices)` },
  "app/clients/[id]/lifecycle/page.tsx::onboarding_workflows": { reads: 1, why: "one client's onboarding workflows, one or two in its life" },
  "app/clients/[id]/portal/page.tsx::client_portal_users": { reads: 1, why: "one client's portal contacts, a handful" },
  "app/clients/[id]/purchases/page.tsx::purchase_bills": { reads: 1, why: CHUNK },
  "app/clients/[id]/purchases/page.tsx::currencies": { reads: 1, why: "the currency reference table, a closed list of codes far below the cap" },
  "app/clients/[id]/sales/page.tsx::client_sales_invoices": { reads: 1, why: CHUNK },
  "app/clients/[id]/tax/filing/page.tsx::itr_filings": { reads: 1, why: "one client's returns of income, one per year and form" },
  "app/clients/[id]/year-end/[engagementId]/adjustments/_page.tsx::year_end_adjustments": { reads: 1, why: ONE_ENGAGEMENT },
  "app/clients/[id]/year-end/[engagementId]/dashboard/_page.tsx::users": { reads: 1, why: "row security lets a signed-in session read only its OWN users row, so at most one" },
  "app/clients/[id]/year-end/[engagementId]/notes/_page.tsx::year_end_notes": { reads: 1, why: ONE_ENGAGEMENT },
  "app/clients/[id]/year-end/page.tsx::year_end_engagements": { reads: 1, why: "one client's year-end engagements, one per year" },
  "app/clients/[id]/year-end/xbrl/page.tsx::xbrl_packages": { reads: 1, why: "one client's XBRL packages, a few per year" },
  "app/income-tax/tax-audit/page.tsx::tax_audits": { reads: 1, why: "one financial year's tax audits for the firm, one per audit client" },
  "components/invoices/InvoiceEditor.tsx::service_catalogue": { reads: 1, why: BY_IDS },
  "components/purchases/AllocatePaymentModal.tsx::purchase_payment_allocations": { reads: 1, why: "the allocations of ONE payment" },
  "components/purchases/DebitNoteEditor.tsx::service_catalogue": { reads: 1, why: BY_IDS },
  "components/purchases/PurchaseBillEditor.tsx::service_catalogue": { reads: 3, why: BY_IDS },
  "components/purchases/PurchaseCreditNoteEditor.tsx::service_catalogue": { reads: 1, why: BY_IDS },
  "components/sales/AllocateReceiptModal.tsx::receipt_allocations": { reads: 1, why: "the allocations of ONE receipt" },
  "components/sales/SalesCreditNoteEditor.tsx::service_catalogue": { reads: 1, why: BY_IDS },
  "components/sales/SalesDebitNoteEditor.tsx::service_catalogue": { reads: 1, why: BY_IDS },
  "lib/data/gst.ts::gstr1_returns": { reads: 2, why: "one client's GSTR-1 returns, one per period and registration, twelve a year" },
  "lib/data/gst.ts::gstr3b_returns": { reads: 2, why: "one client's GSTR-3B returns, one per period and registration, twelve a year" },
  "lib/data/income-tax.ts::it_notices": { reads: 1, why: "one client's income-tax notices, a few a year" },
  "lib/data/tasks.ts::users": { reads: 1, why: "the firm's own team, bounded by its headcount" },
  "lib/data/tds.ts::tds_returns": { reads: 1, why: "one client's TDS statements, four a year per form" },
};

const found = findUnboundedReads(WEB);
const counts = new Map<string, number>();
for (const r of found) counts.set(`${r.file}::${r.table}`, (counts.get(`${r.file}::${r.table}`) ?? 0) + 1);

test("the scanner reads the tree it is pointed at", () => {
  assert.ok(fs.existsSync(path.join(WEB, "app")) && fs.existsSync(path.join(WEB, "lib")), "the web app was not found");
  assert.ok(found.length >= 20, `the scan found only ${found.length} unbounded reads: the scanner has gone blind, not the tree clean`);
});

test("every unbounded browser read is named with the reason it is bounded", () => {
  const unnamed = [...counts.keys()].filter((k) => !(k in BOUNDED));
  assert.deepEqual(
    unnamed.map((k) => `${k} (${found.filter((r) => `${r.file}::${r.table}` === k).map((r) => `line ${r.line}: ${r.chain.slice(0, 70)}`).join("; ")})`),
    [],
    "A browser read with no limit, range, single or pager is cut at ~1000 rows by PostgREST with no sign. Page it with lib/supabase/selectAll.ts " +
    "(selectAllKeyset when the query embeds a child table) and a unique .order('id') tiebreaker, or, if it really cannot outgrow the " +
    "ceiling, name it in BOUNDED with the reason.",
  );
});

test("every name in the list is still a read, in the number stated", () => {
  const wrong = Object.entries(BOUNDED)
    .filter(([k, v]) => (counts.get(k) ?? 0) !== v.reads)
    .map(([k, v]) => `${k}: lists ${v.reads}, the tree has ${counts.get(k) ?? 0}`);
  assert.deepEqual(wrong, [], "An entry whose read was paged, removed or added to must change here: the list is as long as the truth.");
});

test("every name carries a reason", () => {
  for (const [k, v] of Object.entries(BOUNDED)) assert.ok(v.why.trim().length > 15, `${k} has no real reason`);
});

// ── The scanner itself, on snippets, so a blind spot in it cannot make the tree look clean ─────────────────────

// The snippets are BUILT, not written out: `test_frontend_tables_exist.py` and the RLS matrix's table list read every from-call with
// a quoted name under apps/web, comments and test strings included, and a made-up table in a literal would be read as a screen
// querying a table no migration creates (it was, on the first run). The names below are real tables.
const from = (table: string) => `.from(${JSON.stringify(table)})`;

function scanSnippet(src: string): number {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "unbounded-"));
  try {
    fs.mkdirSync(path.join(dir, "app"));
    fs.writeFileSync(path.join(dir, "app", "x.tsx"), src);
    return findUnboundedReads(dir).length;
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

test("a bare read is flagged and a limit, a range, a single, a count-only head, an id lookup or a pager each bound it", () => {
  assert.equal(scanSnippet(`const r = await sb${from("clients")}.select("*").eq("firm_id", f).order("name");`), 1);
  assert.equal(scanSnippet(`const r = await sb${from("clients")}.select("*").limit(50);`), 0);
  assert.equal(scanSnippet(`const r = await sb${from("clients")}.select("*").range(0, 9);`), 0);
  assert.equal(scanSnippet(`const r = await sb${from("clients")}.select("*").eq("id", x).maybeSingle();`), 0);
  assert.equal(scanSnippet(`const r = await sb${from("clients")}.select("id", { count: "exact", head: true });`), 0);
  assert.equal(scanSnippet(`const r = await sb${from("clients")}.select("*").eq("id", x);`), 0);
  assert.equal(scanSnippet(`const r = await selectAll(() => sb${from("clients")}.select("*").order("id"));`), 0);
  assert.equal(scanSnippet(`const r = await selectAllKeyset(() => sb${from("loans")}.select("*, clients(name)"));`), 0);
  assert.equal(scanSnippet(`await sb${from("clients")}.insert({ a: 1 });`), 0);
});

test("a pager that has already closed does not bound a later bare read, and a comment does not hide one", () => {
  assert.equal(
    scanSnippet(`const a = await selectAll(() => sb${from("clients")}.select("*").order("id"));\nconst b = await sb${from("loans")}.select("*");`), 1,
    "a read after a closed pager call was treated as paged");
  assert.equal(scanSnippet(`// selectAll( explains it\nconst b = await sb${from("loans")}.select("*");`), 1, "a comment naming selectAll hid a bare read");
});

test("a comment line that contains a block-comment opener does not hide the code after it", () => {
  // The old comment stripper of the paging guard treated "/*" inside a line comment as the start of a block and removed the code up to
  // the next close; the scanner uses the quote-aware stripper, so the read below is still seen.
  assert.equal(scanSnippet(`// not the /api/health/* routes\nconst b = await sb${from("loans")}.select("*");\n/* later */`), 1);
});
