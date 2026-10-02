// An empty list says what to do next, and the lists that still say only that they
// are empty are a frozen set that can only shrink. Run with:
//   node --experimental-strip-types --test scripts/an-empty-list-says-what-to-do-next.test.ts
//
// WHAT WAS WRONG (frontend_ux-24)
//     A new practice's first look at a screen is usually an empty one. At the commit
//     before this work 130 hand-written paragraphs in 83 files said only "No
//     invoices in this period" or "No suppliers yet." and stopped: no explanation of
//     what the list is for, and the one button that would fix it a few centimetres
//     above, in a toolbar the eye had already left. `EmptyState` existed and
//     `DataTable` already took `emptyAction`; what was missing was an action nobody
//     had to restyle (the seven that existed were seven styles) and nobody could
//     forget to gate.
//
// THE RULES
//   1. A text node that says a list is empty ("No …" ending in found, yet, recorded,
//      available, added or created) is not written by hand. It either becomes an
//      `EmptyState`, or its file is in FROZEN_BARE below with the kind of reason and
//      the reason itself. Asserted as an EQUALITY of per-file counts, so a screen
//      that migrates must come off the list and a new bare paragraph cannot be
//      added by raising a number.
//   2. A `DataTable` that sets `emptyTitle` sets `emptyAction`, or its file is in
//      FROZEN_TABLES.
//   3. An action offered on an empty list is the shared `EmptyStateAction`, which
//      REQUIRES the permission it needs. A raw button in `emptyAction` or in
//      `EmptyState`'s `action` fails unless the file is in FROZEN_RAW_ACTIONS.
//      Offering a Reviewer a "New Invoice" button that ends in a 403 is the
//      defect, and the permission is a required prop so that leaving it out is a
//      type error rather than a review comment.
//   4. Every `href` an empty-state action carries is a route that exists under
//      `app/`. Nothing is offered that leads nowhere, and no new route was added
//      (decision D10: no new page under /clients/[id]; the redirect budget is full).
//
// THE TWO KINDS OF FROZEN ENTRY, AND WHY THEY ARE KEPT APART
//   `nothing-to-do-here`: the absence is the finished state, or is made by something
//   that happens elsewhere (a log, a report's result, a derived register, a history
//   inside a document drawer). There is no list a person could add to.
//   `not-yet-migrated`: a list a person fills, whose next step this change did not
//   wire. These are the debt, and each reason says what is missing.
//   A frozen list that did not say which is which would read as "all of these are
//   fine".
//
// WHAT THIS DOES NOT SAY
//   That the explanation each screen now gives is the right one, or that the layout
//   is good. No browser harness exists, so the rendered behaviour is held by
//   components/ui/empty-state-action.test.ts and lib/table/emptyKind.test.ts, and
//   the screens by tsc and lint, not by a click-through.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";
import { openingTags, topLevelProps } from "./jsxTags.ts";

const WEB = path.resolve(import.meta.dirname, "..");

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    const rel = path.posix.join(dir, e.name);
    if (e.isDirectory()) walk(rel, out);
    else if (e.name.endsWith(".tsx")) out.push(rel);
  }
  return out;
}

const FILES = [...walk("app"), ...walk("components")].sort();
const NOT_A_SCREEN = new Set(["components/ui/states.tsx", "components/ui/data-table.tsx"]);

function code(rel: string): string {
  return stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
}

// ── rule 1: the bare paragraph ──────────────────────────────────────────────

const ABSENCE_WORDS = "found|yet|recorded|available|added|created";
// A JSX text node, possibly over several lines, that opens with "No " and says
// something is missing. Text with an expression in it (`{…}`) is not matched: it is
// composed, and the composed ones here are the ones that already explain themselves.
const BARE = new RegExp(`>\\s*No\\s+[A-Za-z][^<>{}]*?\\b(?:${ABSENCE_WORDS})\\b[^<>{}]*<`, "g");

export function bareParagraphs(src: string): string[] {
  return [...src.matchAll(BARE)].map((m) => m[0].replace(/\s+/g, " "));
}

test("the detector finds each way a screen used to say a list was empty, and only those", () => {
  // one line, a table row, several lines, an entity, a trailing instruction
  assert.equal(bareParagraphs(`<p className="x">No invoices yet</p>`).length, 1);
  assert.equal(bareParagraphs(`<tr><td colSpan={5}>No GSTR-1 returns yet.</td></tr>`).length, 1);
  assert.equal(bareParagraphs(`<p>\n  No payroll runs yet. Compute one\n  under Register first.\n</p>`).length, 1);
  assert.equal(bareParagraphs(`<div>No challans added yet. Click &ldquo;Add&rdquo; to record one.</div>`).length, 1);
  assert.equal(bareParagraphs(`<p>No clients found — add clients first</p>`).length, 1);
  // not a paragraph: a prop is the shared component's own, not a hand-written node
  assert.equal(bareParagraphs(`<EmptyState title="No invoices yet" description="No suppliers found" />`).length, 0);
  // not an absence: no keyword, a composed sentence, or a sentence not opening with "No"
  assert.equal(bareParagraphs(`<option value="">No client</option>`).length, 0);
  assert.equal(bareParagraphs(`<p>No invoices in {period} found</p>`).length, 0);
  assert.equal(bareParagraphs(`<p>There are no invoices yet</p>`).length, 0);
});

// Per-file counts of bare paragraphs, at the commit this work finishes. A kind and a
// reason for each, because a bare list of files says nothing about which are debts.
type Kind = "nothing-to-do-here" | "not-yet-migrated";
type Frozen = { count: number; kind: Kind; reason: string };
const ntd = (count: number, reason: string): Frozen => ({ count, kind: "nothing-to-do-here", reason });
const nym = (count: number, reason: string): Frozen => ({ count, kind: "not-yet-migrated", reason });

const FROZEN_BARE: Record<string, Frozen> = {
  "app/accounting/loans/page.tsx": nym(2, "writes straight over PostgREST under migration 346's Executive-tier rule; no backend [resource, action] pair expresses that tier, so a gate here would be invented rather than read"),
  "app/accounting/receivables/page.tsx": ntd(1, "an ageing list with nothing owed is the good state of a report"),
  "app/client-portal/page.tsx": nym(4, "the CA-facing portal screen: the add control (New Request, upload, the message box) is on the same card and is not wired to the shared action"),
  "app/clients/[id]/accounting/page.tsx": nym(3, "a balance sheet with nothing posted, a books check not yet run (Verify Books sits beside it) and a shared-reports history; the first two need their next step chosen"),
  "app/clients/[id]/ai-insights/page.tsx": ntd(1, "rule-based insights derived from the books; nothing to add"),
  "app/clients/[id]/compliance/gst/page.tsx": ntd(2, "a working panel's own 'not available' note, and the history of returns filed (made by Mark Filed on a return, not here)"),
  "app/clients/[id]/compliance/page.tsx": nym(1, "notices are extracted from an uploaded document and the upload control is elsewhere on the page"),
  "app/clients/[id]/compliance/tds/page.tsx": nym(1, "the deductions register has no add control on this screen: rows come from purchase bills, so the next step is a product decision"),
  "app/clients/[id]/fixed-assets/page.tsx": ntd(1, "a disposal picker with no active asset; the register behind it is where assets are added"),
  "app/clients/[id]/health/page.tsx": nym(1, "a Calculate control sits beside it"),
  "app/clients/[id]/relationships/page.tsx": nym(3, "the next step is the firm's entity registry, an existing route, and is not wired"),
  "app/clients/[id]/sales/page.tsx": ntd(4, "four sub-lists inside a document drawer: histories of what happened to one document, and a pointer at a control in the same drawer"),
  "app/clients/[id]/tax/computation/page.tsx": nym(2, "worksheet panels with their own add form directly above"),
  "app/clients/[id]/tax/filing/page.tsx": ntd(1, "an explanation that a figure has no mapped field in the offline utility; not a list"),
  "app/clients/[id]/year-end/[engagementId]/exports/_page.tsx": nym(1, "'Click Generate above': the Generate control is in the same panel"),
  "app/clients/[id]/year-end/[engagementId]/financial-statements/_page.tsx": nym(2, "'Refresh from ledger': the refresh control is in the same panel"),
  "app/clients/[id]/year-end/[engagementId]/notes/_page.tsx": ntd(1, "one note with no generated content; the editor above it is the action"),
  "app/copilot/page.tsx": ntd(1, "a sidebar of past conversations; the composer beside it is the action"),
  "app/gst/page.tsx": nym(1, "a modal telling a firm with no clients to add some first; the way out is a link to Clients"),
  "app/health/[client_id]/HealthDetailClient.tsx": ntd(1, "a history of overrides"),
  "app/knowledge/page.tsx": nym(1, "article authoring (knowledge:write) is the form on the same page"),
  "app/memory/page.tsx": ntd(1, "client profiles are derived by the product"),
  "app/notifications/whatsapp/page.tsx": ntd(2, "a client picker's no-result and a log of messages sent"),
  "app/payroll/reports/page.tsx": nym(2, "the month review needs a client's run and a run is created in that client's workspace, so the next step depends on choosing a client first"),
  "app/portal/employee/page.tsx": ntd(2, "the employee portal is read-only by owner decision (14-09-2026); there is nothing an employee can add"),
  "app/relationships/[entity_id]/EntityDetailClient.tsx": ntd(2, "derived graph views of one entity"),
  "app/relationships/cross-client/page.tsx": ntd(1, "matches the product derives from the registry; nothing to add"),
  "app/relationships/explorer/page.tsx": ntd(2, "a search result and derived relationships"),
  "app/relationships/intelligence/page.tsx": ntd(3, "summaries the product derives from the registry; nothing to add"),
  "app/relationships/ownership-map/page.tsx": ntd(2, "a graph the product derives from the registry; nothing to add"),
  "app/reports/cash-flow/page.tsx": ntd(1, "a report's own result"),
  "app/reports/page.tsx": ntd(1, "a report's own result"),
  "app/settings/audit-log/page.tsx": ntd(1, "an append-only log; nothing a person can add"),
  "app/settings/scheduled-reports/page.tsx": nym(1, "no role rule on the table (migrations 260 and 261 name it): which role may create a schedule is undecided, so a gate here would be invented"),
  "app/tds/page.tsx": nym(1, "'Generate a draft from the client's Compliance → TDS tab': the target is a per-client screen, so a client has to be chosen first"),
  "app/team/login-history/page.tsx": ntd(1, "an append-only log; nothing a person can add"),
  "app/time/page.tsx": nym(1, "the log form is the card directly above"),
  "app/work/page.tsx": ntd(1, "a personal history of completed work"),
  "app/workflows/page.tsx": ntd(2, "no workflow can be created from the product yet and the sentence says so, and a run history"),
  "components/accounting/OpeningBalancesTab.tsx": nym(1, "the opening-document entry control is on the same tab"),
  "components/banking/AccountsPanel.tsx": ntd(1, "the transactions of one imported statement; the statement is the record"),
  "components/gst/Gstr4AnnualPanel.tsx": ntd(1, "rows derived from the books"),
  "components/gst/Gstr8Panel.tsx": ntd(1, "rows derived from the books"),
  "components/gst/MissingIrnPanel.tsx": ntd(1, "a note on one invoice row that no aggregate turnover is recorded, so the IRN clock is assumed; a caveat on a row, not an empty list"),
  "components/gst/RegistrationPicker.tsx": nym(1, "a one-line note beside a Compute button; the GSTIN is recorded by editing the client on the Clients list, which opens as a modal from a row and has no address of its own to link to (the same reason as RegistrationsTab)"),
  "components/gst/RegistrationsTab.tsx": nym(1, "the GSTIN is recorded on the client record, which is a per-client screen"),
  "components/inventory/LocationsAndBatches.tsx": ntd(1, "a stock movement history, written by documents"),
  "components/inventory/ReorderPanel.tsx": ntd(1, "a cell label: no reorder level is recorded for an item"),
  "components/invoices/InvoiceViewDrawer.tsx": ntd(1, "an activity log inside a document drawer"),
  "components/knowledge/ClientInstructions.tsx": nym(1, "the add control is the form directly above"),
  "components/notifications/EmailPreferencesPanel.tsx": ntd(1, "an unavailable-settings notice, not an empty list"),
  "components/payroll/EmployeeDrawer.tsx": nym(2, "salary revisions and loans: each has its add form in the same drawer"),
  "components/payroll/StatutoryHandoff.tsx": ntd(1, "explains why a liability has no matched bank payment"),
  "components/purchases/DebitNoteViewDrawer.tsx": ntd(1, "an activity log inside a document drawer"),
  "components/purchases/PurchaseBillViewDrawer.tsx": ntd(1, "an activity log inside a document drawer"),
  "components/purchases/PurchaseCreditNoteViewDrawer.tsx": ntd(1, "an activity log inside a document drawer"),
  "components/sales/PriceListsPanel.tsx": nym(1, "no item priced on a list: the picker and Set price are the form directly above (its customers paragraph is an EmptyState with Add Customer)"),
  "components/sales/SalesCreditNoteViewDrawer.tsx": ntd(1, "an activity log inside a document drawer"),
  "components/sales/SalesDebitNoteViewDrawer.tsx": ntd(1, "an activity log inside a document drawer"),
};

test("a list says what to do next, or its file is in the frozen set with a reason", () => {
  const actual: Record<string, number> = {};
  for (const f of FILES) {
    if (NOT_A_SCREEN.has(f)) continue;
    const n = bareParagraphs(code(f)).length;
    if (n) actual[f] = n;
  }
  const expected = Object.fromEntries(Object.entries(FROZEN_BARE).map(([f, v]) => [f, v.count]));
  const added = Object.keys(actual).filter((f) => !(f in expected));
  const migrated = Object.keys(expected).filter((f) => !(f in actual));
  const moved = Object.keys(actual).filter((f) => f in expected && actual[f] !== expected[f]);
  assert.deepEqual(added, [],
    "a hand-written 'No …' paragraph was added: use EmptyState (components/ui/states.tsx) with an EmptyStateAction, or freeze it here with a reason");
  assert.deepEqual(migrated, [],
    "these files no longer have a bare paragraph: take them OFF the frozen list (it only shrinks)");
  assert.deepEqual(moved.map((f) => `${f}: ${expected[f]} -> ${actual[f]}`), [],
    "the count in a frozen file changed: lower it if one was migrated, and a new one must not be added");
});

test("every frozen entry says which kind it is and why, and the two kinds are both real", () => {
  const kinds = new Set<string>();
  for (const [f, v] of Object.entries(FROZEN_BARE)) {
    assert.ok(v.reason.length >= 20, `${f}: a reason is a sentence, not a word`);
    assert.ok(v.count >= 1, `${f}: a zero count is a migrated file`);
    kinds.add(v.kind);
  }
  assert.deepEqual([...kinds].sort(), ["not-yet-migrated", "nothing-to-do-here"]);
});

// ── rule 2: a table that names its empty state offers a next step ───────────

const FROZEN_TABLES: Record<string, { count: number; kind: Kind; reason: string }> = {
  "app/clients/[id]/accounting/page.tsx": { count: 2, kind: "not-yet-migrated", reason: "'No accounts found' (accounts are seeded from the firm's chart, whose import is an existing route that is not yet offered) and an account's ledger range with no posting" },
  "app/clients/[id]/inventory/page.tsx": { count: 1, kind: "not-yet-migrated", reason: "products are marked in the Product/Service catalogue on another tab, and that tab's address has not been confirmed" },
  "app/clients/[id]/reports/ageing/page.tsx": { count: 1, kind: "nothing-to-do-here", reason: "'Nothing outstanding' is the good state of an ageing report" },
  "app/health/page.tsx": { count: 1, kind: "nothing-to-do-here", reason: "a score category with no client in it" },
  "app/notifications/page.tsx": { count: 1, kind: "nothing-to-do-here", reason: "'You're all caught up'" },
  "app/platform/page.tsx": { count: 1, kind: "nothing-to-do-here", reason: "the platform operator's list of firms, which sign themselves up" },
  "app/risks/page.tsx": { count: 1, kind: "nothing-to-do-here", reason: "a register computed from the compliance data; nothing to add" },
};

function tablesWithoutAnAction(): Record<string, number> {
  const out: Record<string, number> = {};
  for (const f of FILES) {
    for (const tag of openingTags(code(f), "DataTable")) {
      const props = topLevelProps(tag, "DataTable");
      if (props.includes("emptyTitle") && !props.includes("emptyAction")) out[f] = (out[f] ?? 0) + 1;
    }
  }
  return out;
}

test("a table that names its empty state also offers a next step, or is frozen with a reason", () => {
  const actual = tablesWithoutAnAction();
  const expected = Object.fromEntries(Object.entries(FROZEN_TABLES).map(([f, v]) => [f, v.count]));
  assert.deepEqual(actual, expected,
    "a DataTable with an emptyTitle and no emptyAction was added (or one was migrated and must come off FROZEN_TABLES)");
});

test("the table detector reads a whole tag, including a `>` inside a value", () => {
  const tag = openingTags(
    `<DataTable data={rows} emptyDescription={a > b ? "x" : "y"} emptyTitle="No rows" emptyAction={<X />} />`,
    "DataTable")[0];
  assert.ok(tag.endsWith("/>"), "the tag ends where the tag ends, not at the first >");
  const props = topLevelProps(tag, "DataTable");
  assert.ok(props.includes("emptyTitle") && props.includes("emptyAction") && props.includes("emptyDescription"));
  // a prop that only appears inside another prop's value is not the tag's own
  const nested = topLevelProps(openingTags(`<DataTable emptyDescription={"emptyAction"} />`, "DataTable")[0], "DataTable");
  assert.deepEqual(nested, ["emptyDescription"]);
});

// ── rule 3: an offered action goes through the shared, permission-bound one ──

const FROZEN_RAW_ACTIONS: Record<string, string> = {
  "app/clients/[id]/purchases/bills/[billId]/edit/_page.tsx": "a way back to the list the page came from, offered to anyone who could open the page; it creates nothing",
  "app/clients/[id]/purchases/credit-notes/[pcnId]/edit/_page.tsx": "a way back to the list the page came from; it creates nothing",
  "app/clients/[id]/purchases/debit-notes/[dnId]/edit/_page.tsx": "a way back to the list the page came from; it creates nothing",
  "app/clients/[id]/sales/credit-notes/[cnId]/edit/_page.tsx": "a way back to the list the page came from; it creates nothing",
  "app/clients/[id]/sales/debit-notes/[sdnId]/edit/_page.tsx": "a way back to the list the page came from; it creates nothing",
  "app/clients/[id]/sales/invoices/[invoiceId]/edit/_page.tsx": "a way back to the list the page came from; it creates nothing",
  "components/client/ClientResolutionGate.tsx": "a way back to the client list from a client that could not be resolved; it creates nothing",
};

/** The text of one prop's `{…}` value on a tag, or null when the prop is absent. */
function propValue(tag: string, name: string): string | null {
  const m = new RegExp(`\\s${name}=`).exec(tag);
  if (!m) return null;
  let i = m.index + m[0].length;
  if (tag[i] !== "{") return "<literal>";
  let depth = 0;
  let quote: string | null = null;
  let k = i;
  for (; k < tag.length; k++) {
    const c = tag[k];
    if (quote) { if (c === "\\") { k++; continue; } if (c === quote) quote = null; continue; }
    if (c === '"' || c === "'" || c === "`") { quote = c; continue; }
    if (c === "{") depth++;
    else if (c === "}") { depth--; if (depth === 0) break; }
  }
  return tag.slice(i, k + 1);
}

/** True when `value` is the shared row of actions, directly or through a const in `src`. */
function goesThroughTheSharedAction(value: string, src: string): boolean {
  if (value.includes("EmptyStateActions")) return true;
  const id = /^\{\s*([A-Za-z_]\w*)\s*\}$/.exec(value)?.[1];
  if (!id) return false;
  const def = new RegExp(`const ${id}\\s*=`).exec(src);
  return def ? src.slice(def.index, def.index + 700).includes("EmptyStateActions") : false;
}

test("an action offered on an empty list is the shared EmptyStateAction, or the file is frozen", () => {
  const raw = new Set<string>();
  for (const f of FILES) {
    if (NOT_A_SCREEN.has(f)) continue;
    const src = code(f);
    for (const tag of openingTags(src, "EmptyState")) {
      const v = propValue(tag, "action");
      if (v !== null && !goesThroughTheSharedAction(v, src)) raw.add(f);
    }
    for (const tag of openingTags(src, "DataTable")) {
      const v = propValue(tag, "emptyAction");
      if (v !== null && !goesThroughTheSharedAction(v, src)) raw.add(f);
    }
  }
  assert.deepEqual([...raw].sort(), Object.keys(FROZEN_RAW_ACTIONS).sort(),
    "an empty-list action that does not go through EmptyStateActions (and so names no permission) was added, or a frozen one was migrated");
  for (const [f, reason] of Object.entries(FROZEN_RAW_ACTIONS)) assert.ok(reason.length >= 20, f);
});

test("every EmptyStateAction names the permission it needs", () => {
  let seen = 0;
  const missing: string[] = [];
  for (const f of FILES) {
    for (const tag of openingTags(code(f), "EmptyStateAction")) {
      seen++;
      if (!topLevelProps(tag, "EmptyStateAction").includes("requires")) missing.push(f);
    }
  }
  assert.ok(seen >= 80, `only ${seen} EmptyStateAction found: the scan has gone blind`);
  assert.deepEqual(missing, []);
  // and the component itself makes it a type error to leave it out
  const component = fs.readFileSync(path.join(WEB, "components/ui/empty-state-action.tsx"), "utf8");
  const common = /type Common = \{[\s\S]*?\n\};/.exec(component)?.[0] ?? "";
  assert.match(common, /\n  requires: EmptyActionRequires;/, "`requires` must not be optional");
  assert.doesNotMatch(common, /requires\?:/);
});

test("the permission pairs an action names are pairs the backend actually has", () => {
  // core/permissions.py is the authority; a pair it does not hold is denied for every
  // role, so an action naming one is never offered to anybody and nothing says so.
  const py = fs.readFileSync(path.resolve(WEB, "../api/core/permissions.py"), "utf8");
  const block = py.slice(py.indexOf("PERMISSIONS: dict"));
  const held = new Set<string>();
  let resource = "";
  for (const line of block.split("\n")) {
    const r = /^    "([a-z_]+)": \{/.exec(line);
    if (r) { resource = r[1]; continue; }
    const a = /^        "([a-z_]+)":/.exec(line);
    if (a && resource) held.add(`${resource}:${a[1]}`);
  }
  assert.ok(held.size > 100, "the permission table was not read");
  const unknown = new Set<string>();
  let seen = 0;
  for (const f of FILES) {
    for (const tag of openingTags(code(f), "EmptyStateAction")) {
      const m = /requires=\{\[\s*"([a-z_]+)"\s*,\s*"([a-z_]+)"\s*\]\}/.exec(tag);
      if (!m) continue;
      seen++;
      if (!held.has(`${m[1]}:${m[2]}`)) unknown.add(`${f}: ${m[1]}:${m[2]}`);
    }
  }
  assert.ok(seen >= 80, "the scan has gone blind");
  assert.deepEqual([...unknown], []);
});

// ── rule 4: no action leads nowhere ─────────────────────────────────────────

function appRoutes(): string[][] {
  const routes: string[][] = [];
  const visit = (dir: string, segs: string[]) => {
    for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
      if (e.isDirectory()) visit(path.posix.join(dir, e.name), [...segs, e.name]);
      else if (e.name === "page.tsx") routes.push(segs);
    }
  };
  visit("app", []);
  return routes;
}

test("every address an empty-list action goes to is a page that exists", () => {
  const routes = appRoutes();
  assert.ok(routes.length > 100, "the route tree was not read");
  const hrefs: Array<[string, string]> = [];
  for (const f of FILES) {
    for (const tag of openingTags(code(f), "EmptyStateAction")) {
      const m = /href=(?:"([^"]*)"|\{`([^`]*)`\}|\{"([^"]*)"\})/.exec(tag);
      if (m) hrefs.push([f, m[1] ?? m[2] ?? m[3]]);
    }
  }
  assert.ok(hrefs.length >= 10, `only ${hrefs.length} links found: the scan has gone blind`);
  const dead: string[] = [];
  for (const [f, href] of hrefs) {
    const p = href.split(/[?#]/)[0].replace(/\$\{[^}]*\}/g, "*");
    const segs = p.split("/").filter(Boolean);
    const exists = routes.some((r) => r.length === segs.length
      && r.every((s, i) => s === segs[i] || s.startsWith("[") || segs[i] === "*"));
    if (!exists) dead.push(`${f}: ${href}`);
  }
  assert.deepEqual(dead, [], "an empty-list action links to a page that does not exist");
});

// ── the table decides which empty it shows ──────────────────────────────────

test("DataTable tells a table the reader emptied from one nothing was recorded in", () => {
  const src = code("components/ui/data-table.tsx");
  assert.match(src, /emptyKind\(\{/, "DataTable must ask emptyKind which empty it is showing");
  assert.match(src, /rowCount:\s*data\.length/, "and give it the number of rows the table was GIVEN");
  assert.match(src, /FILTERED_EMPTY\.clearLabel/, "and offer to clear what the reader set");
  assert.match(src, /<EmptyState title=\{emptyTitle\} description=\{emptyDescription\} action=\{emptyAction\} \/>/,
    "the screen's own first-run message and action are what a table nothing was recorded in shows");
});
