/**
 * The product's own words, as the four redrawn screens on the home page carry
 * them, each group beside the file it was copied from.
 *
 * WHY THIS FILE EXISTS (POST-A-121). The drawings under this folder were made on
 * 16-09-2026 on the argument that a recreation built from the product's source
 * "cannot silently go stale". It did: the product replaced the client sidebar
 * on 25-09-2026 with a module grid and a 48px top bar, added a fourth bank tab,
 * took the Insights tab off the copilot and reshaped GSTR-3B Table 6, and the
 * drawings went on showing the old screens for seven weeks while every check
 * was green, because nothing tied them to the product. They were re-copied on
 * 16-11-2026, and what they were copied FROM is now asserted rather than
 * remembered: `scripts/the-redrawn-screens-match-the-product.test.ts` reads each
 * file named in `FROM` and fails when
 *
 *   - `CLIENT_MODULES` differs from the product's `CLIENT_SECTIONS` in an id, a
 *     label or the order (the module grid renders exactly that list);
 *   - a string in a group of `COPIED` no longer appears in the file it names
 *     (a label renamed, a sentence reworded, a file moved);
 *   - the copilot's disclosure differs from the product's sentence by a letter.
 *
 * When it fails, re-copy from the product; do not loosen the test. A drawing
 * that cannot be brought back in step says so on the page instead.
 *
 * WHAT IT DOES NOT HOLD. The client names, the GSTIN, the dates and every
 * figure are invented sample data and live in the screens; so do the layout and
 * the colours, which nothing checks. A template keeps the product's own
 * placeholder (`{total}`, `${n}`) so that it is found in the source as written,
 * and `fill` puts the sample value in.
 *
 * A plain `.ts` file with no JSX and no imports, so the test can import it under
 * `node --experimental-strip-types`, which cannot read a `.tsx`.
 */

/** The product files the words below were copied from, relative to the repository root. */
export const FROM = {
  clientSections: "apps/web/lib/workspace/ClientNavContext.tsx",
  topBar: "apps/web/components/shell/ClientTopBar.tsx",
  healthBadge: "apps/web/components/HealthBadge.tsx",
  bankPage: "apps/web/app/clients/[id]/bank/page.tsx",
  entriesTab: "apps/web/components/banking/EntriesTab.tsx",
  dataTable: "apps/web/components/ui/data-table.tsx",
  draftReasons: "apps/api/domain/banking/entry.py",
  historyReasons: "apps/api/domain/banking/history.py",
  gstr3b: "apps/web/app/gst/gstr3b/page.tsx",
  copilot: "apps/web/app/copilot/page.tsx",
  copilotQuestions: "apps/api/models/ai_copilot.py",
  aiDisclosure: "apps/web/lib/ai/disclosure.ts",
} as const;

export type Source = keyof typeof FROM;

/** A template's placeholders, `{...}` or `${...}`, replaced in order by the values given. */
export function fill(template: string, ...values: (string | number)[]): string {
  let i = 0;
  return template.replace(/\$?\{[^}]*\}/g, () => String(values[i++] ?? ""));
}

// ── the client workspace ─────────────────────────────────────────────────────

export interface ClientModule {
  /** The product's route segment under /clients/{id}/. */
  id: string;
  /** What the card says. */
  label: string;
}

/** `CLIENT_SECTIONS`, id and label, in the product's order. */
export const CLIENT_MODULES: readonly ClientModule[] = [
  { id: "overview", label: "Overview" },
  { id: "accounting", label: "Accounting" },
  { id: "sales", label: "Sales" },
  { id: "purchases", label: "Purchases" },
  { id: "bank", label: "Bank" },
  { id: "inventory", label: "Inventory" },
  { id: "compliance", label: "Compliance" },
  { id: "payroll", label: "Payroll" },
  { id: "fixed-assets", label: "Fixed Assets" },
  { id: "year-end", label: "Year End" },
  { id: "tax", label: "Tax" },
  { id: "reports", label: "Reports" },
  { id: "documents", label: "Documents" },
  { id: "tasks", label: "Tasks" },
  { id: "portal", label: "Portal" },
  { id: "ai-insights", label: "Insights" },
  { id: "lifecycle", label: "Lifecycle" },
  { id: "relationships", label: "Related Parties" },
  { id: "health", label: "Health" },
  { id: "knowledge", label: "Knowledge" },
  { id: "instructions", label: "Instructions" },
];

export const TOP_BAR = {
  exit: "All clients",
  allModules: "All modules",
} as const;

export const HEALTH = {
  band: "Healthy",
} as const;

// ── Bank → Entries ───────────────────────────────────────────────────────────

export const BANK_TABS = {
  tabs: ["Entries", "Reconcile", "Worth a Look", "Rules"],
} as const;

export const ENTRIES = {
  filters: ["To do", "Passed", "Set aside"],
  accounts: "Accounts",
  bankBook: "Bank Book",
  importStatement: "Import statement",
  propose: "Propose",
  passReady: "Pass {counts.ready} ready",
  toDo: "{counts.to_do} to do",
  ready: "${n} ready",
  proposed: "${n} proposed",
  headers: ["Date", "Bank narration", "Entry", "Spent", "Received", "Status"],
  states: ["Ready", "Proposed", "Needs you"],
  pass: "Pass",
  answer: "Answer",
  receipt: "Receipt",
  payment: "Payment",
  askPayment: "To whom, or which ledger?",
  allAccounts: "All accounts",
  search: "Search narration, reference or payee…",
  footer:
    "A line is a Receipt, a Payment or a Contra — the bank decides which. Click a line to answer it; Pass puts it in the books; Undo takes it back out.",
} as const;

export const DATA_TABLE = {
  columns: "Columns",
  actions: "Actions",
} as const;

/** The reason a proposal carries, as domain/banking/entry.py writes it. */
export const DRAFT_REASONS = {
  onlyDocument: "exact amount, the only document that fits",
  severalDocuments: "{len(exact)} documents have exactly this amount — which one?",
  rule: "Rule “{hit.rule_name}”",
  ownAccount: "same amount on another own account",
} as const;

/** The reason a proposal from the payee's history carries (domain/banking/history.py). */
export const HISTORY_REASONS = {
  every: "Coded this way all {total} times before",
  most: "Coded this way {times} of the last {total} times",
} as const;

// ── GSTR-3B Review ───────────────────────────────────────────────────────────

export const GSTR3B = {
  back: "GST",
  title: "GSTR-3B Review",
  subtitle: "CGST Act Section 39 — Monthly summary return. Due 20th of following month.",
  reviewLead: "CA Review Required.",
  review:
    "Verify all figures before downloading JSON for portal upload. Do not upload to gst.gov.in without CA approval.",
  draft: "Draft",
  approve: "CA Approve",

  t31: "Table 3.1 — Outward Taxable Supplies",
  t31Note: "Net of credit notes. CGST Act Section 37.",
  t31Columns: ["Supply Type", "Taxable value", "IGST", "CGST", "SGST"],
  rowA: "(a) Taxable supplies (B2B + B2C + B2CL)",
  advances:
    "of advances — GSTR-1 Table 11A less 11B, taxable on receipt under CGST s.13(2). Declared and payable here, but not in the general ledger: a receipt posts no output-tax leg, so the books-to-ledger check excludes it.",
  rowB: "(b) Zero-rated supplies (Exports / SEZ)",
  rowC: "(c) Nil-rated / Exempt",
  rowD: "(d) Inward supplies liable to reverse charge",
  rowE: "(e) Non-GST outward supplies",
  total: "Total output tax — rows (a) and (b)",
  totalNote:
    "Reverse charge (d) is excluded — s.2(82) puts it outside output tax, and s.49(4) makes it cash. It is on the challan below.",

  t4: "Table 4 — Input Tax Credit",
  t4Note:
    "Notification 14/2022 with Circular 170/02/2022-GST. 4(A) is gross — the portal populates it from GSTR-2B — and the reversals are declared separately in 4(B).",
  t4Row: "Row",
  a4: "4(A) ITC available",
  a4Note: "All credit availed, including credit reversed below",
  b41: "4(B)(1) Reversed — permanent",
  b41Note: "Rules 38, 42 and 43, and Section 17(5) blocked credit",
  b42: "4(B)(2) Reversed — reclaimable later",
  b42Note: "Rule 37 / 37A and Section 16(2)(b), (c). Comes back through 4(A)(5)",
  c4: "4(C) Net ITC available",

  t6: "Table 6 — Net Tax Payable",
  t6Note:
    "CGST Act Section 49(5) with Rule 88A: IGST credit is spent first, then CGST and SGST credit may each be set against IGST — but never against each other.",
  afterSetOff: "After set-off",
  rcm: "Reverse charge, payable in cash",
  rcmNote: "Table 3.1(d). CGST Act s.49(4) with s.2(82) — the credit ledger cannot pay this.",
  cash: "Total payable in cash",
  cashNote: "This is the challan figure — the set-off result plus the reverse-charge tax.",
  available: "Credit available (opening + 4C)",
  setOff: "Set off against tax",
  carried: "Carried forward",
} as const;

// ── the copilot ──────────────────────────────────────────────────────────────

export const COPILOT = {
  title: "PracticeSync AI Copilot",
  subtitle: "Intelligent assistant for your CA practice",
  context: "Compliance",
  newConversation: "New Conversation",
  placeholder: "Ask anything about your clients, compliance, GST, TDS...",
  footer:
    "AI responses are advisory — always verify with source documents. Never auto-submit to government portals.",
} as const;

/** Questions the product itself suggests, used as the conversations in the sidebar. */
export const COPILOT_QUESTIONS = {
  status: "Summarize firm compliance status.",
  workflows: "Which workflows have failed recently?",
  risk: "Which clients are at risk this month?",
  tds: "What TDS returns are due this quarter?",
} as const;

/** What the copilot tells the CA before a message is sent: the product's sentence, letter for letter. */
export const COPILOT_DISCLOSURE = {
  sentence:
    "Your messages, and counts from your practice's own records, are sent to Groq, an AI provider outside India. No client name is added from our side. What you type is sent as written, except that anything shaped like a PAN or a GSTIN is replaced first.",
} as const;

/** Every group above but the module list (which is checked entry by entry), with the file it came from. */
export const COPIED: readonly (readonly [Source, Readonly<Record<string, string | readonly string[]>>])[] = [
  ["topBar", TOP_BAR],
  ["healthBadge", HEALTH],
  ["bankPage", BANK_TABS],
  ["entriesTab", ENTRIES],
  ["dataTable", DATA_TABLE],
  ["draftReasons", DRAFT_REASONS],
  ["historyReasons", HISTORY_REASONS],
  ["gstr3b", GSTR3B],
  ["copilot", COPILOT],
  ["copilotQuestions", COPILOT_QUESTIONS],
  ["aiDisclosure", COPILOT_DISCLOSURE],
];
