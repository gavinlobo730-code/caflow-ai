/**
 * ACC-22 — where a ledger row's DOCUMENT lives.
 *
 * A general ledger whose rows cannot name the document behind them is a ledger
 * a CA has to take on trust. `journal_entries.source_type` / `source_id` have
 * been filled in by all twenty-six posting paths since commit 99ac94b5, and
 * migration 400 with `domain/reporting/builders.ledger` carry them onto the
 * row; this is the one place that says where the CA goes when they click it.
 *
 * THE VOCABULARY IS PYTHON'S, AND THIS IS NOT A SECOND COPY OF IT.
 *     `apps/api/domain/accounting/journal_source.py` owns ALL_SOURCES and
 *     ENTRY_IS_THE_RECORD. This file maps a source to a SCREEN, which is a
 *     fact about Next.js routes that the backend cannot hold — so the map lives
 *     here and is pinned FROM THE PYTHON SIDE by
 *     `apps/api/tests/test_the_browser_can_open_the_document_the_ledger_names.py`.
 *     A guard written in apps/web would assert this file against a copy of
 *     itself and pass whenever both drifted together, which is exactly what the
 *     Schedule III caption list did for months.
 *
 * THREE SOURCES ARE THE ENTRY ITSELF.
 *     journal_source.ENTRY_IS_THE_RECORD — a manual journal, an opening balance
 *     and a trial-balance import name no row to open, so they carry no
 *     source_id and the target is the JOURNAL ENTRY, addressed by `entry_id`.
 *     The journal editor renders a posted entry read-only, which is what the
 *     day book's own row click already relies on.
 *
 * A SOURCE WITH NOWHERE TO GO IS REFUSED AND NAMED, NEVER GUESSED.
 *     `settlement` and `year_end_adjustment` are the two, and both are refusals
 *     about the ROUTE rather than about the document:
 *       * a settlement's source_id is `payroll_settlements.id`, and the only
 *         screen that shows one is the leaver's drawer inside the employee
 *         list, which is keyed on the EMPLOYEE. The row does not carry one.
 *       * a year-end adjustment lives under `/clients/{c}/year-end/{engagement}`
 *         and the row carries the adjustment's id, not the engagement's.
 *     Sending the CA to a list that cannot show the document is worse than an
 *     unclickable row: it reads as "this is the document" and it is not.
 */

/** One target: a route, and what to call the document in a sentence. */
export interface DocumentTarget {
  href: string;
  label: string;
}

/** A ledger row, as much of it as this module reads. */
export interface LedgerRowSource {
  entry_id: string;
  source_type: string | null;
  source_id: string | null;
}

/** journal_source.ENTRY_IS_THE_RECORD, in its own spelling. */
export const ENTRY_IS_THE_RECORD: readonly string[] = ["manual", "Opening", "TrialBalance"];

/** Module + sub-tab per source. The tab ids are the target page's own `TABS`
 *  values — a tab this page does not know is simply a tab the CA has to pick,
 *  so a typo here costs a click rather than a wrong document. */
const ROUTES: Record<string, { module: string; tab: string }> = {
  // Sales cycle.
  sales_invoice:         { module: "sales",        tab: "invoices" },
  credit_note:           { module: "sales",        tab: "credit-notes" },
  sales_debit_note:      { module: "sales",        tab: "debit-notes" },
  receipt:               { module: "sales",        tab: "receipts" },
  // Purchase cycle.
  purchase_bill:         { module: "purchases",    tab: "bills" },
  debit_note:            { module: "purchases",    tab: "debit-notes" },
  purchase_credit_note:  { module: "purchases",    tab: "credit-notes" },
  purchase_payment:      { module: "purchases",    tab: "payments" },
  bill_of_entry:         { module: "purchases",    tab: "bills-of-entry" },
  // Payroll. Both point at the RUN — the accrual and the disbursement are two
  // journals of one month's payroll.
  payroll_run:           { module: "payroll",      tab: "register" },
  payroll_disbursement:  { module: "payroll",      tab: "register" },
  // Fixed assets. All three point at the ASSET, because that is the row a CA
  // opens: a depreciation charge has no document of its own and its asset is
  // what explains it (journal_source says the same).
  fixed_asset:           { module: "fixed-assets", tab: "register" },
  depreciation:          { module: "fixed-assets", tab: "register" },
  asset_disposal:        { module: "fixed-assets", tab: "register" },
  cwip_addition:         { module: "fixed-assets", tab: "cwip" },
  cwip_capitalisation:   { module: "fixed-assets", tab: "cwip" },
  // Banking.
  bank_transaction:      { module: "bank",         tab: "entries" },
  bank_overpayment:      { module: "bank",         tab: "entries" },
};

/** Why a source that names a document still has no screen to send the CA to.
 *  Rendered as a tooltip, so the row says what it cannot do rather than being
 *  silently inert. */
export const NO_ROUTE_REASON: Record<string, string> = {
  settlement:
    "A settlement is shown inside the leaver's drawer, which opens on the employee — " +
    "and the ledger row carries the settlement's id, not theirs.",
  year_end_adjustment:
    "A year-end adjustment lives under its engagement, and the ledger row carries " +
    "the adjustment's id, not the engagement's.",
};

/** The journal entry itself, read-only for a posted one. */
export function journalEntryHref(clientId: string, entryId: string): string {
  return `/clients/${clientId}/accounting/journal/${entryId}/edit`;
}

/**
 * The document's own screen, with the sub-tab and the document in the URL:
 * `/clients/{c}/{module}?tab={tab}&doc={id}`.
 *
 * `doc` is ONE param for every kind rather than `?invoice=`, `?bill=`,
 * `?run=` — the screen already knows which kind its tab shows, so a param per
 * kind would be a vocabulary to keep in step with this one.
 */
export function documentHref(clientId: string, module: string, tab: string, docId: string): string {
  return `/clients/${clientId}/${module}?tab=${encodeURIComponent(tab)}&doc=${encodeURIComponent(docId)}`;
}

/**
 * The posting path a journal entry came from, spelled for a reader.
 *
 * DERIVED, NOT LISTED. journal_source.ALL_SOURCES is the canonical vocabulary
 * and a label map here would be a second copy of it, out of step the first time
 * one is added. Two of the values are CamelCase rather than snake_case
 * ("Opening", "TrialBalance") — journal_source.py explains why they keep their
 * original spelling — so both shapes are handled.
 * apps/api/tests/test_a_journal_source_reads_as_english.py holds the line from
 * the side that owns the vocabulary.
 */
export function sourceLabel(value: string | null | undefined): string {
  const v = (value ?? "").trim();
  if (!v) return "—";
  const spaced = v.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/_/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1).toLowerCase();
}

/**
 * Where this ledger row goes, or null when there is nowhere.
 *
 * Null has three causes and they are deliberately not distinguished HERE —
 * `noRouteReason` answers that, because a caller wanting a tooltip is a
 * different question from a caller wanting an href:
 *   * the entry carries no source at all (posted before its path stamped one);
 *   * the source names no screen (settlement, year-end adjustment);
 *   * the source names a screen but the row carries no source_id, which would
 *     be a breadcrumb leading nowhere.
 */
export function documentTarget(clientId: string, row: LedgerRowSource): DocumentTarget | null {
  const st = (row.source_type ?? "").trim();
  if (!st) return null;
  if (ENTRY_IS_THE_RECORD.includes(st)) {
    return { href: journalEntryHref(clientId, row.entry_id), label: sourceLabel(st) };
  }
  const route = ROUTES[st];
  if (!route || !row.source_id) return null;
  return {
    href: documentHref(clientId, route.module, route.tab, row.source_id),
    label: sourceLabel(st),
  };
}

/** Why this row does not open, for a tooltip. Empty string when it does open,
 *  or when there is nothing to explain (no source at all). */
export function noRouteReason(row: LedgerRowSource): string {
  const st = (row.source_type ?? "").trim();
  if (!st) return "";
  if (ENTRY_IS_THE_RECORD.includes(st)) return "";
  if (NO_ROUTE_REASON[st]) return NO_ROUTE_REASON[st];
  if (ROUTES[st] && !row.source_id) {
    return `This ${sourceLabel(st).toLowerCase()} entry records no document id, so there is nothing to open.`;
  }
  if (!ROUTES[st]) return `No screen in this product shows a ${sourceLabel(st).toLowerCase()}.`;
  return "";
}

/** Every source this file routes — read by the guard on the Python side. */
export const ROUTED_SOURCES: readonly string[] = Object.keys(ROUTES);

/**
 * The sub-tab and document a screen was opened at.
 *
 * PURE — the caller passes `window.location.search` from inside an effect, the
 * way the `?cust=` convention on the Sales screen already does. Reading
 * `window` during render would break the static export's prerender, and
 * `useSearchParams` would need a Suspense boundary on every screen that took
 * one.
 *
 * A blank value reads as absent: `?doc=` with nothing after it is a link
 * somebody truncated, not a document with an empty id.
 */
export function openedAt(search: string): { tab: string | null; doc: string | null } {
  const p = new URLSearchParams(search);
  const clean = (v: string | null) => (v && v.trim() ? v.trim() : null);
  return { tab: clean(p.get("tab")), doc: clean(p.get("doc")) };
}
