"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, Download, ShieldCheck } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { RoleGuard } from "@/components/RoleGuard";
import { formatDate } from "@/lib/services/formatting";

// ── Types ────────────────────────────────────────────────────────────────────

type ActionType = "Create" | "Update" | "Delete" | "Post";
type EntityType = "Client" | "Journal Entry" | "Compliance" | "Account";

interface AuditRow {
  id: string;
  timestamp: string;          // ISO string
  user: string;               // email or system
  action: ActionType;
  entity_type: EntityType;
  entity_id: string;
  entity_name: string;
  detail: string;             // "Old → New" or summary
  ip_address: string;         // Not available from Supabase metadata — placeholder
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function actionBadgeClass(action: ActionType): string {
  switch (action) {
    case "Create": return "bg-green-100 text-green-700";
    case "Update": return "bg-blue-100 text-blue-700";
    case "Delete": return "bg-red-100 text-red-700";
    case "Post":   return "bg-purple-100 text-purple-700";
    default:       return "bg-gray-100 text-gray-600";
  }
}

/**
 * Build a unified audit timeline by querying created_at / updated_at from key
 * tables. Because there is no dedicated audit_log table, we infer action type:
 *   - If created_at === updated_at → Create
 *   - Otherwise → Update
 * Journal entries with status "posted" get a "Post" action event too.
 */
async function fetchAuditLog(firmId: string): Promise<AuditRow[]> {
  const sb = getSupabaseClient();
  const rows: AuditRow[] = [];

  // ── Clients ────────────────────────────────────────────────────────────────
  const { data: clients } = await sb
    .from("clients")
    .select("id, name, created_at, updated_at, email")
    .eq("firm_id", firmId)
    .order("updated_at", { ascending: false })
    .limit(200);

  for (const c of clients ?? []) {
    const isCreate = c.created_at === c.updated_at;
    rows.push({
      id: `client-${c.id}-${isCreate ? "c" : "u"}`,
      timestamp: isCreate ? c.created_at : c.updated_at,
      user: c.email ?? "—",
      action: isCreate ? "Create" : "Update",
      entity_type: "Client",
      entity_id: c.id,
      entity_name: c.name ?? c.id,
      detail: isCreate ? "Client created" : "Client profile updated",
      ip_address: "—",
    });
  }

  // ── Journal Entries ────────────────────────────────────────────────────────
  const { data: journalEntries } = await sb
    .from("journal_entries")
    .select("id, narration, created_at, updated_at, status, entry_type, total_debit_paise")
    .eq("firm_id", firmId)
    .order("updated_at", { ascending: false })
    .limit(200);

  for (const je of journalEntries ?? []) {
    const isCreate = je.created_at === je.updated_at;
    const action: ActionType = je.status === "posted" && !isCreate ? "Post" : isCreate ? "Create" : "Update";
    rows.push({
      id: `je-${je.id}`,
      timestamp: je.updated_at ?? je.created_at,
      user: "—",
      action,
      entity_type: "Journal Entry",
      entity_id: je.id,
      entity_name: je.narration?.replace(/\[[A-Z]{3} [\d.]+ @ [\d.]+\]$/, "").trim() ?? je.id,
      detail: `${je.entry_type} — status: ${je.status}`,
      ip_address: "—",
    });
  }

  // ── Compliance Calendar ────────────────────────────────────────────────────
  const { data: compliance } = await sb
    .from("compliance_calendar")
    .select("id, task_name, created_at, updated_at, status")
    .eq("firm_id", firmId)
    .order("updated_at", { ascending: false })
    .limit(200);

  for (const cc of compliance ?? []) {
    const isCreate = cc.created_at === cc.updated_at;
    rows.push({
      id: `cc-${cc.id}`,
      timestamp: cc.updated_at ?? cc.created_at,
      user: "—",
      action: isCreate ? "Create" : "Update",
      entity_type: "Compliance",
      entity_id: cc.id,
      entity_name: cc.task_name ?? cc.id,
      detail: isCreate ? "Task created" : `Status → ${cc.status ?? "updated"}`,
      ip_address: "—",
    });
  }

  // ── Chart of Accounts ──────────────────────────────────────────────────────
  const { data: accounts } = await sb
    .from("accounts")
    .select("id, account_name, created_at, updated_at, is_active")
    .eq("firm_id", firmId)
    .order("updated_at", { ascending: false })
    .limit(200);

  for (const acc of accounts ?? []) {
    const isCreate = acc.created_at === acc.updated_at;
    const action: ActionType = !isCreate && acc.is_active === false ? "Delete" : isCreate ? "Create" : "Update";
    rows.push({
      id: `acc-${acc.id}`,
      timestamp: acc.updated_at ?? acc.created_at,
      user: "—",
      action,
      entity_type: "Account",
      entity_id: acc.id,
      entity_name: acc.account_name ?? acc.id,
      detail: isCreate ? "Account created" : acc.is_active === false ? "Account archived" : "Account updated",
      ip_address: "—",
    });
  }

  // Sort unified timeline descending by timestamp
  rows.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  return rows;
}

/** Convert rows to CSV string */
function toCSV(rows: AuditRow[]): string {
  const header = ["Timestamp", "User", "Action", "Entity Type", "Entity ID", "Entity Name", "Detail", "IP Address"];
  const escape = (v: string) => `"${v.replace(/"/g, '""')}"`;
  const lines = [
    header.join(","),
    ...rows.map((r) =>
      [
        r.timestamp,
        r.user,
        r.action,
        r.entity_type,
        r.entity_id,
        r.entity_name,
        r.detail,
        r.ip_address,
      ]
        .map(escape)
        .join(",")
    ),
  ];
  return lines.join("\n");
}

function downloadCSV(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Component ─────────────────────────────────────────────────────────────────

function AuditLogContent() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [filterDateFrom, setFilterDateFrom] = useState("");
  const [filterDateTo, setFilterDateTo] = useState("");
  const [filterAction, setFilterAction] = useState<ActionType | "">("");
  const [filterEntity, setFilterEntity] = useState<EntityType | "">("");
  const [filterUser, setFilterUser] = useState("");

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const sb = getSupabaseClient();
      const { data: { session } } = await sb.auth.getSession();
      if (!session) throw new Error("Not authenticated");
      const { data: userData } = await sb
        .from("users")
        .select("firm_id")
        .eq("auth_user_id", session.user.id)
        .single();
      if (!userData?.firm_id) throw new Error("Firm not found");
      const data = await fetchAuditLog(userData.firm_id as string);
      setRows(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load audit log");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  // Apply filters
  const filtered = rows.filter((r) => {
    const ts = r.timestamp.slice(0, 10); // YYYY-MM-DD
    if (filterDateFrom && ts < filterDateFrom) return false;
    if (filterDateTo && ts > filterDateTo) return false;
    if (filterAction && r.action !== filterAction) return false;
    if (filterEntity && r.entity_type !== filterEntity) return false;
    if (filterUser && !r.user.toLowerCase().includes(filterUser.toLowerCase())) return false;
    return true;
  });

  function handleExport() {
    const csv = toCSV(filtered);
    const now = new Date().toISOString().slice(0, 10);
    downloadCSV(csv, `audit-log-${now}.csv`);
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/settings" className="text-gray-400 hover:text-gray-600">
          <ChevronLeft size={18} />
        </Link>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <ShieldCheck size={16} className="text-blue-600" />
            <h1 className="text-xl font-semibold text-gray-900">Audit Log</h1>
          </div>
          <p className="text-sm text-gray-500 mt-0.5">
            Partner-only view — timeline of all changes across clients, journals, compliance and accounts.
          </p>
        </div>
        <button
          onClick={handleExport}
          disabled={filtered.length === 0}
          className="flex items-center gap-1.5 text-xs border border-gray-200 text-gray-600 px-3 py-1.5 rounded-md hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Download size={13} /> Export CSV
        </button>
      </div>

      {/* Filters */}
      <div className="bg-white border border-gray-100 rounded-xl px-5 py-4 grid grid-cols-2 md:grid-cols-5 gap-3">
        <div>
          <label className="text-xs text-gray-500">From Date</label>
          <input type="date" value={filterDateFrom} onChange={(e) => setFilterDateFrom(e.target.value)}
            className="block w-full mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div>
          <label className="text-xs text-gray-500">To Date</label>
          <input type="date" value={filterDateTo} onChange={(e) => setFilterDateTo(e.target.value)}
            className="block w-full mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div>
          <label className="text-xs text-gray-500">Action</label>
          <select value={filterAction} onChange={(e) => setFilterAction(e.target.value as ActionType | "")}
            className="block w-full mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All Actions</option>
            {(["Create", "Update", "Delete", "Post"] as ActionType[]).map((a) => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500">Entity Type</label>
          <select value={filterEntity} onChange={(e) => setFilterEntity(e.target.value as EntityType | "")}
            className="block w-full mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All Entities</option>
            {(["Client", "Journal Entry", "Compliance", "Account"] as EntityType[]).map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500">User (email)</label>
          <input value={filterUser} onChange={(e) => setFilterUser(e.target.value)}
            placeholder="Search…"
            className="block w-full mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
      </div>

      {/* Table */}
      <div className="bg-white border border-gray-100 rounded-xl overflow-hidden">
        {/* Column headers */}
        <div className="grid grid-cols-12 gap-2 px-5 py-2 text-xs font-semibold text-gray-400 border-b border-gray-100 bg-gray-50">
          <span className="col-span-2">Timestamp</span>
          <span className="col-span-2">User</span>
          <span className="col-span-1">Action</span>
          <span className="col-span-2">Entity Type</span>
          <span className="col-span-3">Entity Name</span>
          <span className="col-span-1">IP Address</span>
          <span className="col-span-1">Detail</span>
        </div>

        {loading && (
          <div className="px-5 py-12 text-center text-sm text-gray-400 animate-pulse">Loading audit log…</div>
        )}
        {!loading && error && (
          <div className="px-5 py-6 text-center text-sm text-red-600">{error}</div>
        )}
        {!loading && !error && filtered.length === 0 && (
          <div className="px-5 py-12 text-center text-sm text-gray-400">
            No audit events found for the selected filters.
          </div>
        )}

        <div className="divide-y divide-gray-50">
          {filtered.map((row) => (
            <div key={row.id} className="grid grid-cols-12 gap-2 px-5 py-3 hover:bg-gray-50 transition-colors items-start text-xs">
              <span className="col-span-2 text-gray-500 tabular-nums">
                {formatDate(row.timestamp.slice(0, 10))}
                <span className="block text-gray-400 font-mono">{row.timestamp.slice(11, 19)}</span>
              </span>
              <span className="col-span-2 text-gray-700 truncate" title={row.user}>{row.user}</span>
              <span className="col-span-1">
                <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${actionBadgeClass(row.action)}`}>
                  {row.action}
                </span>
              </span>
              <span className="col-span-2 text-gray-600">{row.entity_type}</span>
              <span className="col-span-3 text-gray-900 truncate font-medium" title={row.entity_name}>
                {row.entity_name}
                <span className="block font-mono text-gray-400 text-[10px] truncate">{row.entity_id}</span>
              </span>
              <span className="col-span-1 text-gray-400 font-mono">{row.ip_address}</span>
              <span className="col-span-1 text-gray-500 truncate" title={row.detail}>{row.detail}</span>
            </div>
          ))}
        </div>

        {!loading && filtered.length > 0 && (
          <div className="px-5 py-3 border-t border-gray-50 text-xs text-gray-400">
            Showing {filtered.length} event{filtered.length !== 1 ? "s" : ""}
            {filtered.length !== rows.length ? ` (filtered from ${rows.length} total)` : ""}
          </div>
        )}
      </div>

      <p className="text-xs text-gray-400">
        Note: Audit events are reconstructed from table timestamps. IP address tracking requires a dedicated
        audit_log table with server-side logging. User attribution is available only where email is stored on the record.
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
