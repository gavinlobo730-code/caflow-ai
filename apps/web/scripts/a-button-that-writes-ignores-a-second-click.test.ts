// A BUTTON THAT WRITES IGNORES A SECOND CLICK — THE CONVERSION RATCHET (frontend_ux-09).
//   node --experimental-strip-types --test scripts/a-button-that-writes-ignores-a-second-click.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// WHAT THIS HOLDS, AND WHAT IT DOES NOT
// ─────────────────────────────────────────────────────────────────────────────
// `components/ui/button.tsx` ignores a second click while the promise its handler
// returned is unresolved (proved by the-button-ignores-a-second-click-while-one-
// is-in-flight.test.ts). That only helps a screen that USES it. There were 1,664 raw
// `<button>` and 106 `<Button>`; this file is the other half:
//
//   1. the raw async-writing buttons that remain are a FROZEN TABLE, one count per
//      file, asserted as an EQUALITY in both directions — a new one fails, and one
//      that was converted must have its entry deleted, so the table can only fall.
//      (CLAUDE.md's `objectWithLists` shape: a budget is one number somebody
//      raises, a named list can only shrink.)
//   2. no `<Button>` may START an async write and drop the promise. That is the
//      half that makes a conversion real: `onClick={() => { save(); }}` and
//      `onClick={() => void save()}` discard what the primitive needs, the guard
//      is released on the same tick, and the screen has moved to the new component
//      without gaining the protection it thinks it has.
//   3. the screens that WRITE MONEY OR POST are named, and none of them may carry
//      an entry in the table.
//
// WHAT "ASYNC-WRITING" MEANS is in scripts/rawAsyncButtons.ts, with what it cannot
// see: a handler that arrives as a prop, a write behind a helper in another file,
// and a `<form onSubmit>`. It can only understate; it cannot invent a violation.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { analyseButtons, findDroppedPromises, findRawAsyncButtons } from "./rawAsyncButtons.ts";
import { stripComments } from "./stripComments.ts";

const WEB = join(import.meta.dirname, "..");

function walk(dir: string, out: string[] = []): string[] {
  for (const e of readdirSync(join(WEB, dir))) {
    if (e === "node_modules" || e === ".next") continue;
    const rel = join(dir, e).replace(/\\/g, "/");
    if (statSync(join(WEB, rel)).isDirectory()) walk(rel, out);
    else if (rel.endsWith(".tsx")) out.push(rel);
  }
  return out;
}
const FILES = ["app", "components"].flatMap((d) => walk(d));
const source = (rel: string) => readFileSync(join(WEB, rel), "utf8");

// ═════════════════════════════════════════════════════════════════════════════
// THE ANALYSIS — proved on small sources, so the table below is a number somebody can trust
// ═════════════════════════════════════════════════════════════════════════════

const raw = (src: string) => findRawAsyncButtons("t.tsx", src);
const dropped = (src: string) => findDroppedPromises("t.tsx", src);

test("a raw button whose click starts an async write is found", () => {
  const found = raw(`
    export function F() {
      async function save() { await api.accounting.createJournalEntry({}); }
      return <button onClick={save}>Post</button>;
    }`);
  assert.equal(found.length, 1);
  assert.equal(found[0].handler, "save");
  assert.equal(found[0].write, "api.accounting.createJournalEntry");
});

test("through an inline arrow, a Supabase write and a non-GET fetch it is found too", () => {
  assert.equal(raw(`function F(){ async function s(){ await supabase.from(TABLE).insert({}); }
    return <button onClick={() => s()}>x</button>; }`).length, 1);
  assert.equal(raw(`function F(){ async function s(){ await apiCall("/x", "POST", {}); }
    return <button onClick={s}>x</button>; }`).length, 1);
  assert.equal(raw(`function F(){ return <button onClick={async () => { await api.billing.generate(1); }}>x</button>; }`).length, 1);
});

test("a READ is not counted — a second click on Retry costs a request, not a voucher", () => {
  assert.equal(raw(`function F(){ async function load(){ await api.accounting.list(); await api.payroll.payrollClientStates(); }
    return <button onClick={load}>Retry</button>; }`).length, 0,
    "`payrollClientStates` begins with the letters of the verb `pay` and is not a payment");
  assert.equal(raw(`function F(){ async function s(){ await apiCall("/x", "GET"); }
    return <button onClick={s}>x</button>; }`).length, 0);
});

test("a write reached through another same-file function is found", () => {
  assert.equal(raw(`function F(){
    async function inner(){ await api.receipts.allocate(1); }
    async function outer(){ await inner(); }
    return <button onClick={outer}>x</button>; }`).length, 1);
});

test("a SYNC wrapper that starts an async write is reached", () => {
  const found = raw(`function F(){
    async function save(){ await api.accounting.updateAccount(1); }
    function click(){ save(); }
    return <button onClick={click}>x</button>; }`);
  assert.equal(found.length, 1);
});

test("a DELETE named clear… and a draft made by prepare… are writes, though neither verb starts with a common one", () => {
  // Both were found by reading the panels that landed on main after the conversion: the
  // credit ledger's "Remove the recorded balance" calls `clearOpening` (a DELETE), and the
  // overdue-interest panel's "Prepare draft invoice" calls `prepareDrafts`, which makes
  // draft tax invoices through the sales engine. The verb allowlist did not hold either,
  // so the analysis saw the neighbouring Save button and walked past the destructive one.
  assert.equal(raw(`function F(){ async function remove(){ await api.gstCreditLedger.clearOpening(1, "042026"); }
    return <button onClick={remove}>Remove</button>; }`).length, 1);
  assert.equal(raw(`function F(){ async function prepare(){ await api.lateInterest.prepareDrafts({}); }
    return <button onClick={() => prepare()}>Prepare</button>; }`).length, 1);
});

test("an unrelated async handler and a synchronous one are not counted", () => {
  assert.equal(raw(`function F(){ const [a,b]=useState(0); return <button onClick={() => b(a+1)}>x</button>; }`).length, 0);
  assert.equal(raw(`function F(){ async function wait(){ await new Promise(r=>setTimeout(r,1)); }
    return <button onClick={wait}>x</button>; }`).length, 0);
});

test("a same-named function in ANOTHER component is not the one the button reaches", () => {
  const src = `
    function A(){ async function save(){ await api.accounting.createAccount(1); } return <span onClick={save}/>; }
    function B(){ function save(){ return 1; } return <button onClick={save}>x</button>; }`;
  assert.equal(raw(src).length, 0);
});

test("a <Button> is not a raw button", () => {
  assert.equal(raw(`function F(){ async function save(){ await api.accounting.createAccount(1); }
    return <Button onClick={save}>x</Button>; }`).length, 0);
});

test("a <Button> whose handler RETURNS the promise is held, and one that drops it is found", () => {
  const head = `function F(){ async function save(){ await api.accounting.createAccount(1); }`;
  assert.equal(dropped(`${head} return <Button onClick={save}>x</Button>; }`).length, 0, "the async function itself");
  assert.equal(dropped(`${head} return <Button onClick={() => save()}>x</Button>; }`).length, 0, "an arrow returning it");
  assert.equal(dropped(`${head} return <Button onClick={() => { return save(); }}>x</Button>; }`).length, 0);
  assert.equal(dropped(`${head} return <Button onClick={() => save().then(() => 1)}>x</Button>; }`).length, 0, "a chain on it");
  assert.equal(dropped(`${head} return <Button onClick={() => { save(); }}>x</Button>; }`).length, 1, "a statement");
  assert.equal(dropped(`${head} return <Button onClick={() => void save()}>x</Button>; }`).length, 1, "void");
  assert.equal(dropped(`${head} return <Button onClick={() => { setOpen(false); save(); }}>x</Button>; }`).length, 1,
    "work before it does not make the promise returned");
  assert.equal(dropped(`${head} function click(){ void save(); } return <Button onClick={click}>x</Button>; }`).length, 1,
    "a sync wrapper that drops it");
  assert.equal(dropped(`${head} function click(){ return save(); } return <Button onClick={click}>x</Button>; }`).length, 0,
    "a sync wrapper that hands it back");
});

test("the analysis exposes the node a fix has to rewrite", () => {
  const { buttons } = analyseButtons("t.tsx", `function F(){ async function save(){ await api.accounting.createAccount(1); }
    return <Button onClick={() => { save(); }}>x</Button>; }`);
  assert.equal(buttons[0].dropSites.length, 1);
});

// ═════════════════════════════════════════════════════════════════════════════
// THE FROZEN TABLE
// ═════════════════════════════════════════════════════════════════════════════

/**
 * Raw async-writing `<button>`s that REMAIN, by file. This table may only shrink.
 *
 * What is NOT on it is the point: every screen that posts to the ledger, creates or
 * settles a money document, runs payroll, records a statutory filing or computes a
 * return has been moved onto <Button> (see MONEY_SCREENS below). What is left is
 * master data, trackers, portal messaging, settings and administration — a second
 * click there costs a duplicate row somebody deletes, not a duplicate voucher.
 * Moving one across is deleting its line here.
 */
const BASELINE: Record<string, number> = {
  // ── settings and master data ──
  "app/accounting/account-groups/page.tsx": 1,
  "app/accounting/coa-import/page.tsx": 1,
  "app/accounting/suppliers/page.tsx": 1,
  "app/settings/branding/page.tsx": 1,
  "app/settings/dsc-tracker/page.tsx": 3,
  "app/settings/firm-hsn-library/page.tsx": 4,
  "app/settings/invoice-settings/page.tsx": 1,
  "app/settings/invoice-templates/page.tsx": 1,
  "app/settings/page.tsx": 2,
  "app/settings/scheduled-reports/page.tsx": 3,
  "app/settings/statutory-values/page.tsx": 2,
  "app/settings/treaty-rates/page.tsx": 2,
  "components/accounting/CostCentresTab.tsx": 2,
  "components/catalogue/ProductServiceFormModal.tsx": 1,
  "components/catalogue/ProductServiceManagerPanel.tsx": 3,
  "components/customers/CustomerFormModal.tsx": 1,
  "components/gst/RegistrationsTab.tsx": 4,
  "components/lookups/FirmHsnLibraryQuickAddModal.tsx": 1,
  "components/notifications/EmailPreferencesPanel.tsx": 1,
  "components/team/MemberAccessDrawer.tsx": 1,
  "app/team/assignments/page.tsx": 1,
  // ── trackers, documents and notices ──
  "app/clients/[id]/documents/page.tsx": 4,
  "app/clients/documents/page.tsx": 2,
  "app/documents/page.tsx": 2,
  "app/income-tax/notices/page.tsx": 5,
  "app/clients/[id]/compliance/page.tsx": 2,
  "app/clients/[id]/lifecycle/page.tsx": 5,
  "app/tasks/page.tsx": 2,
  "app/workflows/page.tsx": 1,
  // ── client health, relationships, intelligence ──
  "app/clients/[id]/ai-insights/page.tsx": 1,
  "app/clients/[id]/health/page.tsx": 4,
  "app/clients/[id]/relationships/page.tsx": 2,
  "app/health/[client_id]/HealthDetailClient.tsx": 2,
  "app/health/alerts/page.tsx": 1,
  "app/health/page.tsx": 1,
  "app/knowledge/page.tsx": 1,
  "app/memory/page.tsx": 1,
  "app/relationships/[entity_id]/EntityDetailClient.tsx": 2,
  "app/relationships/cross-client/page.tsx": 2,
  "app/relationships/page.tsx": 1,
  // ── communication and engagement ──
  "app/client-portal/page.tsx": 5,
  "app/clients/[id]/portal/page.tsx": 1,
  "app/engagements/page.tsx": 10,
  "app/notifications/page.tsx": 1,
  "app/pipeline/page.tsx": 1,
  "app/sign/page.tsx": 2,
  "components/portal/TaxDeclarationTab.tsx": 1,
  // ── platform administration and the practice's own profile ──
  "app/platform/page.tsx": 2,
  "app/practice/page.tsx": 2,
};

/** The screens that post, settle, pay, issue, run payroll or record a filing. A
 *  screen on this list may NOT appear in BASELINE: it is the half of the table
 *  somebody would otherwise "fix" by adding the file's count to it. */
const MONEY_SCREENS = [
  "components/invoices/InvoiceEditor.tsx",
  "components/purchases/PurchaseBillEditor.tsx",
  "components/purchases/DebitNoteEditor.tsx",
  "components/purchases/PurchaseCreditNoteEditor.tsx",
  "components/purchases/AllocatePaymentModal.tsx",
  "components/purchases/BillsOfEntryTab.tsx",
  "components/purchases/RecurringBills.tsx",
  "components/purchases/RcmDocumentPanel.tsx",
  "components/purchases/LandedCostPanel.tsx",
  "components/sales/SalesCreditNoteEditor.tsx",
  "components/sales/SalesDebitNoteEditor.tsx",
  "components/sales/AllocateReceiptModal.tsx",
  "components/banking/SettleDocumentsModal.tsx",
  "components/banking/EntriesTab.tsx",
  "components/banking/AccountsPanel.tsx",
  // Converting a due post-dated cheque POSTS a receipt or a vendor payment through the
  // ordinary engine, so a second click is a second voucher: the very case this file exists for.
  "components/banking/PostDatedChequesPanel.tsx",
  // Keying the opening balance of the electronic credit ledger moves what a GSTR-3B pays in
  // cash; the ITC-04 panel records the lots of a job-work return; the late-interest panel
  // prepares a draft tax invoice. All three were written after this table was frozen.
  "components/gst/Gstr3bCreditLedger.tsx",
  "components/gst/Itc04Panel.tsx",
  "components/sales/OverdueInterestPanel.tsx",
  "components/accounting/OpeningBalancesTab.tsx",
  "components/fixed-assets/CwipTab.tsx",
  "components/inventory/StockCountSheet.tsx",
  "components/inventory/LocationsAndBatches.tsx",
  "components/payroll/DisburseModal.tsx",
  "components/payroll/StatutoryHandoff.tsx",
  "components/payroll/EmployeeDrawer.tsx",
  "components/currency/FxRatesPanel.tsx",
  "app/clients/[id]/sales/page.tsx",
  "app/clients/[id]/purchases/page.tsx",
  "app/clients/[id]/accounting/page.tsx",
  "app/clients/[id]/fixed-assets/page.tsx",
  "app/clients/[id]/inventory/page.tsx",
  "app/clients/[id]/payroll/page.tsx",
  "app/clients/[id]/compliance/gst/page.tsx",
  "app/clients/[id]/compliance/tds/page.tsx",
  "app/clients/[id]/tax/filing/page.tsx",
  "app/clients/[id]/tax/computation/page.tsx",
  "app/accounting/recurring/page.tsx",
  "app/accounting/retainer/page.tsx",
  "app/accounting/loans/page.tsx",
  "app/approvals/page.tsx",
  "app/billing/page.tsx",
  "app/gst/page.tsx",
  "app/income-tax/page.tsx",
  "app/payroll/people/page.tsx",
  "app/portal/dashboard/page.tsx",
  "app/onboarding/page.tsx",
];

test("the raw async-writing buttons that remain are exactly the frozen table", () => {
  const actual: Record<string, number> = {};
  for (const f of FILES) {
    const n = findRawAsyncButtons(f, source(f)).length;
    if (n > 0) actual[f] = n;
  }
  const grew: string[] = [];
  const fell: string[] = [];
  for (const f of new Set([...Object.keys(actual), ...Object.keys(BASELINE)])) {
    const a = actual[f] ?? 0, b = BASELINE[f] ?? 0;
    if (a > b) grew.push(`${f}: ${a} raw async-writing <button> (table allows ${b})`);
    if (a < b) fell.push(`${f}: ${a} (table says ${b}) — good: lower the entry${a === 0 ? " (delete it)" : ""}`);
  }
  assert.deepEqual(grew, [],
    "a raw <button> that starts an async write has no guard against a repeat click that does not wait for a " +
    "render. Use <Button variant=\"plain\" size=\"none\" onClick={…}> (components/ui/button.tsx) — and RETURN " +
    "the promise from the handler:\n  " + grew.join("\n  "));
  assert.deepEqual(fell, [], "the table may only shrink, and an entry that stopped being true must be deleted:\n  " + fell.join("\n  "));
});

test("the scan is not vacuous", () => {
  const total = Object.values(BASELINE).reduce((s, n) => s + n, 0);
  assert.ok(total >= 90, `the table holds only ${total} — the analysis has probably gone blind`);
  assert.ok(FILES.length > 400, `only ${FILES.length} files walked`);
  const buttons = FILES.reduce((s, f) => s + (source(f).match(/<Button\b/g) ?? []).length, 0);
  assert.ok(buttons >= 300, `only ${buttons} <Button> in the tree — the conversion has been lost`);
});

test("every file named in the table still exists", () => {
  for (const f of Object.keys(BASELINE)) assert.ok(FILES.includes(f), `${f} is in the table but is gone`);
});

test("no <Button> starts an async write and drops the promise", () => {
  const found: string[] = [];
  for (const f of FILES) {
    for (const h of findDroppedPromises(f, source(f))) {
      found.push(`${f}:${h.line}  onClick reaches ${h.handler} (${h.write}) without returning its promise`);
    }
  }
  assert.deepEqual(found, [],
    "Button can only hold a promise it is handed. `() => { save(); }` and `() => void save()` discard it, so the " +
    "guard is released on the same tick. Write `() => save()` (or return it):\n  " + found.join("\n  "));
});

test("a screen that writes money or posts has no raw async-writing button and is not in the table", () => {
  for (const f of MONEY_SCREENS) {
    assert.ok(FILES.includes(f), `${f} is named as a money screen and does not exist`);
    assert.equal(f in BASELINE, false, `${f} writes money or posts: it may not be added to the table`);
    assert.equal(findRawAsyncButtons(f, source(f)).length, 0, f);
    assert.match(source(f), /\bButton\b/, `${f} should be using the Button primitive`);
  }
});

// ═════════════════════════════════════════════════════════════════════════════
// WHAT THE ANALYSIS CANNOT SEE, HELD DIRECTLY
// ═════════════════════════════════════════════════════════════════════════════

test("the journal editor's three save buttons are Buttons on one shared flight, and none is raw", () => {
  // The editor receives `onSave` as a PROP, so the analysis above is blind to it.
  const src = source("components/journal/JournalEditor.tsx");
  const saveButtons = [...src.matchAll(/<Button\b[\s\S]*?onClick=\{\(\) => handleSave\("(\w+)"\)\}/g)].map((m) => m[1]);
  assert.deepEqual(saveButtons.sort(), ["correct", "draft", "post"]);
  assert.equal([...src.matchAll(/<Button\b[^>]*flight=\{flight\}/g)].length, 3, "one flight over all three");
  assert.doesNotMatch(src.replace(/<Button\b[\s\S]*?<\/Button>/g, ""), /<button[^>]*handleSave\(/,
    "a raw <button> calling handleSave has no guard");
  // …and the page hands the promise back, resolving true only on a save.
  const page = source("app/clients/[id]/accounting/journal/[entryId]/edit/_page.tsx");
  assert.match(page, /async function handleSave\([\s\S]*?\): Promise<boolean>/);
  assert.match(page, /finally\s*\{\s*if \(!saved\) setSaving\(false\);/,
    "a successful save leaves `saving` up while the navigation lands, or Post Entry re-enables for exactly that moment");
});

test("a submit control that takes its handler as a PROP is a Button too", () => {
  // The analysis above reads handlers declared in the SAME file, so a shared
  // `ModalActions` / `Actions` / `Shell` whose `onSubmit` arrives as a prop is
  // invisible to it — and those are the controls behind Record Payment, Create
  // Credit Note and Create Debit Note. The rule is stated on the prop's NAME:
  // a raw <button> whose handler is `onSubmit`, `onSave`, `onAdd`… is a write
  // somebody else wrote, and it is held by the primitive or not at all.
  const PROP_WRITE =
    /<button\b[^>]*onClick=\{(?:props\.)?on(?:Submit|Save|Add|Confirm|Post|Issue|Create|Apply|Record|Send|Settle|Allocate|Pay|Prepare)\w*\}/g;
  /** Like BASELINE, a table that may only shrink: note and entity editors, none
   *  of which writes a figure. */
  const PROP_BASELINE: Record<string, number> = {
    "app/clients/[id]/reports/ratios/page.tsx": 2,       // the Ratios note's wording and its principal
    "app/relationships/[entity_id]/EntityDetailClient.tsx": 1,
    "app/relationships/page.tsx": 1,
  };
  const actual: Record<string, number> = {};
  for (const f of FILES) {
    const n = (stripComments(source(f)).match(PROP_WRITE) ?? []).length;
    if (n > 0) actual[f] = n;
  }
  assert.deepEqual(actual, PROP_BASELINE,
    "a raw <button> whose handler is a prop named onSubmit/onSave/onAdd… is a write somebody else wrote. Use " +
    "<Button variant=\"plain\" size=\"none\" onClick={onSubmit}> and type the prop `() => unknown` so the caller's " +
    "promise reaches it. The table may only shrink.");
});
