"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  ShieldAlert,
  AlertTriangle,
  AlertCircle,
  Info,
  CheckCircle,
  Loader2,
  Download,
  RefreshCw,
  KeyRound,
  Landmark,
  CalendarClock,
  UserX,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getClients } from "@/lib/data/clients";
import { DataTable } from "@/components/ui/data-table";
import type { Column, FilterDef } from "@/lib/table/types";
import { formatPaise, formatDate } from "@/lib/services/formatting";
import { todayLocalISO } from "@/lib/dateMath";

// ─── Types ────────────────────────────────────────────────────────────────────

interface ComplianceEntry {
  id: string;
  client_id: string;
  compliance_type: string;
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
  // Optional sortable dimensions carried from the per-category source rows so the
  // unified register can sort by days-overdue / amount / date. Undefined where the
  // category has no such dimension (nullish sinks to the end when sorting).
  daysOverdue?: number;
  amountPaise?: number; // integer paise (CGST Act) — never floating point
  date?: string; // ISO date (due / expiry / maturity) for the row
}

interface AdvanceTaxRisk {
  clientId: string;
  clientName: string;
  installment: string;
  dueDate: string;
  daysOverdue: number;
}

interface DscExpiryRisk {
  clientId: string;
  clientName: string;
  dscHolder: string;
  expiryDate: string;
  daysLeft: number;
}

interface LoanOverdueRisk {
  clientId: string;
  clientName: string;
  lenderName: string;
  loanType: string;
  outstandingPaise: number;
}

interface FdMaturityRisk {
  clientId: string;
  clientName: string;
  bankName: string;
  maturityDate: string;
  daysLeft: number;
  maturityAmountPaise: number;
}

interface MissingPanRisk {
  clientId: string;
  clientName: string;
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
  return m[level] ?? "text-[#334155] bg-[#F1F5F9]";
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
  a.download = `risk-report-${todayLocalISO()}.csv`;
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
  const [advanceTaxRisks, setAdvanceTaxRisks] = useState<AdvanceTaxRisk[]>([]);
  const [dscExpiryRisks, setDscExpiryRisks] = useState<DscExpiryRisk[]>([]);
  const [loanOverdueRisks, setLoanOverdueRisks] = useState<LoanOverdueRisk[]>([]);
  const [fdMaturityRisks, setFdMaturityRisks] = useState<FdMaturityRisk[]>([]);
  const [missingPanRisks, setMissingPanRisks] = useState<MissingPanRisk[]>([]);

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
        .select("id, client_id, compliance_type, due_date, filing_status")
        .eq("firm_id", firmId)
        .lt("due_date", todayStr);

      const compliance: ComplianceEntry[] = compErr ? [] : ((complianceData ?? []) as ComplianceEntry[]);
      const clientMap: Record<string, string> = Object.fromEntries(clients.map((c) => [c.id, c.client_name]));

      // Overdue filing risk
      setOverdueRisks(
        compliance
          .filter((e) => e.filing_status !== "filed" && !["TDS24Q", "TDS26Q"].includes(e.compliance_type))
          .map((e) => {
            const days = daysBetween(e.due_date, today);
            return { clientId: e.client_id, clientName: clientMap[e.client_id] ?? "Unknown", filingType: e.compliance_type, dueDate: e.due_date, daysOverdue: days, riskLevel: overdueRiskLevel(days) };
          })
          .sort((a, b) => b.daysOverdue - a.daysOverdue)
      );

      // TDS default risk — IT Act Section 200A
      setTdsRisks(
        compliance
          .filter((e) => ["TDS24Q", "TDS26Q"].includes(e.compliance_type) && e.filing_status !== "filed")
          .map((e) => ({ clientId: e.client_id, clientName: clientMap[e.client_id] ?? "Unknown", filingType: e.compliance_type, dueDate: e.due_date, daysOverdue: daysBetween(e.due_date, today), riskLevel: "high" as const }))
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

      // Missing PAN — blocks TDS deduction and ITR filing (IT Act Section 139A)
      setMissingPanRisks(
        clients
          .filter((c) => !c.pan || c.pan.trim().length === 0)
          .map((c) => ({ clientId: c.id, clientName: c.client_name }))
      );

      // Advance Tax Default — IT Act Section 208/234B/234C
      // Due dates: 15 Jun (15%), 15 Sep (45%), 15 Dec (75%), 15 Mar (100%)
      const curYear = today.getMonth() >= 3 ? today.getFullYear() : today.getFullYear() - 1;
      const advanceTaxInstallments = [
        { label: "1st Installment (15%)", date: `${curYear}-06-15` },
        { label: "2nd Installment (45%)", date: `${curYear}-09-15` },
        { label: "3rd Installment (75%)", date: `${curYear}-12-15` },
        { label: "4th Installment (100%)", date: `${curYear + 1}-03-15` },
      ];
      const { data: advTaxData } = await sb
        .from("compliance_calendar")
        .select("client_id, compliance_type, due_date, filing_status")
        .eq("firm_id", firmId)
        .eq("compliance_type", "ADVANCE_TAX")
        .lt("due_date", todayStr);
      const filedAdvTax = new Set(
        ((advTaxData ?? []) as { client_id: string; due_date: string; filing_status: string }[])
          .filter((e) => e.filing_status === "filed")
          .map((e) => `${e.client_id}|${e.due_date}`)
      );
      const advRisks: AdvanceTaxRisk[] = [];
      for (const client of clients) {
        for (const inst of advanceTaxInstallments) {
          if (inst.date < todayStr && !filedAdvTax.has(`${client.id}|${inst.date}`)) {
            // Only flag if there's a compliance entry for this client (i.e. they're tracked for advance tax)
            const tracked = (advTaxData ?? []) as { client_id: string }[];
            if (tracked.some((e) => e.client_id === client.id)) {
              advRisks.push({
                clientId: client.id,
                clientName: client.client_name,
                installment: inst.label,
                dueDate: inst.date,
                daysOverdue: daysBetween(inst.date, today),
              });
            }
          }
        }
      }
      setAdvanceTaxRisks(advRisks);

      // DSC Expiry — within 60 days (IT Act Rule 12 — digital signature for e-filing)
      const sixtyAhead = new Date(today);
      sixtyAhead.setDate(sixtyAhead.getDate() + 60);
      const sixtyAheadStr = sixtyAhead.toISOString().slice(0, 10);
      const { data: dscData } = await sb
        .from("dsc_tracker")
        .select("client_id, dsc_holder_name, expiry_date")
        .eq("firm_id", firmId)
        .lte("expiry_date", sixtyAheadStr)
        .gte("expiry_date", todayStr);
      setDscExpiryRisks(
        ((dscData ?? []) as { client_id: string; dsc_holder_name: string; expiry_date: string }[]).map((d) => ({
          clientId: d.client_id,
          clientName: clientMap[d.client_id] ?? "Unknown",
          dscHolder: d.dsc_holder_name,
          expiryDate: d.expiry_date,
          daysLeft: Math.ceil((new Date(d.expiry_date).getTime() - today.getTime()) / 86400000),
        }))
      );

      // Loan Overdue
      const { data: loanData } = await sb
        .from("loans")
        .select("client_id, lender_name, loan_type, outstanding_paise")
        .eq("firm_id", firmId)
        .eq("status", "overdue");
      setLoanOverdueRisks(
        ((loanData ?? []) as { client_id: string; lender_name: string; loan_type: string; outstanding_paise: number }[]).map((l) => ({
          clientId: l.client_id,
          clientName: clientMap[l.client_id] ?? "Unknown",
          lenderName: l.lender_name,
          loanType: l.loan_type,
          outstandingPaise: l.outstanding_paise,
        }))
      );

      // FD Maturity within 30 days — Section 194A TDS on interest
      const thirtyAhead = new Date(today);
      thirtyAhead.setDate(thirtyAhead.getDate() + 30);
      const { data: fdData } = await sb
        .from("fixed_deposits")
        .select("client_id, bank_name, maturity_date, maturity_amount_paise")
        .eq("firm_id", firmId)
        .eq("status", "active")
        .lte("maturity_date", thirtyAhead.toISOString().slice(0, 10))
        .gte("maturity_date", todayStr);
      setFdMaturityRisks(
        ((fdData ?? []) as { client_id: string; bank_name: string; maturity_date: string; maturity_amount_paise: number }[]).map((f) => ({
          clientId: f.client_id,
          clientName: clientMap[f.client_id] ?? "Unknown",
          bankName: f.bank_name,
          maturityDate: f.maturity_date,
          daysLeft: Math.ceil((new Date(f.maturity_date).getTime() - today.getTime()) / 86400000),
          maturityAmountPaise: f.maturity_amount_paise,
        }))
      );
    } catch (err) {
      setPageError(err instanceof Error ? err.message : "Failed to load risk data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const riskRegister: RiskRegisterRow[] = [
    ...overdueRisks.map((r) => ({ clientName: r.clientName, riskType: "Overdue Filing", description: `${r.filingType} overdue by ${r.daysOverdue} days (due ${r.dueDate})`, severity: r.riskLevel as "high" | "medium" | "low", action: "File immediately and pay late fee under CGST Act Section 47", daysOverdue: r.daysOverdue, date: r.dueDate })),
    ...tdsRisks.map((r) => ({ clientName: r.clientName, riskType: "TDS Default", description: `${r.filingType} overdue by ${r.daysOverdue} days — IT Act Section 200A interest applies`, severity: "high" as const, action: "File TDS return and compute interest u/s 201(1A)", daysOverdue: r.daysOverdue, date: r.dueDate })),
    ...gstinRisks.map((r) => ({ clientName: r.clientName, riskType: "GSTIN Mismatch", description: `GSTIN ${r.gstin} is invalid: ${r.reason}`, severity: "medium" as const, action: "Verify GSTIN on GST portal and update client record" })),
    ...inactiveClients.map((c) => ({ clientName: c.clientName, riskType: "Inactive Client", description: "No compliance entries in last 90 days", severity: "low" as const, action: "Confirm client status and add compliance calendar entries if active" })),
    ...advanceTaxRisks.map((r) => ({ clientName: r.clientName, riskType: "Advance Tax Default", description: `${r.installment} not filed — due ${r.dueDate}, ${r.daysOverdue} days overdue`, severity: "high" as const, action: "Pay advance tax with interest u/s 234B/234C of IT Act", daysOverdue: r.daysOverdue, date: r.dueDate })),
    ...dscExpiryRisks.map((r) => ({ clientName: r.clientName, riskType: "DSC Expiry", description: `DSC of ${r.dscHolder} expires on ${r.expiryDate} (${r.daysLeft} days left)`, severity: (r.daysLeft <= 15 ? "high" : "medium") as "high" | "medium", action: "Renew DSC before expiry — required for e-filing under IT Act Rule 12", date: r.expiryDate })),
    ...loanOverdueRisks.map((r) => ({ clientName: r.clientName, riskType: "Loan Overdue", description: `${r.loanType} from ${r.lenderName} is overdue — ₹${(r.outstandingPaise / 100).toLocaleString("en-IN")} outstanding`, severity: "high" as const, action: "Contact lender immediately — overdue may affect credit rating and attract penal interest", amountPaise: r.outstandingPaise })),
    ...fdMaturityRisks.map((r) => ({ clientName: r.clientName, riskType: "FD Maturing Soon", description: `FD at ${r.bankName} matures on ${r.maturityDate} (${r.daysLeft} days) — ₹${(r.maturityAmountPaise / 100).toLocaleString("en-IN")}`, severity: "low" as const, action: "Advise client on renewal or withdrawal — TDS applicable u/s 194A if interest > ₹40,000", amountPaise: r.maturityAmountPaise, date: r.maturityDate })),
    ...missingPanRisks.map((r) => ({ clientName: r.clientName, riskType: "Missing PAN", description: "Client has no PAN on record", severity: "medium" as const, action: "Obtain PAN — mandatory for TDS deduction and ITR filing u/s 139A of IT Act" })),
  ];

  const totalRisks = riskRegister.length;
  const highCount = riskRegister.filter((r) => r.severity === "high" || r.severity === "critical").length;
  const mediumCount = riskRegister.filter((r) => r.severity === "medium").length;
  const lowCount = riskRegister.filter((r) => r.severity === "low").length;

  // ── Risk Register DataTable: columns / filters ───────────────────────────────
  // Amounts are integer paise (CGST Act) — accessor returns paise for numeric
  // sorting; the cell renders via the shared formatPaise, exported in rupees.
  const registerColumns: Column<RiskRegisterRow>[] = useMemo(() => [
    {
      key: "clientName", header: "Client", accessor: (r) => r.clientName,
      searchable: true, sortable: true, sticky: true, hideable: false,
      render: (r) => <span className="font-medium text-[#1E293B]">{r.clientName}</span>,
    },
    {
      key: "riskType", header: "Risk Type", accessor: (r) => r.riskType, sortable: true,
      render: (r) => <span className="text-[#475569]">{r.riskType}</span>,
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
      key: "daysOverdue", header: "Days Overdue", accessor: (r) => r.daysOverdue ?? null,
      sortable: true, align: "right",
      render: (r) =>
        r.daysOverdue == null ? <span className="text-[#94A3B8]">—</span> : <span className="font-semibold text-[#0F172A]">{r.daysOverdue}</span>,
    },
    {
      key: "amount", header: "Amount", accessor: (r) => r.amountPaise ?? null,
      sortable: true, align: "right", exportValue: (r) => (r.amountPaise == null ? "" : r.amountPaise / 100),
      render: (r) =>
        r.amountPaise == null ? <span className="text-[#94A3B8]">—</span> : <span className="text-[#334155]">{formatPaise(r.amountPaise)}</span>,
    },
    {
      key: "date", header: "Date", accessor: (r) => r.date ?? "", sortable: true,
      render: (r) => <span className="text-[#475569]">{r.date ? formatDate(r.date) : "—"}</span>,
    },
    {
      key: "description", header: "Description", accessor: (r) => r.description, searchable: true,
      render: (r) => <span className="text-[#475569] max-w-xs block">{r.description}</span>,
    },
    {
      key: "action", header: "Recommended Action", accessor: (r) => r.action,
      render: (r) => <span className="text-[#475569] max-w-xs text-xs block">{r.action}</span>,
    },
  ], []);

  const registerFilters: FilterDef<RiskRegisterRow>[] = useMemo(() => [
    {
      key: "riskType", label: "Category", type: "select", accessor: (r) => r.riskType,
      options: [
        "Overdue Filing",
        "TDS Default",
        "GSTIN Mismatch",
        "Inactive Client",
        "Advance Tax Default",
        "DSC Expiry",
        "Loan Overdue",
        "FD Maturing Soon",
        "Missing PAN",
      ].map((t) => ({ value: t, label: t })),
    },
    {
      key: "severity", label: "Severity", type: "select", accessor: (r) => r.severity,
      options: (["critical", "high", "medium", "low"]).map((s) => ({ value: s, label: s[0].toUpperCase() + s.slice(1) })),
    },
  ], []);

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">Risk Intelligence</h1>
          <p className="text-sm text-[#64748B] mt-0.5">Real-time risk monitoring across all clients</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={loadData} disabled={loading} className="flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-[#334155] hover:bg-[#F8FAFC] disabled:opacity-50">
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
          <AlertCircle className="h-10 w-10 text-red-600 mb-3" />
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
                <p className="px-6 py-4 text-sm text-[#64748B]">No overdue filings detected.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b border-[#F1F5F9] bg-[#F8FAFC] text-left"><th className="px-4 py-3 font-medium text-[#64748B]">Client</th><th className="px-4 py-3 font-medium text-[#64748B]">Filing Type</th><th className="px-4 py-3 font-medium text-[#64748B]">Due Date</th><th className="px-4 py-3 font-medium text-[#64748B]">Days Overdue</th><th className="px-4 py-3 font-medium text-[#64748B]">Risk Level</th></tr></thead>
                    <tbody className="divide-y divide-[#F8FAFC]">
                      {overdueRisks.map((r, i) => (
                        <tr key={i} className={`hover:bg-[#F8FAFC] transition-colors ${riskRowColor(r.riskLevel)}`}>
                          <td className="px-4 py-3 font-medium text-[#1E293B]">{r.clientName}</td>
                          <td className="px-4 py-3 text-[#475569]">{r.filingType}</td>
                          <td className="px-4 py-3 text-[#475569]">{r.dueDate}</td>
                          <td className="px-4 py-3 font-semibold text-[#0F172A]">{r.daysOverdue}</td>
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
                <p className="px-6 py-4 text-sm text-[#64748B]">All GSTINs are valid.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b border-[#F1F5F9] bg-[#F8FAFC] text-left"><th className="px-4 py-3 font-medium text-[#64748B]">Client</th><th className="px-4 py-3 font-medium text-[#64748B]">GSTIN</th><th className="px-4 py-3 font-medium text-[#64748B]">Issue</th></tr></thead>
                    <tbody className="divide-y divide-[#F8FAFC]">
                      {gstinRisks.map((r, i) => (
                        <tr key={i} className="hover:bg-[#F8FAFC] bg-orange-50 transition-colors">
                          <td className="px-4 py-3 font-medium text-[#1E293B]">{r.clientName}</td>
                          <td className="px-4 py-3 font-mono text-[#475569]">{r.gstin}</td>
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
                <p className="px-6 py-4 text-sm text-[#64748B]">No TDS defaults detected.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b border-[#F1F5F9] bg-[#F8FAFC] text-left"><th className="px-4 py-3 font-medium text-[#64748B]">Client</th><th className="px-4 py-3 font-medium text-[#64748B]">Return Type</th><th className="px-4 py-3 font-medium text-[#64748B]">Due Date</th><th className="px-4 py-3 font-medium text-[#64748B]">Days Overdue</th></tr></thead>
                    <tbody className="divide-y divide-[#F8FAFC]">
                      {tdsRisks.map((r, i) => (
                        <tr key={i} className="hover:bg-[#F8FAFC] bg-red-50 transition-colors">
                          <td className="px-4 py-3 font-medium text-[#1E293B]">{r.clientName}</td>
                          <td className="px-4 py-3 text-[#475569]">{r.filingType}</td>
                          <td className="px-4 py-3 text-[#475569]">{r.dueDate}</td>
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
                <Info size={16} className="text-[#94A3B8]" />
                Inactive Clients (no entries in 90 days)
                {inactiveClients.length > 0 && <span className="ml-auto text-xs font-medium bg-[#F1F5F9] text-[#475569] px-2 py-0.5 rounded-full">{inactiveClients.length} inactive</span>}
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {inactiveClients.length === 0 ? (
                <p className="px-6 py-4 text-sm text-[#64748B]">All clients have recent activity.</p>
              ) : (
                <div className="flex flex-wrap gap-2 px-4 py-3">
                  {inactiveClients.map((c) => (
                    <span key={c.clientId} className="inline-flex items-center rounded-full border border-[#E2E8F0] bg-[#F8FAFC] px-3 py-1 text-xs font-medium text-[#475569]">{c.clientName}</span>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Advance Tax Default */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <CalendarClock size={16} className="text-red-500" />
                Advance Tax Default Risk
                {advanceTaxRisks.length > 0 && <span className="ml-auto text-xs font-medium bg-red-100 text-red-700 px-2 py-0.5 rounded-full">{advanceTaxRisks.length} defaulted</span>}
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {advanceTaxRisks.length === 0 ? (
                <p className="px-6 py-4 text-sm text-[#64748B]">No advance tax defaults detected.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b border-[#F1F5F9] bg-[#F8FAFC] text-left"><th className="px-4 py-3 font-medium text-[#64748B]">Client</th><th className="px-4 py-3 font-medium text-[#64748B]">Installment</th><th className="px-4 py-3 font-medium text-[#64748B]">Due Date</th><th className="px-4 py-3 font-medium text-[#64748B]">Days Overdue</th></tr></thead>
                    <tbody className="divide-y divide-[#F8FAFC]">
                      {advanceTaxRisks.map((r, i) => (
                        <tr key={i} className="hover:bg-[#F8FAFC] bg-red-50 transition-colors">
                          <td className="px-4 py-3 font-medium text-[#1E293B]">{r.clientName}</td>
                          <td className="px-4 py-3 text-[#475569]">{r.installment}</td>
                          <td className="px-4 py-3 text-[#475569]">{r.dueDate}</td>
                          <td className="px-4 py-3 font-semibold text-red-700">{r.daysOverdue}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          {/* DSC Expiry */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <KeyRound size={16} className="text-orange-500" />
                DSC Expiry Risk
                {dscExpiryRisks.length > 0 && <span className="ml-auto text-xs font-medium bg-orange-100 text-orange-700 px-2 py-0.5 rounded-full">{dscExpiryRisks.length} expiring</span>}
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {dscExpiryRisks.length === 0 ? (
                <p className="px-6 py-4 text-sm text-[#64748B]">No DSCs expiring in the next 60 days.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b border-[#F1F5F9] bg-[#F8FAFC] text-left"><th className="px-4 py-3 font-medium text-[#64748B]">Client</th><th className="px-4 py-3 font-medium text-[#64748B]">DSC Holder</th><th className="px-4 py-3 font-medium text-[#64748B]">Expiry Date</th><th className="px-4 py-3 font-medium text-[#64748B]">Days Left</th></tr></thead>
                    <tbody className="divide-y divide-[#F8FAFC]">
                      {dscExpiryRisks.map((r, i) => (
                        <tr key={i} className={`hover:bg-[#F8FAFC] transition-colors ${r.daysLeft <= 15 ? "bg-red-50" : "bg-orange-50"}`}>
                          <td className="px-4 py-3 font-medium text-[#1E293B]">{r.clientName}</td>
                          <td className="px-4 py-3 text-[#475569]">{r.dscHolder}</td>
                          <td className="px-4 py-3 text-[#475569]">{r.expiryDate}</td>
                          <td className={`px-4 py-3 font-semibold ${r.daysLeft <= 15 ? "text-red-700" : "text-orange-700"}`}>{r.daysLeft}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Loan Overdue */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Landmark size={16} className="text-red-500" />
                Loan Overdue Risk
                {loanOverdueRisks.length > 0 && <span className="ml-auto text-xs font-medium bg-red-100 text-red-700 px-2 py-0.5 rounded-full">{loanOverdueRisks.length} overdue</span>}
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {loanOverdueRisks.length === 0 ? (
                <p className="px-6 py-4 text-sm text-[#64748B]">No overdue loans detected.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b border-[#F1F5F9] bg-[#F8FAFC] text-left"><th className="px-4 py-3 font-medium text-[#64748B]">Client</th><th className="px-4 py-3 font-medium text-[#64748B]">Lender</th><th className="px-4 py-3 font-medium text-[#64748B]">Loan Type</th><th className="px-4 py-3 font-medium text-[#64748B]">Outstanding</th></tr></thead>
                    <tbody className="divide-y divide-[#F8FAFC]">
                      {loanOverdueRisks.map((r, i) => (
                        <tr key={i} className="hover:bg-[#F8FAFC] bg-red-50 transition-colors">
                          <td className="px-4 py-3 font-medium text-[#1E293B]">{r.clientName}</td>
                          <td className="px-4 py-3 text-[#475569]">{r.lenderName}</td>
                          <td className="px-4 py-3 text-[#475569] capitalize">{r.loanType.replace(/_/g, " ")}</td>
                          <td className="px-4 py-3 font-semibold text-red-700">₹{(r.outstandingPaise / 100).toLocaleString("en-IN")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          {/* FD Maturity */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Info size={16} className="text-blue-500" />
                FD Maturing in 30 Days
                {fdMaturityRisks.length > 0 && <span className="ml-auto text-xs font-medium bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">{fdMaturityRisks.length} maturing</span>}
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {fdMaturityRisks.length === 0 ? (
                <p className="px-6 py-4 text-sm text-[#64748B]">No FDs maturing in the next 30 days.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b border-[#F1F5F9] bg-[#F8FAFC] text-left"><th className="px-4 py-3 font-medium text-[#64748B]">Client</th><th className="px-4 py-3 font-medium text-[#64748B]">Bank</th><th className="px-4 py-3 font-medium text-[#64748B]">Maturity Date</th><th className="px-4 py-3 font-medium text-[#64748B]">Days Left</th><th className="px-4 py-3 font-medium text-[#64748B]">Amount</th></tr></thead>
                    <tbody className="divide-y divide-[#F8FAFC]">
                      {fdMaturityRisks.map((r, i) => (
                        <tr key={i} className="hover:bg-[#F8FAFC] bg-blue-50 transition-colors">
                          <td className="px-4 py-3 font-medium text-[#1E293B]">{r.clientName}</td>
                          <td className="px-4 py-3 text-[#475569]">{r.bankName}</td>
                          <td className="px-4 py-3 text-[#475569]">{r.maturityDate}</td>
                          <td className="px-4 py-3 font-semibold text-blue-700">{r.daysLeft}</td>
                          <td className="px-4 py-3 text-[#334155]">₹{(r.maturityAmountPaise / 100).toLocaleString("en-IN")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Missing PAN */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <UserX size={16} className="text-orange-500" />
                Missing PAN
                {missingPanRisks.length > 0 && <span className="ml-auto text-xs font-medium bg-orange-100 text-orange-700 px-2 py-0.5 rounded-full">{missingPanRisks.length} missing</span>}
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {missingPanRisks.length === 0 ? (
                <p className="px-6 py-4 text-sm text-[#64748B]">All clients have PAN on record.</p>
              ) : (
                <div className="flex flex-wrap gap-2 px-4 py-3">
                  {missingPanRisks.map((c) => (
                    <span key={c.clientId} className="inline-flex items-center rounded-full border border-orange-200 bg-orange-50 px-3 py-1 text-xs font-medium text-orange-700">{c.clientName}</span>
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
              <CardContent>
                {/* Consolidated register — shared DataTable (search, category/severity filters,
                    sort by days-overdue / amount / date, pagination, CSV export, prefs). */}
                <DataTable
                  data={riskRegister}
                  columns={registerColumns}
                  filters={registerFilters}
                  getRowId={(r) => `${r.clientName}|${r.riskType}|${r.date ?? ""}|${r.description}`}
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
          )}

          {totalRisks === 0 && (
            <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-[#E2E8F0] bg-[#F8FAFC] py-20 text-center">
              <CheckCircle className="h-12 w-12 text-green-400 mb-3" />
              <p className="text-sm font-medium text-[#334155]">No risks detected</p>
              <p className="text-xs text-[#94A3B8] mt-1">All clients have valid GSTINs, no overdue filings, and recent activity.</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
