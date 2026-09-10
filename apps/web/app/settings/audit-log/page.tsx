"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import { ChevronLeft, Download, ShieldCheck, RefreshCw } from "lucide-react";
import { api, type AuditEntry } from "@/lib/api";
import { RoleGuard } from "@/components/RoleGuard";
import { formatDate } from "@/lib/services/formatting";
import { todayLocalISO } from "@/lib/dateMath";
import { Skeleton } from "@/components/ui/skeleton";

// ── Formatting helpers ─────────────────────────────────────────────────────────
// The audit_log table stores backend vocabulary: entity_type is snake_case
// (journal_entry, sales_invoice, gstr1_return, …) and action is lowercase
// (create, update, status_change, final_approve, …). We render friendly labels
// without hardcoding an exhaustive list — special-cases first, generic title-case
// (with acronym handling) as the fallback so new event types still display well.

const ACRONYMS = new Set([
  "gst", "tds", "mca", "roc", "gstr", "hsn", "sac", "pan", "tan", "tin", "itr",
  "xbrl", "ca", "kyc", "ip", "2fa", "mfa", "26as", "24q", "26q", "3b", "id",
  "dsc", "msme", "esi", "pf", "ros", "din", "cin",
]);

function titleizeToken(t: string): string {
  if (!t) return t;
  if (ACRONYMS.has(t.toLowerCase())) return t.toUpperCase();
  return t.charAt(0).toUpperCase() + t.slice(1);
}

const ENTITY_LABELS: Record<string, string> = {
  journal_entry: "Journal Entry",
  sales_invoice: "Sales Invoice",
  payment_link: "Payment Link",
  payment_webhook: "Payment Webhook",
  customer_payment: "Customer Payment",
  compliance_record: "Compliance Record",
  user_role: "User Role",
  gstr1_return: "GSTR-1 Return",
  gstr3b_return: "GSTR-3B Return",
  tds_challan: "TDS Challan",
  tds_return: "TDS Return",
  tds_certificate: "TDS Certificate",
  form_26as_upload: "Form 26AS Upload",
  year_end_engagement: "Year-End Engagement",
  government_notice: "Government Notice",
  bank_statement: "Bank Statement",
  bank_transaction: "Bank Transaction",
  bank_reconciliation: "Bank Reconciliation",
  knowledge_article: "Knowledge Article",
  approval_request: "Approval Request",
  user_client_assignment: "Client Assignment",
  client_portal_user: "Portal User",
  customer_statement: "Customer Statement",
  // Entity types produced by the database audit triggers (migration 111).
  firm: "Firm",
  account: "Account",
  client: "Client",
  it_notice: "IT Notice",
  it_deduction: "IT Deduction",
  itr_filing: "ITR Filing",
  tax_notice: "Tax Notice",
  tax_audit: "Tax Audit",
  tax_planning_record: "Tax Planning Record",
  advance_tax_payment: "Advance Tax Payment",
  capital_gain: "Capital Gain",
  fixed_asset: "Fixed Asset",
  fixed_deposit: "Fixed Deposit",
  mca_filing: "MCA Filing",
  mca_company: "MCA Company",
  mca_director: "MCA Director",
  msme_payment: "MSME Payment",
  eway_bill_record: "E-Way Bill Record",
  einvoice_record: "E-Invoice Record",
  dsc_record: "DSC Record",
  fee_engagement: "Fee Engagement",
  fee_invoice: "Fee Invoice",
  fee_receipt: "Fee Receipt",
  purchase_bill: "Purchase Bill",
  purchase_payment: "Purchase Payment",
  credit_note: "Credit Note",
  scheduled_report: "Scheduled Report",
  salary_slip: "Salary Slip",
  salary_structure: "Salary Structure",
};

function formatEntityType(s: string): string {
  if (!s) return "—";
  return ENTITY_LABELS[s] ?? s.split("_").map(titleizeToken).join(" ");
}

const ACTION_LABELS: Record<string, string> = {
  status_change: "Status Change",
  final_approve: "Final Approve",
  request_revision: "Request Revision",
  submit_for_review: "Submit for Review",
  force_logout: "Force Logout",
  force_logout_all: "Force Logout All",
  platform_suspend: "Platform Suspend",
  platform_unsuspend: "Platform Unsuspend",
  platform_delete: "Platform Delete",
  repost_journal: "Repost Journal",
  recurring_generated: "Recurring Generated",
  reminder_sent: "Reminder Sent",
  signature_failed: "Signature Failed",
  assignment_change: "Assignment Change",
};

function formatAction(s: string): string {
  if (!s) return "—";
  return ACTION_LABELS[s] ?? s.split("_").map(titleizeToken).join(" ");
}

function actionBadgeClass(action: string): string {
  const a = action.toLowerCase();
  if (["create", "captured", "recurring_generated"].includes(a)) return "bg-green-100 text-green-700";
  if (["update", "assignment_change"].includes(a)) return "bg-blue-100 text-blue-700";
  if (["delete", "platform_delete", "reject", "signature_failed"].includes(a)) return "bg-red-100 text-red-700";
  if (["approve", "final_approve", "reactivate", "platform_unsuspend"].includes(a)) return "bg-purple-100 text-purple-700";
  if (["suspend", "platform_suspend", "force_logout", "force_logout_all", "request_revision"].includes(a)) return "bg-orange-100 text-orange-700";
  if (a.includes("status") || a.includes("review") || a.includes("send") || a.includes("reminder")) return "bg-amber-100 text-amber-700";
  return "bg-[#F1F5F9] text-[#475569]";
}

/** Pull a human-friendly entity label from new_data/old_data; fall back to the id. */
function deriveName(row: AuditEntry): string {
  const src = { ...(row.old_data ?? {}), ...(row.new_data ?? {}) } as Record<string, unknown>;
  for (const k of [
    "client_name", "name", "invoice_number", "invoice_no", "number", "title",
    "narration", "task_name", "reference_no", "challan_no", "full_name", "email",
  ]) {
    const v = src[k];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return row.entity_id ?? "—";
}

/** Short, robust summary of what changed. */
function deriveDetail(row: AuditEntry): string {
  const meta = (row.metadata ?? {}) as Record<string, unknown>;
  for (const k of ["message", "note", "reason", "summary"]) {
    const v = meta[k];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  if (row.action === "status_change") {
    const oldS = (row.old_data as Record<string, unknown> | null)?.status;
    const newS = (row.new_data as Record<string, unknown> | null)?.status;
    if (typeof newS === "string") return typeof oldS === "string" ? `${oldS} → ${newS}` : `→ ${newS}`;
  }
  return "";
}

// ── CSV export ─────────────────────────────────────────────────────────────────

interface DisplayRow {
  id: string;
  created_at: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_name: string;
  entity_id: string;
  detail: string;
}

function toDisplay(row: AuditEntry): DisplayRow {
  return {
    id: row.id,
    created_at: row.created_at ?? "",
    actor: row.actor_email?.trim() || "System",
    action: row.action,
    entity_type: row.entity_type,
    entity_name: deriveName(row),
    entity_id: row.entity_id ?? "",
    detail: deriveDetail(row),
  };
}

function toCSV(rows: DisplayRow[]): string {
  const header = ["Timestamp", "Actor", "Action", "Entity Type", "Entity", "Entity ID", "Detail"];
  const escape = (v: string) => `"${(v ?? "").replace(/"/g, '""')}"`;
  const lines = [
    header.join(","),
    ...rows.map((r) =>
      [r.created_at, r.actor, formatAction(r.action), formatEntityType(r.entity_type), r.entity_name, r.entity_id, r.detail]
        .map(escape)
        .join(","),
    ),
  ];
  return lines.join("\n");
}

function downloadCSV(content: string, filename: string) {
  const blob = new Blob(["\uFEFF" + content], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Component ─────────────────────────────────────────────────────────────────

/** What the backend writes. services/audit_service.log_event names the first
 *  five; migration 266's triggers add the journal pair. Seeding the dropdowns
 *  with these keeps the choices stable as a CA narrows the window — a list
 *  derived from one page shrinks the more precisely you filter, which is the
 *  opposite of useful. */
const KNOWN_ENTITY_TYPES = [
  "journal_entry", "journal_line", "invoice", "compliance_record",
  "user_role", "client",
];
const KNOWN_ACTIONS = [
  "create", "update", "delete", "status_change", "approve",
];

/** One page. The log is a whole firm's history — it is asked, not downloaded. */
const PAGE_SIZE = 50;

function AuditLogContent() {
  const [rows, setRows] = useState<DisplayRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Filters. Every one of these now goes to the SERVER. They used to narrow a
  // fixed 200-row fetch in the browser, so "show me April" showed whatever
  // fell inside the most recent 200 events.
  const [filterDateFrom, setFilterDateFrom] = useState("");
  const [filterDateTo, setFilterDateTo] = useState("");
  const [filterAction, setFilterAction] = useState("");
  const [filterEntity, setFilterEntity] = useState("");
  // The one filter that stays in the browser, and it is honest about it: the
  // endpoint matches actor_id exactly and this box is a substring search over
  // an email. It says so beside the field.
  const [filterUser, setFilterUser] = useState("");

  const query = useCallback(() => ({
    date_from: filterDateFrom || undefined,
    date_to: filterDateTo || undefined,
    action: filterAction || undefined,
    entity_type: filterEntity || undefined,
    limit: PAGE_SIZE,
  }), [filterDateFrom, filterDateTo, filterAction, filterEntity]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Reads the authoritative audit_log via the Partner-gated backend endpoint
      // (RBAC: accounting:approve == Partner-only, matching this page's RoleGuard).
      const res = await api.audit.list(query());
      if (!res.success) throw new Error(res.error || "Failed to load audit log");
      setRows((res.data?.entries ?? []).map(toDisplay));
      setCursor(res.data?.next_cursor ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load audit log");
    } finally {
      setLoading(false);
    }
  }, [query]);

  const loadMore = useCallback(async () => {
    if (!cursor) return;
    setLoadingMore(true);
    try {
      const res = await api.audit.list({ ...query(), cursor });
      if (!res.success) throw new Error(res.error || "Failed to load audit log");
      setRows((prev) => [...prev, ...(res.data?.entries ?? []).map(toDisplay)]);
      setCursor(res.data?.next_cursor ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load audit log");
    } finally {
      setLoadingMore(false);
    }
  }, [cursor, query]);

  useEffect(() => { loadData(); }, [loadData]);

  // Derived from what is on screen, and that is now a PAGE rather than the
  // whole recent log — so the lists are seeded with the vocabulary the backend
  // actually writes (services/audit_service.log_event's docstring, plus the
  // trigger types of migrations 111 and 266). Deriving them from one page
  // alone would offer a CA fewer choices the more precisely they filtered.
  const entityOptions = useMemo(
    () => Array.from(new Set([...KNOWN_ENTITY_TYPES, ...rows.map((r) => r.entity_type)])).sort(),
    [rows],
  );
  const actionOptions = useMemo(
    () => Array.from(new Set([...KNOWN_ACTIONS, ...rows.map((r) => r.action)])).sort(),
    [rows],
  );

  // The date range, the action and the entity type are already applied BY THE
  // DATABASE — re-applying them here would be a second implementation of the
  // same rule, and the IST-vs-UTC boundary is exactly where the two would
  // disagree (see services/audit_query_service.py). Only the email substring
  // is the browser's, over the page in hand.
  const filtered = filterUser
    ? rows.filter((r) => r.actor.toLowerCase().includes(filterUser.toLowerCase()))
    : rows;

  function handleExport() {
    const csv = toCSV(filtered);
    const now = todayLocalISO();
    downloadCSV(csv, `audit-log-${now}.csv`);
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/settings" className="text-[#94A3B8] hover:text-[#475569]">
          <ChevronLeft size={18} />
        </Link>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <ShieldCheck size={16} className="text-blue-600" />
            <h1 className="text-xl font-semibold text-[#0F172A]">Audit Log</h1>
          </div>
          <p className="text-sm text-[#64748B] mt-0.5">
            Partner-only view — immutable trail of who changed what across invoices, journals, compliance, clients and users.
          </p>
        </div>
        <button
          onClick={() => loadData()}
          disabled={loading}
          className="flex items-center gap-1.5 text-xs border border-[#E2E8F0] text-[#475569] px-3 py-1.5 rounded-md hover:bg-[#F8FAFC] disabled:opacity-40"
        >
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
        <button
          onClick={handleExport}
          disabled={filtered.length === 0}
          className="flex items-center gap-1.5 text-xs border border-[#E2E8F0] text-[#475569] px-3 py-1.5 rounded-md hover:bg-[#F8FAFC] disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Download size={13} /> Export CSV
        </button>
      </div>

      {/* Filters */}
      <div className="bg-white border border-[#F1F5F9] rounded-xl px-5 py-4 grid grid-cols-2 md:grid-cols-5 gap-3">
        <div>
          <label className="text-xs text-[#64748B]">From Date</label>
          <input type="date" value={filterDateFrom} onChange={(e) => setFilterDateFrom(e.target.value)}
            className="block w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div>
          <label className="text-xs text-[#64748B]">To Date</label>
          <input type="date" value={filterDateTo} onChange={(e) => setFilterDateTo(e.target.value)}
            className="block w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div>
          <label className="text-xs text-[#64748B]">Action</label>
          <select value={filterAction} onChange={(e) => setFilterAction(e.target.value)}
            className="block w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All Actions</option>
            {actionOptions.map((a) => (
              <option key={a} value={a}>{formatAction(a)}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-[#64748B]">Entity Type</label>
          <select value={filterEntity} onChange={(e) => setFilterEntity(e.target.value)}
            className="block w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All Entities</option>
            {entityOptions.map((t) => (
              <option key={t} value={t}>{formatEntityType(t)}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-[#64748B]">
            User (email)
            <span className="ml-1 text-[#CBD5E1]" title="Searches the events already loaded, not the whole log — the server matches a user by id, not by an email fragment.">
              · loaded only
            </span>
          </label>
          <input value={filterUser} onChange={(e) => setFilterUser(e.target.value)}
            placeholder="Search loaded events…"
            className="block w-full mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
      </div>

      {/* Table */}
      <div className="bg-white border border-[#F1F5F9] rounded-xl overflow-hidden">
        {/* Column headers */}
        <div className="grid grid-cols-12 gap-2 px-5 py-2 text-xs font-semibold text-[#94A3B8] border-b border-[#F1F5F9] bg-[#F8FAFC]">
          <span className="col-span-2">Timestamp</span>
          <span className="col-span-2">User</span>
          <span className="col-span-2">Action</span>
          <span className="col-span-2">Entity Type</span>
          <span className="col-span-2">Entity Name</span>
          <span className="col-span-2">Detail</span>
        </div>

        {loading && (
          <div className="divide-y divide-[#F8FAFC]">
            {Array.from({ length: 6 }).map((_, r) => (
              <div key={r} className="grid grid-cols-12 gap-2 px-5 py-3 items-center">
                {Array.from({ length: 6 }).map((_, c) => (
                  <Skeleton key={c} className="col-span-2 h-3 w-3/4" />
                ))}
              </div>
            ))}
          </div>
        )}
        {!loading && error && (
          <div className="px-5 py-8 text-center space-y-3">
            <p className="text-sm text-red-600">{error}</p>
            <button onClick={() => loadData()} className="inline-flex items-center gap-1.5 text-xs border border-[#E2E8F0] text-[#475569] px-3 py-1.5 rounded-md hover:bg-[#F8FAFC]">
              <RefreshCw size={13} /> Retry
            </button>
          </div>
        )}
        {!loading && !error && rows.length === 0 && (
          <div className="px-5 py-12 text-center text-sm text-[#94A3B8]">
            No audit events recorded yet. Actions such as creating invoices, posting journals, updating
            compliance records and managing users will be recorded here automatically.
          </div>
        )}
        {!loading && !error && rows.length > 0 && filtered.length === 0 && (
          <div className="px-5 py-12 text-center text-sm text-[#94A3B8]">
            No audit events match the selected filters.
          </div>
        )}

        <div className="divide-y divide-[#F8FAFC]">
          {filtered.map((row) => (
            <div key={row.id} className="grid grid-cols-12 gap-2 px-5 py-3 hover:bg-[#F8FAFC] transition-colors items-start text-xs">
              <span className="col-span-2 text-[#64748B] tabular-nums">
                {formatDate(row.created_at.slice(0, 10))}
                <span className="block text-[#94A3B8] font-mono">{row.created_at.slice(11, 19)}</span>
              </span>
              <span className="col-span-2 text-[#334155] truncate" title={row.actor}>{row.actor}</span>
              <span className="col-span-2">
                <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${actionBadgeClass(row.action)}`}>
                  {formatAction(row.action)}
                </span>
              </span>
              <span className="col-span-2 text-[#475569]">{formatEntityType(row.entity_type)}</span>
              <span className="col-span-2 text-[#0F172A] truncate font-medium" title={row.entity_name}>
                {row.entity_name}
                {row.entity_id && row.entity_id !== row.entity_name && (
                  <span className="block font-mono text-[#94A3B8] text-[10px] truncate">{row.entity_id}</span>
                )}
              </span>
              <span className="col-span-2 text-[#64748B] truncate" title={row.detail}>{row.detail || "—"}</span>
            </div>
          ))}
        </div>

        {!loading && !error && filtered.length > 0 && (
          <div className="px-5 py-3 border-t border-gray-50 flex items-center justify-between gap-3">
            <span className="text-xs text-[#94A3B8]">
              Showing {filtered.length} event{filtered.length !== 1 ? "s" : ""}
              {filterUser && filtered.length !== rows.length
                ? ` of ${rows.length} loaded` : ""}
              {/* NOT "of N total". Counting the whole log to render a page is
                  the cost this screen stopped paying. */}
            </span>
            {cursor && (
              <button
                onClick={() => { void loadMore(); }}
                disabled={loadingMore}
                className="text-xs border border-[#E2E8F0] text-[#475569] px-3 py-1.5 rounded-md hover:bg-[#F8FAFC] disabled:opacity-40"
              >
                {loadingMore ? "Loading…" : "Load more"}
              </button>
            )}
          </div>
        )}
      </div>

      <p className="text-xs text-[#94A3B8]">
        Note: this is the authoritative, append-only audit trail — every sensitive change (invoices, journals,
        compliance records, clients, user/role changes and platform actions) is recorded server-side with the
        acting user, as the proviso to Rule 3(1) of the Companies (Accounts) Rules 2014 requires.
        Automated and background actions appear as “System”. Dates are IST.
        The filters above are applied in the database, so a date range searches the
        whole log rather than the events already on screen.
      </p>
    </div>
  );
}

export default function AuditLogPage() {
  return (
    <RoleGuard allowed={["Partner"]}>
      <AuditLogContent />
    </RoleGuard>
  );
}
