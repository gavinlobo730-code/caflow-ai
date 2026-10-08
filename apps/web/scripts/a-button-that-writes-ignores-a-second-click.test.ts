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
import {
  analyseButtons, API_CLIENTS, findAwaitedPropCallbacks, findDroppedPromises, findDroppedPropPromises,
  findForwardedClicks, findRawAsyncButtons, GUARDED_PRIMITIVES, READS_BY_POST, writingClientMethods,
} from "./rawAsyncButtons.ts";
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
  assert.equal(raw(`function F(){ async function s(){ await supabase.from("customers").insert({}); }
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
  // The promise is the value of a short-circuit or a conditional, so it is handed back whichever
  // way the expression goes: `() => id && remove(id)` is how a row's delete is written.
  assert.equal(dropped(`${head} return <Button onClick={() => id && save()}>x</Button>; }`).length, 0, "&&");
  assert.equal(dropped(`${head} return <Button onClick={() => id ? save() : undefined}>x</Button>; }`).length, 0, "?:");
  assert.equal(dropped(`${head} return <Button onClick={() => { return id && save(); }}>x</Button>; }`).length, 0, "return &&");
  assert.equal(dropped(`${head} return <Button onClick={() => { id && save(); }}>x</Button>; }`).length, 1,
    "a short-circuit used as a STATEMENT discards its value");
  assert.equal(dropped(`${head} return <Button onClick={() => save() && other()}>x</Button>; }`).length, 1,
    "the LEFT side is the condition, not what comes back");
});

test("an <EmptyStateAction> is held like a <Button>: found when it drops the promise, held when it returns it, never raw", () => {
  // EmptyStateAction renders the Button primitive (components/ui/empty-state-action.tsx; the render
  // test beside it proves a second click is ignored), so it is a Button here and not a raw one. Before
  // it was named, a screen could write `onClick={() => void save()}` on one, drop the promise the
  // primitive needs, and no ratchet saw it: four sites did, and the ratchet read 0 of them.
  const head = `function F(){ async function save(){ await api.accounting.createAccount(1); }`;
  const action = (onClick: string) =>
    `${head} return <EmptyStateAction requires={["accounting", "write"]} label="Post" onClick={${onClick}} />; }`;
  assert.equal(dropped(action("save")).length, 0, "the async function itself");
  assert.equal(dropped(action("() => save()")).length, 0, "an arrow returning it");
  assert.equal(dropped(action("() => save().then(() => 1)")).length, 0, "a chain on it");
  assert.equal(dropped(action("() => void save()")).length, 1, "void");
  assert.equal(dropped(action("() => { save(); }")).length, 1, "a statement");
  assert.equal(raw(action("save")).length, 0, "it is not a raw <button>");
  assert.equal(raw(action("() => void save()")).length, 0, "and dropping the promise is the dropped-promise rule's, not the raw one's");
  assert.equal(analyseButtons("t.tsx", action("save")).buttons[0].tag, "EmptyStateAction");
  // a click that only opens a form writes nothing, so there is nothing to hold
  assert.equal(dropped(`function F(){ return <EmptyStateAction requires="anyone" label="New" onClick={() => setOpen(true)} />; }`).length, 0);
});

test("a component the analysis treats as a guarded Button really renders the Button primitive", () => {
  // The analysis equates these tags with <Button>, which is only true while each one's source hands
  // its click to the primitive. Held here so the equivalence cannot rot silently: a primitive that
  // went back to a raw <button> would still read as guarded in every table below.
  for (const tag of GUARDED_PRIMITIVES.filter((t) => t !== "Button")) {
    const file = {
      EmptyStateAction: "components/ui/empty-state-action.tsx",
    }[tag as string];
    assert.ok(file, `${tag} is treated as a guarded Button and has no source recorded here`);
    const src = stripComments(source(file));
    assert.match(src, /import \{ Button \} from "@\/components\/ui\/button"/, `${file} must import the Button primitive`);
    assert.match(src, /<Button\b[^>]*onClick=/, `${file} must hand its click to <Button>`);
    assert.doesNotMatch(src, /<button\b/, `${file} must not render a raw <button>`);
  }
});

test("the analysis exposes the node a fix has to rewrite", () => {
  const { buttons } = analyseButtons("t.tsx", `function F(){ async function save(){ await api.accounting.createAccount(1); }
    return <Button onClick={() => { save(); }}>x</Button>; }`);
  assert.equal(buttons[0].dropSites.length, 1);
});

// ═════════════════════════════════════════════════════════════════════════════
// WHICH CLIENT METHOD WRITES IS READ OFF THE CLIENT, NOT OFF ITS NAME
// ═════════════════════════════════════════════════════════════════════════════

test("a client method that sends a POST is a write whatever it is called, at any depth, on any client", () => {
  // The frozen table below was a number the analysis could not make true: the first version asked
  // whether a method's NAME began with a verb from a list, on a chain of exactly `api.<ns>.<verb>`.
  // `invoices.fromEngagement` (Raise Invoice), `yearEndApi.notes.generateAll` (Generate All Notes)
  // and `api.banking.entries.pass` (Pass, which books a bank line) matched neither limb, so the
  // screens that held them read as having no write and a money screen carried raw buttons while
  // its own guard said it carried none.
  assert.equal(raw(`function F(){ async function s(){ await api.invoices.fromEngagement(1); }
    return <button onClick={s}>x</button>; }`).length, 1, "a verb nobody listed");
  assert.equal(raw(`function F(){ async function s(){ await yearEndApi.notes.generateAll(1); }
    return <button onClick={s}>x</button>; }`).length, 1, "a second client");
  assert.equal(raw(`function F(){ async function s(){ await partyCreditsApi.apply({}); }
    return <button onClick={s}>x</button>; }`).length, 1, "a third, one level deep");
  assert.equal(raw(`function F(){ async function s(){ await api.accounting.fxRevaluation.run("c", {}); }
    return <button onClick={s}>x</button>; }`).length, 1, "a namespace inside a namespace");
  assert.equal(dropped(`function F(){ async function s(){ await api.banking.entries.pass("t"); }
    return <Button onClick={() => { s(); }}>Pass</Button>; }`).length, 1, "and the dropped-promise rule sees it too");
});

test("a client method that only reads is not a write, a POST that only computes is named, and an unknown chain falls back to its verb", () => {
  assert.equal(raw(`function F(){ async function s(){ await api.invoices.downloadPdf(1); }
    return <button onClick={s}>x</button>; }`).length, 0, "a GET download");
  assert.equal(raw(`function F(){ async function s(){ await api.accounting.fxRevaluation.preview("c", {}); }
    return <button onClick={s}>Preview</button>; }`).length, 0, "a preview is a POST that writes nothing");
  assert.equal(raw(`function F(){ async function s(){ await api.notAMethodTheClientHas.createThing(1); }
    return <button onClick={s}>x</button>; }`).length, 1, "a chain the clients do not define is judged by its verb, as before");
  assert.equal(raw(`function F(){ async function s(){ await api.notAMethodTheClientHas.listThings(); }
    return <button onClick={s}>x</button>; }`).length, 0);
});

test("the writing methods are read from the client files, and each client is registered", () => {
  const writers = writingClientMethods();
  assert.ok(writers.size >= 330, `only ${writers.size} writing client methods found — the derivation has probably gone blind`);
  for (const must of [
    "api.invoices.fromEngagement", "api.banking.entries.pass", "api.accounting.fxRevaluation.run",
    "api.clients.permanentDelete", "api.billing.run", "yearEndApi.notes.generateAll", "partyCreditsApi.apply",
  ]) assert.ok(writers.has(must), `${must} sends a mutating HTTP method and is not in the derived set`);
  for (const mustNot of ["api.invoices.downloadPdf", "api.accounting.fxRevaluation.preview"]) {
    assert.equal(writers.has(mustNot) && !(mustNot in READS_BY_POST), false, `${mustNot} reads`);
  }
  // A client object added under lib/api and not named in API_CLIENTS is a client the analysis cannot see.
  const declared: string[] = [];
  for (const f of readdirSync(join(WEB, "lib/api")).filter((n) => n.endsWith(".ts"))) {
    for (const m of readFileSync(join(WEB, "lib/api", f), "utf8").matchAll(/^export const (api|[A-Za-z]+Api)\s*=\s*\{/gm)) {
      declared.push(m[1]);
    }
  }
  assert.deepEqual(declared.sort(), Object.keys(API_CLIENTS).sort(),
    "every exported API client object must be named in API_CLIENTS (scripts/rawAsyncButtons.ts)");
  for (const [root, rel] of Object.entries(API_CLIENTS)) {
    assert.match(readFileSync(join(WEB, rel), "utf8"), new RegExp(`export const ${root}\\s*=`), `${root} is not defined in ${rel}`);
  }
});

test("every method named as a read-by-POST is real and really sends a POST", () => {
  // A stale entry would quietly exempt a method that no longer exists — or one that has since
  // started to write. Each is checked against the same derivation that would otherwise count it.
  const writers = writingClientMethods();
  for (const [method, why] of Object.entries(READS_BY_POST)) {
    assert.ok(writers.has(method), `${method} is named a read-by-POST but the client has no POST method by that name`);
    assert.ok(why.length > 15, `${method} needs its reason written down`);
  }
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
  "app/clients/[id]/lifecycle/page.tsx": 4,
  "app/tasks/page.tsx": 2,
  "app/workflows/page.tsx": 1,
  // ── client health, relationships, intelligence ──
  "app/clients/[id]/ai-insights/page.tsx": 1,
  "app/clients/[id]/health/page.tsx": 4,
  "app/health/[client_id]/HealthDetailClient.tsx": 2,
  "app/health/alerts/page.tsx": 1,
  "app/health/page.tsx": 1,
  "app/knowledge/page.tsx": 1,
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
  "app/practice/page.tsx": 1,
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
  // Named when the analysis learned which client methods write (see writingClientMethods): each
  // was reading as having NO async write, and each posts, certifies or registers a statutory figure.
  // The FX revaluation POSTS journals through the kernel; the ITC register records a Rule 37/42/43
  // reversal that GSTR-3B Table 4(B) reads; the 2B panel makes a draft purchase bill through the bill
  // engine; the three bank modals post, split or certify a reconciliation; Rules trusts a pattern
  // that then posts with nobody watching; a year-end adjustment posts a journal.
  "components/accounting/FxRevaluationPanel.tsx",
  "components/gst/ItcRegisterTab.tsx",
  "components/gst/CreateDraftBillFrom2B.tsx",
  "components/banking/SplitAcrossLedgersModal.tsx",
  "components/banking/ReconcileTab.tsx",
  "components/banking/EntryDetailModal.tsx",
  "components/banking/RulesTab.tsx",
  "app/clients/[id]/year-end/[engagementId]/adjustments/_page.tsx",
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

// ═════════════════════════════════════════════════════════════════════════════
// WHERE THE WRITE IS SOMEBODY ELSE'S (the money-editor drive, PRE-A-015)
// ═════════════════════════════════════════════════════════════════════════════
//
// Everything above reads a handler declared in the SAME file. Driving the money editors in a real browser found
// eight places where a click reaches a write that is in a CALLER, and in every one a second click in the same tick
// sent a second request: the Issue of an invoice (which posts its journal) and of each of the four notes, the
// Receive of a purchase bill (which posts its journal, withholds the TDS and claims the credit), and the Delete
// Draft of an invoice and of a bill. The source guard had read all of them as clean, because:
//
//   * a drawer's `Action` was a raw `<button onClick={onClick}>` typed `() => void`, six copies of it, and every
//     caller's write reached a button that held nothing;
//   * a confirmation dialog's handler `await onConfirm()`s the caller's delete, and `onConfirm` is a prop, not a
//     function the analysis can open;
//   * the page handed the drawer `onIssue={(id) => { setDetailId(null); issueInvoice(id); }}`, which STARTS the
//     write and drops its promise, so even a button that held would have been released on the same tick.
//
// The three rules below are stated on those SHAPES, derived from the syntax tree of every file, so a seventh copy
// of the primitive or a fourth dialog is caught by the check that caught the first.

test("a raw button handed its component's own onClick is found, and a Button doing the same is not", () => {
  const forwarded = (src: string) => findForwardedClicks("t.tsx", src);
  assert.equal(forwarded(`function Action({ children, onClick }) { return <button onClick={onClick}>{children}</button>; }`).length, 1,
    "the destructured prop");
  assert.equal(forwarded(`function Action(props) { return <button onClick={props.onClick}>x</button>; }`).length, 1, "props.onClick");
  assert.equal(forwarded(`function Action({ onClick: go }) { return <button onClick={go}>x</button>; }`).length, 1, "a renamed binding");
  assert.equal(forwarded(`function List({ rows, onClick }) { return rows.map((r) => <button key={r} onClick={onClick}>x</button>); }`).length, 1,
    "a button inside a .map callback sits inside the component all the same");
  // what it must leave alone
  assert.equal(forwarded(`function Action({ onClick }) { return <Button onClick={onClick}>x</Button>; }`).length, 0, "a Button holds it");
  assert.equal(forwarded(`function A({ onClose }) { return <button onClick={onClose}>x</button>; }`).length, 0, "another prop is not this rule's");
  assert.equal(forwarded(`function A() { const onClick = () => 1; return <button onClick={onClick}>x</button>; }`).length, 0,
    "a local function named onClick is not a prop");
  assert.equal(forwarded(`function A({ onClick }) { return <button onClick={() => onClick()}>x</button>; }`).length, 0,
    "wrapped in an arrow it is the existing rules' business");
});

test("a raw button whose handler awaits a callback its component was handed is found", () => {
  const awaited = (src: string) => findAwaitedPropCallbacks("t.tsx", src);
  const dialog = (handler: string) => `
    function Dialog({ onConfirm, onClose }) {
      ${handler}
      return <button onClick={handle}>Delete</button>;
    }`;
  assert.equal(awaited(dialog(`async function handle() { setBusy(true); try { await onConfirm(); } finally { setBusy(false); } }`)).length, 1,
    "the confirmation dialog");
  assert.equal(awaited(dialog(`const handle = async () => { await onConfirm(); };`)).length, 1, "an async arrow");
  assert.equal(awaited(dialog(`async function handle() { await somethingLocal(); }`)).length, 0, "awaiting a local function is not a prop");
  assert.equal(awaited(dialog(`function handle() { onConfirm(); }`)).length, 0, "a sync handler is not async");
  assert.equal(awaited(`function D({ onConfirm }) { async function handle() { await onConfirm(); } return <Button onClick={handle}>x</Button>; }`).length, 0,
    "a Button holds it");
});

test("a function handed to a component's on… prop that starts a write and drops the promise is found", () => {
  const dropped = (src: string) => findDroppedPropPromises("t.tsx", src);
  const page = (prop: string) => `
    function Page() {
      async function issueInvoice(id) { await apiCall("/api/x/" + id, "POST"); }
      return <Drawer ${prop} />;
    }`;
  assert.equal(dropped(page(`onIssue={(id) => { setDetailId(null); issueInvoice(id); }}`)).length, 1, "a statement");
  assert.equal(dropped(page(`onIssue={(id) => void issueInvoice(id)}`)).length, 1, "void");
  assert.equal(dropped(page(`onIssue={(id) => { setDetailId(null); return issueInvoice(id); }}`)).length, 0, "returned");
  assert.equal(dropped(page(`onIssue={(id) => issueInvoice(id)}`)).length, 0, "an expression body is returned");
  assert.equal(dropped(page(`onIssue={(id) => { setDetailId(null); }}`)).length, 0, "no write");
  assert.equal(dropped(page(`onIssue={issueInvoice}`)).length, 0, "a named function is handed over whole");
  assert.equal(dropped(`function P(){ async function load(){ await api.accounting.list(); } return <Drawer onDone={() => { load(); }} />; }`).length, 0,
    "a READ dropped is not this rule's");
  assert.equal(dropped(`function P(){ async function issue(){ await apiCall("/x", "POST"); } return <div onClick={() => { issue(); }} />; }`).length, 0,
    "a DOM event on a native tag is the raw-button rule's, not this one's");
  assert.equal(dropped(`function P(){ async function issue(){ await apiCall("/x", "POST"); } return <Button onClick={() => { issue(); }}>x</Button>; }`).length, 0,
    "a guarded primitive's own onClick is the dropped-promise rule's");
});

/**
 * The raw buttons that await a prop callback and are NOT on a money screen, each with why a second click costs
 * nothing a person cannot see. A table that may only shrink; a money screen may not be on it.
 */
const AWAITS_A_PROP_CALLBACK: Record<string, { count: number; why: string }> = {
  "app/settings/email-templates/page.tsx": { count: 1, why: "saves a template by key: a second save writes the same row again" },
  "app/team/page.tsx": { count: 1, why: "changes a member's role to the value shown: a second change is the same change" },
  "components/CsvImportModal.tsx": {
    count: 1,
    why: "NOT harmless: a second Import in one tick imports the file twice. It is shared by ten screens and is "
      + "the upload screens' to convert (PRE-A-001); named here so the rule does not read it as clean",
  },
};

/** `on…` props given a function that starts a write and drops the promise, where nothing holds a click. */
const DROPS_A_PROP_PROMISE: Record<string, { count: number; why: string }> = {
  "app/copilot/page.tsx": { count: 1, why: "a thumbs rating on a reply: nothing is posted and a repeat records the same rating" },
  "app/settings/ai/page.tsx": { count: 1, why: "the provider check spends a few tokens and is rate limited by the server (3 a minute)" },
};

function treeFinds(finder: (f: string, s: string) => Array<{ line: number }>): Record<string, number> {
  const found: Record<string, number> = {};
  for (const f of FILES) {
    const n = finder(f, source(f)).length;
    if (n > 0) found[f] = n;
  }
  return found;
}

function assertEqualToTable(found: Record<string, number>, table: Record<string, { count: number; why: string }>, what: string) {
  const grew: string[] = [];
  const fell: string[] = [];
  for (const f of new Set([...Object.keys(found), ...Object.keys(table)])) {
    const a = found[f] ?? 0, b = table[f]?.count ?? 0;
    if (a > b) grew.push(`${f}: ${a} (table allows ${b})`);
    if (a < b) fell.push(`${f}: ${a} (table says ${b}) — good: lower the entry${a === 0 ? " (delete it)" : ""}`);
  }
  assert.deepEqual(grew, [], what + "\n  " + grew.join("\n  "));
  assert.deepEqual(fell, [], "the table may only shrink, and an entry that stopped being true must be deleted:\n  " + fell.join("\n  "));
}

test("no raw button forwards its component's onClick: a generic button primitive is a Button", () => {
  const found = treeFinds((f, s) => findForwardedClicks(f, s));
  assert.deepEqual(found, {},
    "a component that takes `onClick` and hands it to a raw <button> holds nothing: every caller's write, an Issue or a " +
    "Receive that posts a journal included, reaches a button that lets a second click through. Render " +
    "<Button variant=\"plain\" size=\"none\" onClick={onClick}> and type the prop `() => unknown`:\n  " +
    Object.keys(found).join("\n  "));
});

test("no raw button awaits a callback its component was handed, outside the table", () => {
  assertEqualToTable(treeFinds((f, s) => findAwaitedPropCallbacks(f, s)), AWAITS_A_PROP_CALLBACK,
    "a raw <button> whose handler `await`s a prop callback (`await onConfirm()`) performs a write the same-file analysis " +
    "cannot see, and a second click in the same tick performs it twice. Use <Button …> (the handler already returns the " +
    "promise):");
  for (const [f, { why }] of Object.entries(AWAITS_A_PROP_CALLBACK)) {
    assert.ok(why.length > 20, `${f} needs its reason written down`);
    assert.equal(MONEY_SCREENS.includes(f), false, `${f} is a money screen: it may not be on the table`);
  }
});

test("nothing hands a component an on… function that starts a write and drops the promise, outside the table", () => {
  assertEqualToTable(treeFinds((f, s) => findDroppedPropPromises(f, s)), DROPS_A_PROP_PROMISE,
    "`onIssue={(id) => { setDetailId(null); issueInvoice(id); }}` starts the write and discards the promise, so the " +
    "receiving component has nothing to hold a repeat click on. Return it: `{ setDetailId(null); return issueInvoice(id); }` " +
    "(and type the prop `=> unknown`):");
  for (const [f, { why }] of Object.entries(DROPS_A_PROP_PROMISE)) {
    assert.ok(why.length > 20, `${f} needs its reason written down`);
    assert.equal(MONEY_SCREENS.includes(f), false, `${f} is a money screen: it may not be on the table`);
  }
});

test("the drawers that take a caller's write type the prop so the promise reaches the button", () => {
  // A prop typed `=> void` tells the caller nobody reads the result; typed `=> unknown` it says the opposite.
  for (const [file, prop] of [
    ["components/invoices/InvoiceViewDrawer.tsx", "onIssue"],
    ["components/purchases/PurchaseBillViewDrawer.tsx", "onReceive"],
    ["components/sales/SalesCreditNoteViewDrawer.tsx", "onIssue"],
    ["components/sales/SalesDebitNoteViewDrawer.tsx", "onIssue"],
    ["components/purchases/DebitNoteViewDrawer.tsx", "onIssue"],
    ["components/purchases/PurchaseCreditNoteViewDrawer.tsx", "onIssue"],
  ] as const) {
    const declared = new RegExp(`\\b${prop}: \\([^)]*\\) => (\\w+);`).exec(stripComments(source(file)));
    assert.ok(declared, `${file} no longer declares ${prop}`);
    assert.equal(declared![1], "unknown", `${file}: ${prop} is typed => ${declared![1]}; the caller's promise has nowhere to go`);
  }
});
