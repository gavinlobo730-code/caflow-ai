"use client";

import { useState, useEffect, useCallback } from "react";
import {
  ShieldAlert,
  AlertTriangle,
  AlertCircle,
  Info,
  CheckCircle,
  Loader2,
  Download,
  RefreshCw,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getClients } from "@/lib/data/clients";

// ─── Types ────────────────────────────────────────────────────────────────────

interface ComplianceEntry {
  id: string;
  client_id: string;
  filing_type: string;
  due_date: string;
  filing_status: string;
}

interface OverdueRisk {
  clientId: string;
  clientName: string;
  filingType: string;
  dueDate: string;
  daysOverdue: number;
  riskLevel: "high" | "medium" | "low";
}

interface InvalidGstinClient {
  clientId: string;
  clientName: string;
  gstin: string;
  reason: string;
}

interface InactiveClient {
  clientId: string;
  clientName: string;
  daysInactive: number;
}

interface RiskRegisterRow {
  clientName: string;
  riskType: string;
  description: string;
  severity: "critical" | "high" | "medium" | "low";
  action: string;
}

// CGST Act, Section 25 — GSTIN format: 2-digit state code + PAN + entity number + Z + check digit
const GSTIN_REGEX = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/;

function validateGstin(gstin: string): string | null {
  if (!gstin) return null;
  const trimmed = gstin.trim().toUpperCase();
  if (trimmed.length !== 15) return `Length is ${trimmed.length}, expected 15`;
  if (!GSTIN_REGEX.test(trimmed)) return "Format does not match state code + PAN + entity + Z + check";
  return null;
}

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).maybeSingle();
  if (!data?.firm_id) throw new Error("No firm found");
  return data.firm_id as string;
}

function daysBetween(dateStr: string, now: Date): number {
  return Math.floor((now.getTime() - new Date(dateStr).getTime()) / (1000 * 60 * 60 * 24));
}

function overdueRiskLevel(days: number): "high" | "medium" | "low" {
  if (days > 30) return "high";
  if (days >= 15) return "medium";
  return "low";
}

function riskColor(level: string) {
  const m: Record<string, string> = { critical: "text-red-700 bg-red-100", high: "text-red-700 bg-red-100", medium: "text-orange-700 bg-orange-100", low: "text-yellow-700 bg-yellow-100" };
  return m[level] ?? "text-gray-700 bg-gray-100";
}

function riskRowColor(level: string) {
  const m: Record<string, string> = { high: "bg-red-50", medium: "bg-orange-50", low: "bg-yellow-50" };
  return m[level] ?? "";
}

function exportCsv(rows: RiskRegisterRow[]) {
  const header = ["Client", "Risk Type", "Description", "Severity", "Recommended Action"];
  const lines = [header.join(","), ...rows.map((r) => [r.clientName, r.riskType, `"${r.description}"`, r.severity, `"${r.action}"`].join(","))];
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `risk-report-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function OverallScoreCard({ total }: { total: number }) {
  const items = total === 0
    ? { label: "All Clear", color: "text-green-600 bg-green-50 border-green-200", Icon: CheckCircle }
    : total <= 3
    ? { label: "Low Risk", color: "text-yellow-600 bg-yellow-50 border-yellow-200", Icon: Info }
    : total <= 8
    ? { label: "Medium Risk", color: "text-orange-600 bg-orange-50 border-orange-200", Icon: AlertTriangle }
    : { label: "High Risk", color: "text-red-600 bg-red-50 border-red-200", Icon: AlertCircle };
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

function MiniCard({ label, count, color, icon: Icon }: { label: string; count: number; color: string; icon: React.ElementType }) {
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

export default function RisksPage() {
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [overdueRisks, setOverdueRisks] = useState<OverdueRisk[]>([]);
  const [gstinRisks, setGstinRisks] = useState<InvalidGstinClient[]>([]);
  const [tdsRisks, setTdsRisks] = useState<OverdueRisk[]>([]);
  const [inactiveClients, setInactiveClients] = useState<InactiveClient[]>([]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setPageError(null);
    try {
      const [clients, firmId] = await Promise.all([getClients(), getFirmId()]);
      const sb = getSupabaseClient();
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const todayStr = today.toISOString().slice(0, 10);

      // Compliance calendar
      const { data: complianceData, error: compErr } = await sb
        .from("compliance_calendar")
        .select("id, client_id, filing_type, due_date, filing_status")
        .eq("firm_id", firmId)
        .lt("due_date", todayStr);

      const compliance: ComplianceEntry[] = compErr ? [] : ((complianceData ?? []) as ComplianceEntry[]);
      const clientMap: Record<string, string> = Object.fromEntries(clients.map((c) => [c.id, c.client_name]));

      // Overdue filing risk
      setOverdueRisks(
        compliance
          .filter((e) => e.filing_status !== "filed" && !["TDS24Q", "TDS26Q"].includes(e.filing_type))
          .map((e) => {
            const days = daysBetween(e.due_date, today);
            return { clientId: e.client_id, clientName: clientMap[e.client_id] ?? "Unknown", filingType: e.filing_type, dueDate: e.due_date, daysOverdue: days, riskLevel: overdueRiskLevel(days) };
          })
          .sort((a, b) => b.daysOverdue - a.daysOverdue)
      );

      // TDS default risk — IT Act Section 200A
      setTdsRisks(
        compliance
          .filter((e) => ["TDS24Q", "TDS26Q"].includes(e.filing_type) && e.filing_status !== "filed")
          .map((e) => ({ clientId: e.client_id, clientName: clientMap[e.client_id] ?? "Unknown", filingType: e.filing_type, dueDate: e.due_date, daysOverdue: daysBetween(e.due_date, today), riskLevel: "high" as const }))
          .sort((a, b) => b.daysOverdue - a.daysOverdue)
      );

      // GSTIN mismatch — CGST Act Section 25
      setGstinRisks(
        clients
          .filter((c) => c.gstin && c.gstin.trim().length > 0)
          .flatMap((c) => {
            const reason = validateGstin(c.gstin!);
            return reason ? [{ clientId: c.id, clientName: c.client_name, gstin: c.gstin!, reason }] : [];
          })
      );

      // Inactive clients (no entries in last 90 days)
      const ninetyAgo = new Date(today);
      ninetyAgo.setDate(ninetyAgo.getDate() - 90);
      const { data: recentData } = await sb.from("compliance_calendar").select("client_id").eq("firm_id", firmId).gte("due_date", ninetyAgo.toISOString().slice(0, 10));
      const activeIds = new Set((recentData ?? []).map((r: { client_id: string }) => r.client_id));
      setInactiveClients(clients.filter((c) => !activeIds.has(c.id)).map((c) => ({ clientId: c.id, clientName: c.client_name, daysInactive: 90 })));
    } catch (err) {
      setPageError(err instanceof Error ? err.message : "Failed to load risk data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const riskRegister: RiskRegisterRow[] = [
    ...overdueRisks.map((r) => ({ clientName: r.clientName, riskType: "Overdue Filing", description: `${r.filingType} overdue by ${r.daysOverdue} days (due ${r.dueDate})`, severity: r.riskLevel as "high" | "medium" | "low", action: "File immediately and pay late fee under CGST Act Section 47" })),
    ...tdsRisks.map((r) => ({ clientName: r.clientName, riskType: "TDS Default", description: `${r.filingType} overdue by ${r.daysOverdue} days — IT Act Section 200A interest applies`, severity: "high" as const, action: "File TDS return and compute interest u/s 201(1A)" })),
    ...gstinRisks.map((r) => ({ clientName: r.clientName, riskType: "GSTIN Mismatch", description: `GSTIN ${r.gstin} is invalid: ${r.reason}`, severity: "medium" as const, action: "Verify GSTIN on GST portal and update client record" })),
    ...inactiveClients.map((c) => ({ clientName: c.clientName, riskType: "Inactive Client", description: "No compliance entries in last 90 days", severity: "low" as const, action: "Confirm client status and add compliance calendar entries if active" })),
  ];

  const totalRisks = riskRegister.length;
  const highCount = riskRegister.filter((r) => r.severity === "high" || r.severity === "critical").length;
  const mediumCount = riskRegister.filter((r) => r.severity === "medium").length;
  const lowCount = riskRegister.filter((r) => r.severity === "low").length;

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Risk Intelligence</h1>
          <p className="text-sm text-gray-500 mt-0.5">Real-time risk monitoring across all clients</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={loadData} disabled={loading} className="flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50">
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
          {riskRegister.length > 0 && (
            <button onClick={() => exportCsv(riskRegister)} className="flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700">
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
          <AlertCircle className="h-10 w-10 text-red-400 mb-3" />
          <p className="text-sm font-medium text-red-700">{pageError}</p>
          <button onClick={loadData} className="mt-3 text-xs text-blue-600 hover:underline">Retry</button>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="sm:col-span-2 lg:col-span-1"><OverallScoreCard total={totalRisks} /></div>
            <MiniCard label="High / Critical" count={highCount} color="text-red-600 bg-red-50 border-red-200 border" icon={AlertCircle} />
            <MiniCard label="Medium Risk" count={mediumCount} color="text-orange-600 bg-orange-50 border-orange-200 border" icon={AlertTriangle} />
            <MiniCard label="Low Risk" count={lowCount} color="text-yellow-600 bg-yellow-50 border-yellow-200 border" icon={Info} />
          </div>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <AlertCircle size={16} className="text-red-500" />
                Overdue Filing Risk
                {overdueRisks.length > 0 && <span className="ml-auto text-xs font-medium bg-red-100 text-red-700 px-2 py-0.5 rounded-full">{overdueRisks.length} overdue</span>}
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {overdueRisks.length === 0 ? (
                <p className="px-6 py-4 text-sm text-gray-500">No overdue filings detected.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b border-gray-100 bg-gray-50 text-left"><th className="px-4 py-3 font-medium text-gray-500">Client</th><th className="px-4 py-3 font-medium text-gray-500">Filing Type</th><th className="px-4 py-3 font-medium text-gray-500">Due Date</th><th className="px-4 py-3 font-medium text-gray-500">Days Overdue</th><th className="px-4 py-3 font-medium text-gray-500">Risk Level</th></tr></thead>
                    <tbody className="divide-y divide-gray-50">
                      {overdueRisks.map((r, i) => (
                        <tr key={i} className={`hover:bg-gray-50 transition-colors ${riskRowColor(r.riskLevel)}`}>
                          <td className="px-4 py-3 font-medium text-gray-800">{r.clientName}</td>
                          <td className="px-4 py-3 text-gray-600">{r.filingType}</td>
                          <td className="px-4 py-3 text-gray-600">{r.dueDate}</td>
                          <td className="px-4 py-3 font-semibold text-gray-900">{r.daysOverdue}</td>
                          <td className="px-4 py-3"><span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${riskColor(r.riskLevel)}`}>{r.riskLevel}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <ShieldAlert size={16} className="text-orange-500" />
                GSTIN Mismatch Risk
                {gstinRisks.length > 0 && <span className="ml-auto text-xs font-medium bg-orange-100 text-orange-700 px-2 py-0.5 rounded-full">{gstinRisks.length} invalid</span>}
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {gstinRisks.length === 0 ? (
                <p className="px-6 py-4 text-sm text-gray-500">All GSTINs are valid.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b border-gray-100 bg-gray-50 text-left"><th className="px-4 py-3 font-medium text-gray-500">Client</th><th className="px-4 py-3 font-medium text-gray-500">GSTIN</th><th className="px-4 py-3 font-medium text-gray-500">Issue</th></tr></thead>
                    <tbody className="divide-y divide-gray-50">
                      {gstinRisks.map((r, i) => (
                        <tr key={i} className="hover:bg-gray-50 bg-orange-50 transition-colors">
                          <td className="px-4 py-3 font-medium text-gray-800">{r.clientName}</td>
                          <td className="px-4 py-3 font-mono text-gray-600">{r.gstin}</td>
                          <td className="px-4 py-3 text-orange-700">{r.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <AlertTriangle size={16} className="text-red-500" />
                TDS Default Risk
                {tdsRisks.length > 0 && <span className="ml-auto text-xs font-medium bg-red-100 text-red-700 px-2 py-0.5 rounded-full">{tdsRisks.length} defaulted</span>}
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {tdsRisks.length === 0 ? (
                <p className="px-6 py-4 text-sm text-gray-500">No TDS defaults detected.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b border-gray-100 bg-gray-50 text-left"><th className="px-4 py-3 font-medium text-gray-500">Client</th><th className="px-4 py-3 font-medium text-gray-500">Return Type</th><th className="px-4 py-3 font-medium text-gray-500">Due Date</th><th className="px-4 py-3 font-medium text-gray-500">Days Overdue</th></tr></thead>
                    <tbody className="divide-y divide-gray-50">
                      {tdsRisks.map((r, i) => (
                        <tr key={i} className="hover:bg-gray-50 bg-red-50 transition-colors">
                          <td className="px-4 py-3 font-medium text-gray-800">{r.clientName}</td>
                          <td className="px-4 py-3 text-gray-600">{r.filingType}</td>
                          <td className="px-4 py-3 text-gray-600">{r.dueDate}</td>
                          <td className="px-4 py-3 font-semibold text-red-700">{r.daysOverdue}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Info size={16} className="text-gray-400" />
                Inactive Clients (no entries in 90 days)
                {inactiveClients.length > 0 && <span className="ml-auto text-xs font-medium bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">{inactiveClients.length} inactive</span>}
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {inactiveClients.length === 0 ? (
                <p className="px-6 py-4 text-sm text-gray-500">All clients have recent activity.</p>
              ) : (
                <div className="flex flex-wrap gap-2 px-4 py-3">
                  {inactiveClients.map((c) => (
                    <span key={c.clientId} className="inline-flex items-center rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-medium text-gray-600">{c.clientName}</span>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {riskRegister.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <ShieldAlert size={16} className="text-blue-500" />
                  Risk Register — All Risks
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b border-gray-100 bg-gray-50 text-left"><th className="px-4 py-3 font-medium text-gray-500">Client</th><th className="px-4 py-3 font-medium text-gray-500">Risk Type</th><th className="px-4 py-3 font-medium text-gray-500">Description</th><th className="px-4 py-3 font-medium text-gray-500">Severity</th><th className="px-4 py-3 font-medium text-gray-500">Recommended Action</th></tr></thead>
                    <tbody className="divide-y divide-gray-50">
                      {riskRegister.map((r, i) => (
                        <tr key={i} className="hover:bg-gray-50 transition-colors">
                          <td className="px-4 py-3 font-medium text-gray-800">{r.clientName}</td>
                          <td className="px-4 py-3 text-gray-600">{r.riskType}</td>
                          <td className="px-4 py-3 text-gray-600 max-w-xs">{r.description}</td>
                          <td className="px-4 py-3"><span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${riskColor(r.severity)}`}>{r.severity}</span></td>
                          <td className="px-4 py-3 text-gray-600 max-w-xs text-xs">{r.action}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="border-t border-gray-100 px-4 py-2 text-xs text-gray-400">{riskRegister.length} risk{riskRegister.length !== 1 ? "s" : ""} in register</div>
              </CardContent>
            </Card>
          )}

          {totalRisks === 0 && (
            <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 py-20 text-center">
              <CheckCircle className="h-12 w-12 text-green-400 mb-3" />
              <p className="text-sm font-medium text-gray-700">No risks detected</p>
              <p className="text-xs text-gray-400 mt-1">All clients have valid GSTINs, no overdue filings, and recent activity.</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
