/**
 * Every screen in this product, named the way a CA would look for it.
 *
 * WHY A HAND-WRITTEN INVENTORY AND NOT THE ROUTE TABLE. The route is the worst
 * possible name. `/accounting/msme-tracker` is the §43B(h) screen and nobody
 * types "tracker"; `/settings/statutory-values` is where the PT slabs live and
 * nobody types "values". A CA types the FORM NUMBER, the SECTION, or the word
 * their firm has always used — "gstr1", "24Q", "43bh", "26AS", "form 16",
 * "BRS", "pass book". Almost none of that appears in a path.
 *
 * So `synonyms` is where the statutory vocabulary lives, and it is the half
 * that makes the palette worth opening. A name alone would only find the
 * screens somebody could already see in a menu.
 *
 * SCREENS ARE LOCAL; ENTITIES ARE NOT. This list ships in the bundle, so it
 * matches on the first keystroke with no round trip. `/api/search` finds
 * RECORDS and has to stay on the server, because it enforces client assignment
 * there (M2) — a browser-side entity search would be a second, weaker answer
 * to "may this person see this client".
 *
 * ⚠️ THE PLAN SAID ENTITY SEARCH WOULD MOVE BEHIND A PREFIX AND IT DOES NOT.
 * The commonest use of ⌘K here is typing a client's name; putting that behind
 * `@sharma` makes the common case worse to tidy the rare one. The real
 * difference between the two is COST, not priority — so both run, screens
 * first because they are instant, and `>` restricts to screens for anyone who
 * wants only those. Nothing was removed and nothing got slower.
 *
 * A CLIENT SCREEN NEEDS A CLIENT, which is a third state rather than an
 * absence. 33 of these live under `/clients/:id/` and there is no id at firm
 * level. Offering them anyway would mean inventing a "pick a client first"
 * flow, which is a feature and not a palette — so they are offered only inside
 * a workspace, and outside one the palette SAYS they exist and that a client
 * must be open. A hub tile that names why it has no figure, applied to
 * navigation.
 *
 * WHAT IS DELIBERATELY ABSENT is in `UNLISTED`, with a reason each, and
 * `scripts/every-screen-has-a-name.test.ts` holds the two halves together: a
 * route on disk that is in neither list fails, and a named route that is not
 * on disk fails too. The second direction matters — 2.2b's href guard found
 * four typed paths that did not exist.
 */

export type ScreenScope = "firm" | "client";

export interface Screen {
  /** Firm: the absolute path. Client: the FIRST SEGMENT under `/clients/:id/`,
   *  because that is the one segment `lib/workspace/clientPath` carries and
   *  every one of them has its own landing page. */
  href: string;
  name: string;
  /** What a CA types. The form number, the section, the old name. */
  synonyms: string[];
  section: string;
  scope: ScreenScope;
}

const firm = (href: string, name: string, section: string, synonyms: string[] = []): Screen =>
  ({ href, name, section, synonyms, scope: "firm" });
const client = (href: string, name: string, section: string, synonyms: string[] = []): Screen =>
  ({ href, name, section, synonyms, scope: "client" });

export const SCREENS: Screen[] = [
  // ── Home and cross-cutting ────────────────────────────────────────────────
  firm("/", "Home", "General", ["dashboard", "hub", "start"]),
  firm("/deadlines", "Compliance calendar", "General", ["due dates", "deadlines", "whats due", "calendar"]),
  firm("/calendar", "Calendar", "General", ["schedule", "diary"]),
  firm("/tasks", "Tasks", "General", ["to do", "work items"]),
  firm("/tasks/templates", "Task templates", "General", ["recurring tasks", "checklist template"]),
  firm("/work", "My work", "General", ["assigned to me", "my queue"]),
  firm("/approvals", "Approvals", "General", ["sign off", "review queue"]),
  firm("/workflows", "Workflows", "General", ["automation", "process"]),
  firm("/workflows/approvals", "Workflow approvals", "General", ["approval chain"]),
  firm("/notifications", "Notifications", "General", ["alerts"]),
  firm("/notifications/whatsapp", "WhatsApp notifications", "General", ["whatsapp", "wa"]),
  firm("/search", "Search", "General", ["find"]),
  firm("/documents", "Documents", "General", ["files", "attachments", "dms"]),
  firm("/knowledge", "Knowledge base", "General", ["help", "articles", "notes"]),
  firm("/risks", "Risk register", "General", ["risks", "exposure"]),
  firm("/time", "Timesheets", "General", ["time", "hours", "utilisation"]),

  // ── Clients and relationships ─────────────────────────────────────────────
  firm("/clients", "Clients", "Clients", ["client list", "all clients"]),
  firm("/clients/documents", "Client documents", "Clients", ["client files"]),
  firm("/pipeline", "Pipeline", "Clients", ["leads", "prospects", "sales pipeline"]),
  firm("/relationships", "Relationships", "Clients", ["group", "related parties"]),
  firm("/relationships/cross-client", "Cross-client exposure", "Clients", ["inter company", "common parties"]),
  firm("/relationships/explorer", "Relationship explorer", "Clients", ["graph", "network"]),
  firm("/relationships/intelligence", "Relationship intelligence", "Clients", ["insights"]),
  firm("/relationships/ownership-map", "Ownership map", "Clients", ["shareholding", "structure", "group chart"]),
  firm("/engagements", "Engagements", "Clients", ["engagement letter", "loe", "appointment"]),
  firm("/client-portal", "Client portal", "Clients", ["portal access", "sharing"]),

  // ── Accounting ────────────────────────────────────────────────────────────
  firm("/accounting", "Accounting", "Accounting", ["books", "ledger", "gl", "general ledger"]),
  firm("/accounting/account-groups", "Account groups", "Accounting", ["groups", "chart grouping"]),
  firm("/accounting/budget", "Budgets", "Accounting", ["budget vs actual", "variance"]),
  firm("/accounting/coa-export", "Export chart of accounts", "Accounting", ["coa export", "download coa"]),
  firm("/accounting/coa-import", "Import chart of accounts", "Accounting", ["coa import", "upload coa"]),
  firm("/accounting/loans", "Loans", "Accounting", ["borrowings", "related party loans"]),
  firm("/accounting/lock-year", "Lock financial year", "Accounting", ["close year", "freeze", "year end lock"]),
  firm("/accounting/msme-tracker", "MSME payments", "Accounting", ["43b(h)", "43bh", "micro small", "msmed", "section 43b"]),
  firm("/accounting/receivables", "Receivables", "Accounting", ["debtors", "ar", "outstanding", "ageing"]),
  // The four firm-level WORKLISTS (D22, G3) — which clients need work in a
  // module whose register lives only in the client workspace. Named with the
  // words a CA would type for the QUESTION, not for the module: somebody
  // looking for "which clients" is not looking for the register.
  firm("/accounting/banking", "Banking worklist", "Accounting",
    ["bank lines", "unpassed", "which clients", "reconcile", "statement queue"]),
  firm("/accounting/purchases", "Purchases worklist", "Accounting",
    ["creditors", "ap", "overdue to suppliers", "which clients", "payables"]),
  firm("/accounting/fixed-assets", "Fixed assets worklist", "Accounting",
    ["depreciation due", "which clients", "schedule ii", "wdv", "asset register"]),
  firm("/accounting/year-end", "Year-end worklist", "Accounting",
    ["finalisation", "which clients", "closing", "statements", "schedule iii"]),
  firm("/accounting/recurring", "Recurring journals", "Accounting", ["repeating entry", "standing journal"]),
  firm("/accounting/retainer", "Retainers", "Accounting", ["retainer billing", "fixed fee"]),
  // NOT "Schedule III captions" — that was wrong, and wrong in the way this
  // list exists to prevent. This route renders the STATEMENTS (its own header:
  // "Formats Balance Sheet and P&L as per Companies Act 2013, Schedule III");
  // the caption mapping is `/accounting/schedule-iii-mapping` on the next line.
  // So a CA typing "balance sheet" found nothing and one typing "captions"
  // landed on the statements.
  firm("/accounting/schedule-iii", "Schedule III statements", "Accounting",
    ["schedule 3", "balance sheet", "profit and loss", "p&l", "section 129", "statements"]),
  firm("/accounting/schedule-iii-mapping", "Schedule III account mapping", "Accounting", ["map accounts", "schedule 3 mapping"]),
  firm("/accounting/suppliers", "Suppliers (firm)", "Accounting", ["vendors", "creditors"]),
  firm("/accounting/trial-balance-import", "Import trial balance", "Accounting", ["tb import", "opening tb"]),

  // ── GST ───────────────────────────────────────────────────────────────────
  firm("/gst", "GST", "GST", ["goods and services tax"]),
  firm("/gst/gstr1", "GSTR-1", "GST", ["gstr1", "outward supplies", "sales return"]),
  firm("/gst/gstr3b", "GSTR-3B", "GST", ["gstr3b", "3b", "summary return", "monthly return"]),
  firm("/einvoice", "e-Invoice", "GST", ["irn", "irp", "e invoice", "einvoice"]),

  // ── Income tax and TDS ────────────────────────────────────────────────────
  firm("/income-tax", "Income tax", "Income tax", ["it", "itr"]),
  firm("/income-tax/advance-tax", "Advance tax", "Income tax", ["234b", "234c", "instalments"]),
  firm("/income-tax/ais", "AIS", "Income tax", ["annual information statement", "tis"]),
  firm("/income-tax/book-to-tax", "Book to tax", "Income tax", ["reconciliation", "bridge"]),
  firm("/income-tax/capital-gains", "Capital gains", "Income tax", ["54", "54f", "112a", "111a", "ltcg", "stcg"]),
  firm("/income-tax/deductions", "Chapter VI-A deductions", "Income tax", ["80c", "80d", "80g", "deductions"]),
  firm("/income-tax/notices", "Notices", "Income tax", ["143(1)", "139(9)", "intimation", "scrutiny"]),
  firm("/income-tax/section-32", "Depreciation (section 32)", "Income tax", ["32", "additional depreciation", "block"]),
  firm("/income-tax/tax-audit", "Tax audit", "Income tax", ["44ab", "3cd", "3ca", "3cb", "audit report"]),
  firm("/tds", "TDS", "TDS", ["withholding", "deduction"]),
  firm("/tds/returns", "TDS returns", "TDS", ["24q", "26q", "27q", "27eq", "quarterly statement", "fvu"]),

  // ── Payroll ───────────────────────────────────────────────────────────────
  firm("/payroll", "Payroll", "Payroll", ["salary", "wages"]),
  firm("/payroll/attendance", "Attendance", "Payroll", ["lop", "leave", "days present"]),
  firm("/payroll/declarations", "Investment declarations", "Payroll", ["12bb", "proofs", "80c declaration"]),
  firm("/payroll/people", "Employees", "Payroll", ["staff", "people", "employee master"]),
  firm("/payroll/reports", "Payroll reports", "Payroll", ["variance", "department cost", "bank advice"]),
  firm("/payroll/statutory", "Payroll statutory", "Payroll", ["pf", "esi", "pt", "ecr", "challan"]),

  // ── MCA ───────────────────────────────────────────────────────────────────
  firm("/mca", "MCA / ROC", "MCA", ["roc", "aoc-4", "mgt-7", "adt-1", "company filings"]),

  // ── Practice ──────────────────────────────────────────────────────────────
  firm("/practice", "Practice", "Practice", ["firm"]),
  firm("/practice/ar", "Practice receivables", "Practice", ["fee outstanding", "our debtors"]),
  firm("/practice/billing", "Practice billing", "Practice", ["fee bills", "invoicing"]),
  firm("/practice/collections", "Collections", "Practice", ["chasing", "reminders", "dunning"]),
  firm("/practice/compliance", "Practice compliance", "Practice", ["our own compliance"]),
  firm("/practice/instructions", "Standing instructions", "Practice", ["instructions"]),
  firm("/practice/revenue", "Revenue", "Practice", ["fee income", "realisation"]),
  firm("/billing", "Billing", "Practice", ["fees", "client invoices"]),
  firm("/team", "Team", "Practice", ["staff", "users", "permissions"]),
  firm("/team/assignments", "Client assignments", "Practice", ["who handles which client"]),
  firm("/team/login-history", "Login history", "Practice", ["sign ins", "access log"]),
  firm("/team/work-allocation", "Work allocation", "Practice", ["allocate", "assign work"]),
  firm("/team/workload", "Workload", "Practice", ["capacity", "utilisation"]),

  // ── Intelligence and reporting ────────────────────────────────────────────
  firm("/health", "Client health", "Insights", ["score", "health"]),
  firm("/health/alerts", "Health alerts", "Insights", ["alerts"]),
  firm("/health/at-risk", "At-risk clients", "Insights", ["churn", "at risk"]),
  firm("/health/critical", "Critical clients", "Insights", ["critical"]),
  firm("/health/overrides", "Health overrides", "Insights", ["override score"]),
  firm("/executive-dashboard", "Executive dashboard", "Insights", ["partner view", "mis"]),
  firm("/reports", "Reports", "Insights", ["statements", "mis"]),
  firm("/reports/cash-flow", "Cash flow", "Insights", ["as-3", "cash flow statement"]),
  firm("/ai-assistant", "AI assistant", "Insights", ["copilot", "ask", "chat"]),
  firm("/copilot", "Copilot", "Insights", ["ai", "assistant", "ask"]),
  firm("/memory", "AI memory", "Insights", ["what it remembers"]),

  // ── Settings ──────────────────────────────────────────────────────────────
  firm("/settings", "Settings", "Settings", ["configuration", "preferences"]),
  firm("/settings/audit-log", "Audit log", "Settings", ["who changed what", "edit log", "rule 3(1)"]),
  firm("/settings/branding", "Branding", "Settings", ["logo", "letterhead"]),
  firm("/settings/dsc-tracker", "DSC tracker", "Settings", ["digital signature", "dsc expiry", "token"]),
  firm("/settings/email-templates", "Email templates", "Settings", ["mail wording"]),
  firm("/settings/firm-hsn-library", "HSN library", "Settings", ["hsn", "sac", "rate master"]),
  firm("/settings/invoice-settings", "Invoice numbering", "Settings", ["series", "prefix", "rule 46(b)"]),
  firm("/settings/invoice-templates", "Invoice templates", "Settings", ["layout", "pdf design"]),
  firm("/settings/multi-currency", "Multi-currency", "Settings", ["fx", "foreign currency", "as-11"]),
  firm("/settings/scheduled-reports", "Scheduled reports", "Settings", ["email reports", "subscriptions"]),
  firm("/settings/security", "Security", "Settings", ["2fa", "sessions", "password policy"]),
  firm("/settings/statutory-values", "Statutory values", "Settings", ["rates", "limits", "pt slabs"]),
  firm("/settings/treaty-rates", "DTAA treaty rates", "Settings", ["dtaa", "treaty", "90(2)", "trc"]),

  // ── Onboarding, migration, platform ───────────────────────────────────────
  firm("/onboarding", "Onboarding", "Setup", ["setup", "get started"]),
  firm("/onboarding/checklist", "Onboarding checklist", "Setup", ["setup steps"]),
  firm("/migration", "Tally migration", "Setup", ["import from tally", "migrate"]),
  firm("/platform", "Platform admin", "Setup", ["superadmin", "firms"]),

  // ── Client workspace ──────────────────────────────────────────────────────
  client("overview", "Overview", "Client", ["summary", "home"]),
  client("accounting", "Accounting", "Client", ["ledger", "journal", "gl", "books"]),
  client("bank", "Bank", "Client", ["statement", "reconciliation", "brs", "pass book"]),
  client("sales", "Sales", "Client", ["invoices", "customers", "receipts"]),
  client("purchases", "Purchases", "Client", ["bills", "vendors", "payments"]),
  client("inventory", "Inventory", "Client", ["stock", "godown", "batch", "reorder"]),
  client("fixed-assets", "Fixed assets", "Client", ["depreciation", "schedule ii", "wdv", "block"]),
  client("payroll", "Payroll", "Client", ["salary", "pf", "esi", "payslip"]),
  client("compliance", "Compliance", "Client", ["returns", "filings"]),
  client("documents", "Documents", "Client", ["files", "attachments"]),
  client("tasks", "Tasks", "Client", ["to do", "checklist"]),
  client("instructions", "Instructions", "Client", ["standing instructions", "notes"]),
  client("health", "Health", "Client", ["score", "risk"]),
  client("ai-insights", "AI insights", "Client", ["insights", "anomalies"]),
  client("knowledge", "Knowledge", "Client", ["notes", "articles"]),
  client("lifecycle", "Lifecycle", "Client", ["stage", "onboarding status"]),
  client("portal", "Portal", "Client", ["client portal", "sharing"]),
  client("relationships", "Relationships", "Client", ["group", "related parties"]),
  client("tax", "Income tax", "Client", ["itr", "computation"]),
  client("year-end", "Year end", "Client", ["finalisation", "closing", "statements"]),
  client("reports", "Reports", "Client", ["statements", "registers"]),
];

/**
 * Sub-screens under a client section. Kept apart from `SCREENS` because they
 * are NOT what `lib/workspace/clientPath` carries — that rule moves ONE
 * segment, deliberately, so a switch cannot land on another client's document.
 * These are reachable and nameable; they are simply deeper.
 */
export const CLIENT_SUBSCREENS: Screen[] = [
  client("compliance/gst", "GST compliance", "Client", ["gstr-1", "3b", "2b", "gstr-9", "e-way"]),
  client("compliance/tds", "TDS compliance", "Client", ["24q", "26q", "27q", "challan", "26as"]),
  client("compliance/mca", "MCA compliance", "Client", ["roc", "aoc-4", "mgt-7"]),
  client("tax/computation", "Tax computation", "Client", ["compute", "slabs", "115bac", "regime"]),
  client("tax/filing", "ITR filing", "Client", ["itr-1", "itr-4", "acknowledgement", "139"]),
  client("tax/26as", "Form 26AS", "Client", ["26as", "tax credit", "tds credit"]),
  client("year-end/xbrl", "XBRL", "Client", ["xbrl", "taxonomy", "mca filing"]),
  client("reports/ageing", "Ageing", "Client", ["debtors ageing", "creditors", "schedule iii ageing"]),
  client("reports/bank-book", "Bank book", "Client", ["cash book", "bank register"]),
  client("reports/ratios", "Ratios", "Client", ["ratio note", "g.s.r. 207(e)", "current ratio"]),
  client("reports/trend", "Trend", "Client", ["year on year", "comparative"]),
];

export const ALL_SCREENS: Screen[] = [...SCREENS, ...CLIENT_SUBSCREENS];

/**
 * Routes on disk that are deliberately NOT in the palette, each with why.
 * A route in neither list fails the guard, so silence is never the reason.
 */
export const UNLISTED: Record<string, string> = {
  // `/accounting/fixed-assets` LEFT THIS LIST ON 24-09 (D22). It was the
  // tombstone this entry describes; it is the fixed-asset WORKLIST now and is
  // named above. `/accounting/invoices` is still one.
  "/accounting/invoices":
    "a MovedToClientWorkspace TOMBSTONE, the Sales half of the pair. Naming\n     it would let a CA type \"invoices\" and land on a page whose whole content\n     is \"this moved\" — worse than a dead link, because the name says it\n     works. Its worklist question is already answered by\n     /accounting/receivables, which is the Sales tile's own firm href, so it\n     did not get a worklist of its own; see D22 and question G3",
  "/login": "signed-out — a palette is for somebody already inside the product",
  "/login/forgot-password": "signed-out",
  "/signup": "signed-out",
  "/join": "signed-out — reached from an invitation link",
  "/sign": "signed-out — a client signs an engagement letter from an emailed link",
  "/auth/reset-password": "signed-out",
  "/portal": "the CLIENT's portal, not staff navigation",
  "/portal/login": "signed-out, client portal",
  "/portal/activate": "reached from an invitation link",
  "/portal/dashboard": "the client's own screen, not staff navigation",
  "/portal/employee": "the EMPLOYEE portal — a different principal entirely",
  "/portal/employee/activate": "reached from an invitation link",
  "/clients/[id]":
    "a pure redirect to /clients/:id/overview/ — naming it would give ONE\n     destination two palette entries, and \"Overview\" is the one a CA means",
  "/health/[client_id]": "a RECORD, which is what entity search already finds",
  "/relationships/[entity_id]": "a RECORD",
  "/clients/[id]/accounting/journal/[entryId]/edit": "a RECORD — no such screen without a document id",
  "/clients/[id]/sales/invoices/[invoiceId]/edit": "a RECORD",
  "/clients/[id]/sales/credit-notes/[cnId]/edit": "a RECORD",
  "/clients/[id]/sales/debit-notes/[sdnId]/edit": "a RECORD",
  "/clients/[id]/purchases/bills/[billId]/edit": "a RECORD",
  "/clients/[id]/purchases/credit-notes/[pcnId]/edit": "a RECORD",
  "/clients/[id]/purchases/debit-notes/[dnId]/edit": "a RECORD",
  "/clients/[id]/year-end/[engagementId]": "a RECORD",
};

/** Where a screen goes. A client screen needs an open client; without one the
 *  caller is told, rather than sent to a path with no id in it. */
export function screenHref(s: Screen, clientId: string | null): string | null {
  if (s.scope === "firm") return s.href;
  return clientId ? `/clients/${clientId}/${s.href}/` : null;
}

/** Ranked matches. Local and synchronous — that is the whole point of it. */
export function matchScreens(query: string, clientId: string | null, limit = 8): Screen[] {
  const q = query.trim().toLowerCase().replace(/^>\s*/, "");
  if (!q) return [];
  const scored: { s: Screen; score: number }[] = [];
  for (const s of ALL_SCREENS) {
    if (s.scope === "client" && !clientId) continue;
    const name = s.name.toLowerCase();
    let score = 0;
    if (name === q) score = 100;
    else if (name.startsWith(q)) score = 80;
    else if (name.includes(q)) score = 60;
    else if (s.synonyms.some((x) => x === q)) score = 70;
    else if (s.synonyms.some((x) => x.startsWith(q))) score = 50;
    else if (s.synonyms.some((x) => x.includes(q))) score = 30;
    else if (s.section.toLowerCase().startsWith(q)) score = 20;
    if (score) scored.push({ s, score });
  }
  scored.sort((a, b) => b.score - a.score || a.s.name.localeCompare(b.s.name));
  return scored.slice(0, limit).map((x) => x.s);
}

/** `>` restricts the palette to screens. */
export const SCREENS_ONLY_PREFIX = ">";
export const isScreensOnly = (q: string) => q.trimStart().startsWith(SCREENS_ONLY_PREFIX);
