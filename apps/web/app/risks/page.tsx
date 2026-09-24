"use client";

/**
 * Risk Intelligence — the firm-wide statutory risk register.
 *
 * ── WHAT THIS SCREEN USED TO BE ─────────────────────────────────────────────
 * 856 lines that made six PostgREST reads of their own and derived NINE kinds
 * of statutory risk in the browser: which filings are overdue and how badly,
 * which TDS statements are in default, which GSTINs are wrong, which clients
 * have gone quiet, which advance-tax instalments were missed, which DSCs are
 * about to lapse, which loans are overdue, which deposits are maturing, and
 * which clients have no PAN. It cited CGST §47, IT §200A, §201(1A), §234B/C,
 * §139A and §194A while doing it.
 *
 * Every part of that is business logic in the frontend, which this codebase's
 * first rule forbids — and it was not abstract. `rbac()` ran on none of the six
 * reads and neither did `core.authz`'s assignment scope, so an Executive who
 * cannot see a client still read that client's compliance calendar, loans and
 * fixed deposits. Two statutory figures were wrong as a result; see
 * `apps/api/domain/risk/register.py`, which is now the rule.
 *
 * ── WHAT IT IS NOW ──────────────────────────────────────────────────────────
 * One call to `GET /api/risks/register`, and a renderer. **THE BROWSER HOLDS
 * NO PER-KIND KNOWLEDGE**: each row carries a `particulars` map the server
 * decided — "Filing Type" for an overdue return, "DSC Holder" for a
 * certificate, "Lender" and "Loan Type" for a loan — in display order, so the
 * nine hand-written tables collapse into one generic one. Adding a tenth kind
 * of risk is a change to the domain module and to nothing here.
 *
 * The CSV export builds from what the server sent, through the one CSV writer.
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  AlertTriangle,
  AlertCircle,
  Info,
  CheckCircle,
  Loader2,
  Download,
  RefreshCw,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import type { Column, FilterDef } from "@/lib/table/types";
import { formatPaise, formatDate } from "@/lib/services/formatting";
import { todayLocalISO } from "@/lib/dateMath";
import { downloadCsv, toCsvRows } from "@/lib/export/csv";
import { api } from "@/lib/api";

// ─── The server's shape ───────────────────────────────────────────────────────

interface RiskRow {
  client_id: string;
  client_name: string;
  risk_type: string;
  description: string;
  severity: "critical" | "high" | "medium" | "low";
  action: string;
  days_overdue: number | null;
  amount_paise: number | null;
  date: string | null;
  particulars: Record<string, string>;
}

interface RegisterPayload {
  as_at: string;
  counts: Record<string, number>;
  notes: string[];
  gaps: string[];
  rows: RiskRow[];
}

// The order the categories are shown in, worst first. A LABEL LIST, not a
// vocabulary: a kind the server sends that is missing here still renders, in
// its own section at the end, so a tenth risk cannot go unseen because nobody
// edited this array. That is the `table_4a_gaps` discipline — a nil meaning
// "we did not look" is not a nil meaning "there was none".
const CATEGORY_ORDER = [
  "Overdue Filing",
  "TDS Default",
  "Advance Tax Default",
  "GSTIN Mismatch",
  "DSC Expiry",
  "Loan Overdue",
  "Missing PAN",
  "Inactive Client",
  "FD Maturing Soon",
];

function riskColor(level: string) {
  const m: Record<string, string> = {
    critical: "text-state-problem bg-state-problem-surface",
    high: "text-state-problem bg-state-problem-surface",
    medium: "text-orange-700 bg-orange-100",
    low: "text-yellow-700 bg-yellow-100",
  };
  return m[level] ?? "text-ps-body bg-ps-muted";
}

function OverallScoreCard({ total }: { total: number }) {
  const items = total === 0
    ? { label: "All Clear", color: "text-green-600 bg-green-50 border-green-200", Icon: CheckCircle }
    : total <= 3
    ? { label: "Low Risk", color: "text-yellow-600 bg-yellow-50 border-yellow-200", Icon: Info }
    : total <= 8
    ? { label: "Medium Risk", color: "text-orange-600 bg-orange-50 border-orange-200", Icon: AlertTriangle }
    : { label: "High Risk", color: "text-red-600 bg-state-problem-surface border-state-problem-border", Icon: AlertCircle };
  const { label, color, Icon } = items;
  return (
    <div className={`rounded-xl border p-5 flex items-center gap-4 ${color}`}>
      <Icon size={36} />
      <div>
        <p className="text-xs font-semibold uppercase tracking-wider opacity-70">Overall Risk</p>
        <p className="text-2xl font-bold">{label}</p>
        <p className="text-sm opacity-70">{total} open risk{total !== 1 ? "s" : ""} detected</p>
      </div>
    </div>
  );
}

function MiniCard({ label, count, color, icon: Icon }: {
  label: string; count: number; color: string; icon: React.ElementType;
}) {
  return (
    <div className={`rounded-xl border p-4 flex items-center gap-3 ${color}`}>
      <Icon size={20} className="shrink-0" />
      <div>
        <p className="text-2xl font-bold">{count}</p>
        <p className="text-xs font-medium opacity-80">{label}</p>
      </div>
    </div>
  );
}

/**
 * One category's table, with the columns the SERVER named.
 *
 * The union of every row's `particulars` keys, in first-seen order, is the
 * column set — so two rows of one kind that carry different particulars (a
 * loan with no lender recorded, say) both render, with a dash where a value is
 * absent rather than the row being dropped.
 */
function CategoryCard({ title, rows }: { title: string; rows: RiskRow[] }) {
  const columns = useMemo(() => {
    const seen: string[] = [];
    for (const r of rows) {
      for (const k of Object.keys(r.particulars ?? {})) {
        if (!seen.includes(k)) seen.push(k);
      }
    }
    return seen;
  }, [rows]);

  if (rows.length === 0) return null;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <AlertCircle size={16} className="text-red-500" />
          {title}
          <span className="ml-auto text-xs font-medium bg-state-problem-surface text-state-problem px-2 py-0.5 rounded-full">
            {rows.length}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-ps-muted bg-ps-bg text-left">
                <th className="px-4 py-3 font-medium text-ps-label">Client</th>
                {columns.map((c) => (
                  <th key={c} className="px-4 py-3 font-medium text-ps-label">{c}</th>
                ))}
                <th className="px-4 py-3 font-medium text-ps-label">Severity</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.client_id}-${r.risk_type}-${i}`} className="border-b border-ps-muted last:border-0">
                  <td className="px-4 py-3 font-medium text-ps-ink">{r.client_name}</td>
                  {columns.map((c) => (
                    <td key={c} className="px-4 py-3 text-ps-label">
                      {r.particulars?.[c] ?? <span className="text-ps-hint">—</span>}
                    </td>
                  ))}
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${riskColor(r.severity)}`}>
                      {r.severity}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

export default function RisksPage() {
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [register, setRegister] = useState<RegisterPayload | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setPageError(null);
    try {
      // The GST workspace router answers a refusal as HTTP 200 with
      // `{success: false}`, so an unchecked call renders an empty register as
      // though it were a clean one. Check it.
      const res = (await api.risks.register()) as
        { success: boolean; data: RegisterPayload | null; error?: string | null };
      if (!res.success || !res.data) {
        throw new Error(res.error || "Could not load the risk register");
      }
      setRegister(res.data);
    } catch (err) {
      setPageError(err instanceof Error ? err.message : "Failed to load risk data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const rows = register?.rows ?? [];
  const counts = register?.counts ?? {};
  const total = counts.total ?? 0;

  // Worst first, then whatever the server sent that this list does not name.
  const grouped = useMemo(() => {
    const byType = new Map<string, RiskRow[]>();
    for (const r of rows) {
      const list = byType.get(r.risk_type) ?? [];
      list.push(r);
      byType.set(r.risk_type, list);
    }
    const named = CATEGORY_ORDER.filter((t) => byType.has(t));
    const unnamed = Array.from(byType.keys()).filter((t) => !CATEGORY_ORDER.includes(t)).sort();
    return [...named, ...unnamed].map((t) => ({ title: t, rows: byType.get(t) ?? [] }));
  }, [rows]);

  function exportCsv() {
    downloadCsv(`risk-report-${todayLocalISO()}.csv`, toCsvRows([
      ["Client", "Risk Type", "Description", "Severity", "Recommended Action"],
      ...rows.map((r) => [r.client_name, r.risk_type, r.description, r.severity, r.action]),
    ]));
  }

  const registerColumns: Column<RiskRow>[] = useMemo(() => [
    {
      key: "clientName", header: "Client", accessor: (r) => r.client_name,
      searchable: true, sortable: true, sticky: true, hideable: false,
      render: (r) => <span className="font-medium text-ps-ink">{r.client_name}</span>,
    },
    {
      key: "riskType", header: "Risk Type", accessor: (r) => r.risk_type, sortable: true,
      render: (r) => <span className="text-ps-label">{r.risk_type}</span>,
    },
    {
      key: "severity", header: "Severity", accessor: (r) => r.severity,
      render: (r) => (
        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${riskColor(r.severity)}`}>
          {r.severity}
        </span>
      ),
    },
    {
      key: "daysOverdue", header: "Days Overdue", accessor: (r) => r.days_overdue ?? null,
      sortable: true, align: "right",
      render: (r) => r.days_overdue == null
        ? <span className="text-ps-hint">—</span>
        : <span className="font-semibold text-ps-ink">{r.days_overdue}</span>,
    },
    {
      key: "amount", header: "Amount", accessor: (r) => r.amount_paise ?? null,
      sortable: true, align: "right",
      exportValue: (r) => (r.amount_paise == null ? "" : r.amount_paise / 100),
      render: (r) => r.amount_paise == null
        ? <span className="text-ps-hint">—</span>
        : <span className="text-ps-body">{formatPaise(r.amount_paise)}</span>,
    },
    {
      key: "date", header: "Date", accessor: (r) => r.date ?? "", sortable: true,
      render: (r) => <span className="text-ps-label">{r.date ? formatDate(r.date) : "—"}</span>,
    },
    {
      key: "description", header: "Description", accessor: (r) => r.description, searchable: true,
      render: (r) => <span className="text-ps-label max-w-xs block">{r.description}</span>,
    },
    {
      key: "action", header: "Recommended Action", accessor: (r) => r.action,
      render: (r) => <span className="text-ps-label max-w-xs text-xs block">{r.action}</span>,
    },
  ], []);

  // The category filter is built from what ARRIVED, not from a list kept here.
  // A hardcoded option list is how a screen comes to offer a category the
  // engine no longer emits, and to omit one it does.
  const registerFilters: FilterDef<RiskRow>[] = useMemo(() => [
    {
      key: "riskType", label: "Category", type: "select", accessor: (r) => r.risk_type,
      options: Array.from(new Set(rows.map((r) => r.risk_type))).sort().map((t) => ({ value: t, label: t })),
    },
    {
      key: "severity", label: "Severity", type: "select", accessor: (r) => r.severity,
      options: (["critical", "high", "medium", "low"]).map((s) => ({
        value: s, label: s[0].toUpperCase() + s.slice(1),
      })),
    },
  ], [rows]);

  return (
    <div className="p-6 max-w-ps-data mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ps-ink">Risk Intelligence</h1>
          <p className="text-sm text-ps-label mt-0.5">
            Statutory risk across the clients you can see
            {register?.as_at ? ` · as at ${formatDate(register.as_at)}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={loadData} disabled={loading} className="flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-ps-body hover:bg-ps-bg disabled:opacity-50">
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
          {rows.length > 0 && (
            <button onClick={exportCsv} className="flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700">
              <Download size={14} />
              Export CSV
            </button>
          )}
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-24"><Loader2 className="h-7 w-7 animate-spin text-blue-500" /></div>
      ) : pageError ? (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <AlertCircle className="h-10 w-10 text-red-600 mb-3" />
          <p className="text-sm font-medium text-state-problem">{pageError}</p>
          <button onClick={loadData} className="mt-3 text-xs text-blue-600 hover:underline">Retry</button>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="sm:col-span-2 lg:col-span-1"><OverallScoreCard total={total} /></div>
            <MiniCard label="High / Critical" count={(counts.high ?? 0) + (counts.critical ?? 0)} color="text-red-600 bg-state-problem-surface border-state-problem-border border" icon={AlertCircle} />
            <MiniCard label="Medium Risk" count={counts.medium ?? 0} color="text-orange-600 bg-orange-50 border-orange-200 border" icon={AlertTriangle} />
            <MiniCard label="Low Risk" count={counts.low ?? 0} color="text-yellow-600 bg-yellow-50 border-yellow-200 border" icon={Info} />
          </div>

          {/* What the engine could not establish, and the conventions it applied.
              Rendered because a register read without them reads as complete. */}
          {((register?.notes?.length ?? 0) > 0 || (register?.gaps?.length ?? 0) > 0) && (
            <Card>
              <CardContent className="py-4 space-y-1.5">
                {register?.gaps?.map((g) => (
                  <p key={g} className="text-xs text-orange-700 flex gap-2">
                    <AlertTriangle size={13} className="shrink-0 mt-0.5" />{g}
                  </p>
                ))}
                {register?.notes?.map((n) => (
                  <p key={n} className="text-xs text-ps-label flex gap-2">
                    <Info size={13} className="shrink-0 mt-0.5" />{n}
                  </p>
                ))}
              </CardContent>
            </Card>
          )}

          {total === 0 ? (
            <Card>
              <CardContent className="py-16 text-center">
                <CheckCircle className="h-10 w-10 text-green-600 mx-auto mb-3" />
                <p className="text-sm font-medium text-ps-ink">Nothing outstanding</p>
                <p className="text-xs text-ps-label mt-1">
                  No overdue filing, TDS default, invalid GSTIN, missed instalment,
                  expiring certificate, overdue loan or maturing deposit.
                </p>
              </CardContent>
            </Card>
          ) : (
            <>
              {grouped.map((g) => (
                <CategoryCard key={g.title} title={g.title} rows={g.rows} />
              ))}

              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Consolidated Register</CardTitle>
                </CardHeader>
                <CardContent className="p-0">
                  <DataTable
                    data={rows}
                    columns={registerColumns}
                    filters={registerFilters}
                    getRowId={(r) => `${r.client_id}|${r.risk_type}|${r.date ?? ""}|${r.description}`}
                    loading={loading}
                    error={pageError}
                    onRetry={loadData}
                    onRefresh={loadData}
                    searchPlaceholder="Search by client or description…"
                    initialSort={{ key: "daysOverdue", dir: "desc" }}
                    exportFilename="risk-register"
                    persistKey="risks.register"
                    emptyTitle="No risks in register"
                  />
                </CardContent>
              </Card>
            </>
          )}
        </>
      )}
    </div>
  );
}
