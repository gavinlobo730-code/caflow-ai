"use client";

import { Suspense } from "react";
import { useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import {
  Calendar, AlertTriangle, Clock, CheckCircle, FileText,
  ExternalLink, FlaskConical, Users, ArrowRight,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";
import { formatDate } from "@/lib/services/formatting";
import { getComplianceCalendar, updateFilingStatus } from "@/lib/data/compliance";
import type { ComplianceEntry } from "@/lib/data/compliance";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";
import DemoFilingModal from "@/components/DemoFilingModal";
import { getDemoFilingsByEntry, saveDemoFiling, type DemoFiling } from "@/lib/data/demoFilings";
import { isSimulatable, DEMO_STATUS_LABEL } from "@/lib/filing/demoFiling";

// ─── Type filter mapping ───────────────────────────────────────────────────
// URL param → compliance_type predicate. TDS and MCA use prefix matching because
// the DB stores subtypes (TDS24Q, TDS26Q, MCA_AOC4, MCA_MGT7).
function matchesUrlType(complianceType: string, urlType: string): boolean {
  if (urlType === "TDS") return complianceType.startsWith("TDS") || complianceType === "TCS_RETURN";
  if (urlType === "MCA") return complianceType.startsWith("MCA");
  return complianceType === urlType;
}

const TYPE_LABELS: Record<string, string> = {
  GSTR1:  "GSTR-1",
  GSTR3B: "GSTR-3B",
  ITR:    "Income Tax",
  TDS:    "TDS",
  MCA:    "MCA",
};

interface EmptyStateCopy { title: string; desc: string }
const TYPE_EMPTY_STATES: Record<string, EmptyStateCopy> = {
  GSTR1:  { title: "No GSTR-1 deadlines found",      desc: "Create a client and add a GSTR-1 compliance obligation to begin tracking filings." },
  GSTR3B: { title: "No GSTR-3B deadlines found",     desc: "Create a client and add a GSTR-3B compliance obligation." },
  ITR:    { title: "No Income Tax deadlines found",   desc: "Create a client and add an Income Tax compliance obligation." },
  TDS:    { title: "No TDS deadlines found",          desc: "Create a client and add a TDS compliance obligation." },
  MCA:    { title: "No MCA deadlines found",          desc: "Create a client and add an MCA compliance obligation." },
};

// ─── Styling ───────────────────────────────────────────────────────────────
const FILING_STATUS_COLORS: Record<string, string> = {
  pending:     "bg-amber-100 text-amber-700",
  in_progress: "bg-blue-100 text-blue-700",
  filed:       "bg-green-100 text-green-700",
  overdue:     "bg-red-100 text-red-700",
  na:          "bg-[#F1F5F9] text-[#64748B]",
};

const ALL_TYPES = ["GSTR1", "GSTR3B", "GSTR9", "ITR", "TDS24Q", "TDS26Q", "ADVANCE_TAX", "MCA_AOC4", "MCA_MGT7"];
const ALL_STATUSES = ["pending", "in_progress", "filed", "overdue", "na"];

function LoadingSpinner() {
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-4 animate-pulse">
      <div className="h-6 bg-white/[0.08] rounded w-48" />
      <div className="grid grid-cols-5 gap-3">
        {[1, 2, 3, 4, 5].map((i) => <div key={i} className="h-20 bg-[#F1F5F9] rounded-lg" />)}
      </div>
      <div className="h-64 bg-[#F1F5F9] rounded-xl" />
    </div>
  );
}

interface MarkFiledForm { id: string; arn: string }

// ─── Inner component — reads search params ─────────────────────────────────
function DeadlinesContent() {
  const searchParams = useSearchParams();
  const urlType = searchParams.get("type"); // e.g. "GSTR1", "TDS", null

  const [records, setRecords] = useState<ComplianceEntry[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [clientFilter, setClientFilter] = useState("");
  const [markFiled, setMarkFiled] = useState<MarkFiledForm | null>(null);
  const [filingLoading, setFilingLoading] = useState(false);
  const [demoFilings, setDemoFilings] = useState<Record<string, DemoFiling>>({});
  const [demoEntry, setDemoEntry] = useState<ComplianceEntry | null>(null);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [recs, cls, demos] = await Promise.all([
        getComplianceCalendar(undefined),
        getClients().catch(() => [] as Client[]),
        getDemoFilingsByEntry(undefined).catch(() => ({} as Record<string, DemoFiling>)),
      ]);
      setRecords(recs);
      setClients(cls);
      setDemoFilings(demos);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load deadline data");
    } finally {
      setLoading(false);
    }
  }

  // Clear in-page sub-filters when the URL type changes so prior selections don't bleed over
  useEffect(() => {
    setStatusFilter("");
    setTypeFilter("");
    setClientFilter("");
  }, [urlType]);

  useEffect(() => { loadData(); }, []);

  async function handleSimulated(demoReference: string) {
    if (!demoEntry) return;
    await saveDemoFiling(demoEntry, demoReference);
    setDemoFilings(prev => ({
      ...prev,
      [demoEntry.id]: {
        id: "local", firm_id: "", client_id: demoEntry.client_id,
        compliance_entry_id: demoEntry.id, compliance_type: demoEntry.compliance_type,
        period_start: demoEntry.period_start, period_end: demoEntry.period_end,
        demo_reference: demoReference, demo_status: "demo_filed",
        simulated_at: new Date().toISOString(),
      },
    }));
  }

  async function handleMarkFiled() {
    if (!markFiled) return;
    setFilingLoading(true);
    try {
      await updateFilingStatus(markFiled.id, "filed", markFiled.arn || undefined);
      setRecords(prev => prev.map(r =>
        r.id === markFiled.id ? { ...r, filing_status: "filed", arn_number: markFiled.arn } : r
      ));
      setMarkFiled(null);
    } finally {
      setFilingLoading(false);
    }
  }

  if (loading) return <LoadingSpinner />;
  if (error) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error}</div>
      </div>
    );
  }

  const today = new Date().toISOString().split("T")[0];
  const in7Days = new Date(Date.now() + 7 * 86400000).toISOString().split("T")[0];

  // Apply URL type filter first (drives the stats cards too)
  const typeRecords = urlType
    ? records.filter(r => matchesUrlType(r.compliance_type, urlType))
    : records;

  const overdue     = typeRecords.filter(r => r.due_date < today && r.filing_status !== "filed" && r.filing_status !== "na").length;
  const dueThisWeek = typeRecords.filter(r => r.due_date >= today && r.due_date <= in7Days && r.filing_status !== "filed").length;
  const inProgress  = typeRecords.filter(r => r.filing_status === "in_progress").length;
  const filed       = typeRecords.filter(r => r.filing_status === "filed").length;
  const pending     = typeRecords.filter(r => r.filing_status === "pending").length;
  const demoCount   = Object.values(demoFilings).filter(d =>
    urlType ? matchesUrlType(d.compliance_type, urlType) : true
  ).length;

  const STATS = [
    { label: "Due This Week", value: dueThisWeek, icon: Clock,          color: "text-amber-600", bg: "bg-amber-50"  },
    { label: "Overdue",       value: overdue,      icon: AlertTriangle,  color: "text-red-600",   bg: "bg-red-50"    },
    { label: "In Progress",   value: inProgress,   icon: FileText,       color: "text-blue-600",  bg: "bg-blue-50"   },
    { label: "Pending",       value: pending,       icon: Calendar,       color: "text-purple-600",bg: "bg-purple-50" },
    { label: "Filed",         value: filed,         icon: CheckCircle,   color: "text-green-600", bg: "bg-green-50"  },
    { label: "Demo Filed",    value: demoCount,    icon: FlaskConical,   color: "text-amber-600", bg: "bg-amber-50"  },
  ];

  const clientMap = Object.fromEntries(clients.map(c => [c.id, c.client_name]));

  // Secondary in-page filters (status, explicit type dropdown, client name search)
  const filtered = typeRecords.filter(r => {
    if (statusFilter && r.filing_status !== statusFilter) return false;
    if (typeFilter && r.compliance_type !== typeFilter) return false;
    if (clientFilter) {
      const name = (clientMap[r.client_id] ?? "").toLowerCase();
      if (!name.includes(clientFilter.toLowerCase())) return false;
    }
    return true;
  });

  const pageTitle = urlType && TYPE_LABELS[urlType]
    ? `Deadlines — ${TYPE_LABELS[urlType]}`
    : "All Deadlines";

  // Empty state copy — type-specific when URL has a type param
  const emptyStateCopy: EmptyStateCopy | null =
    urlType && TYPE_EMPTY_STATES[urlType] ? TYPE_EMPTY_STATES[urlType] : null;

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-[#0F172A]">{pageTitle}</h1>
        <p className="text-sm text-[#64748B] mt-0.5">
          Cross-client compliance calendar — triage here, file inside each client
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
        {STATS.map((s) => (
          <Card key={s.label}>
            <CardContent className="pt-4 pb-3">
              <div className={`w-8 h-8 rounded-lg ${s.bg} flex items-center justify-center mb-2`}>
                <s.icon size={16} className={s.color} />
              </div>
              <p className="text-2xl font-bold text-[#0F172A]">{s.value}</p>
              <p className="text-xs text-[#64748B] mt-0.5 leading-tight">{s.label}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
        <Calendar size={16} className="text-amber-600 mt-0.5 shrink-0" />
        <p className="text-sm text-amber-800">
          <strong>Triage view.</strong> To file a return, click the client name or &ldquo;Open Client&rdquo; to go
          directly to that client&apos;s Compliance tab.
        </p>
      </div>

      {markFiled && (
        <Card className="border-blue-200 bg-blue-50">
          <CardContent className="pt-4 pb-4">
            <p className="text-sm font-medium text-blue-900 mb-3">Mark as Filed</p>
            <div className="flex gap-3 items-center">
              <input
                value={markFiled.arn}
                onChange={e => setMarkFiled({ ...markFiled, arn: e.target.value })}
                placeholder="ARN Number (optional)"
                className="flex-1 px-3 py-1.5 text-sm border border-blue-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
              />
              <button
                onClick={handleMarkFiled}
                disabled={filingLoading}
                className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
              >
                {filingLoading ? "Saving…" : "Confirm Filed"}
              </button>
              <button
                onClick={() => setMarkFiled(null)}
                className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-md hover:bg-[#F1F5F9] bg-white"
              >
                Cancel
              </button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Secondary in-page filters — type dropdown hidden when URL already sets type */}
      <div className="flex flex-wrap gap-3">
        <div>
          <label className="text-xs text-[#64748B]">Status</label>
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
            className="block mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All statuses</option>
            {ALL_STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        {!urlType && (
          <div>
            <label className="text-xs text-[#64748B]">Type</label>
            <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)}
              className="block mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="">All types</option>
              {ALL_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
        )}
        <div>
          <label className="text-xs text-[#64748B]">Client</label>
          <input value={clientFilter} onChange={e => setClientFilter(e.target.value)}
            placeholder="Search client…"
            className="block mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 w-48" />
        </div>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">{filtered.length} record{filtered.length !== 1 ? "s" : ""}</CardTitle>
        </CardHeader>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#F1F5F9] text-xs text-[#94A3B8]">
                <th className="px-5 py-3 text-left font-semibold">Client</th>
                <th className="px-3 py-3 text-left font-semibold">Type</th>
                <th className="px-3 py-3 text-left font-semibold">Period</th>
                <th className="px-3 py-3 text-left font-semibold">Due Date</th>
                <th className="px-3 py-3 text-left font-semibold">Status</th>
                <th className="px-3 py-3 text-left font-semibold">ARN</th>
                <th className="px-5 py-3 text-left font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {filtered.map((r) => (
                <tr key={r.id} className="hover:bg-[#F8FAFC]">
                  <td className="px-5 py-3 text-sm font-medium">
                    <Link href={`/clients/${r.client_id}`} className="text-blue-600 hover:underline">
                      {clientMap[r.client_id] ?? r.client_id.slice(0, 8)}
                    </Link>
                  </td>
                  <td className="px-3 py-3 text-xs text-[#475569]">{r.compliance_type}</td>
                  <td className="px-3 py-3 text-xs text-[#64748B] whitespace-nowrap">
                    {formatDate(r.period_start)} – {formatDate(r.period_end)}
                  </td>
                  <td className={`px-3 py-3 text-xs whitespace-nowrap ${r.due_date < today && r.filing_status !== "filed" ? "text-red-600 font-medium" : "text-[#475569]"}`}>
                    {formatDate(r.due_date)}
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex flex-col gap-1 items-start">
                      <Badge className={`text-xs ${FILING_STATUS_COLORS[r.filing_status] ?? "bg-[#F1F5F9] text-[#475569]"}`}>
                        {r.filing_status}
                      </Badge>
                      {demoFilings[r.id] && (
                        <Badge className="text-[10px] bg-amber-100 text-amber-700 flex items-center gap-1">
                          <FlaskConical size={10} /> {DEMO_STATUS_LABEL}
                        </Badge>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-3 text-xs text-[#64748B] font-mono">
                    {demoFilings[r.id]
                      ? <span className="text-amber-700" title="Demo reference — not filed with any portal">{demoFilings[r.id].demo_reference}</span>
                      : (r.arn_number ?? "—")}
                  </td>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-3 flex-wrap">
                      {r.filing_status !== "filed" && r.filing_status !== "na" && (
                        <button
                          onClick={() => setMarkFiled({ id: r.id, arn: r.arn_number ?? "" })}
                          className="text-xs text-blue-600 hover:underline flex items-center gap-1"
                        >
                          <CheckCircle size={12} /> Mark Filed
                        </button>
                      )}
                      {r.filing_status === "filed" && (
                        <span className="text-xs text-green-600 flex items-center gap-1">
                          <CheckCircle size={12} /> {r.filed_date ? formatDate(r.filed_date) : "Filed"}
                        </span>
                      )}
                      {isSimulatable(r.compliance_type) && (
                        <button
                          onClick={() => setDemoEntry(r)}
                          className="text-xs text-amber-700 hover:underline flex items-center gap-1"
                          title="Run a demo of the filing workflow — submits nothing"
                        >
                          <FlaskConical size={12} /> Simulate Filing
                        </button>
                      )}
                      <Link
                        href={`/clients/${r.client_id}`}
                        className="text-xs text-blue-600 hover:underline flex items-center gap-1"
                      >
                        <ExternalLink size={11} /> Open Client
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {filtered.length === 0 && (
            <div className="py-14 px-8 text-center">
              {/* Type-specific empty state when panel link is active */}
              {emptyStateCopy && typeRecords.length === 0 ? (
                <div className="max-w-xs mx-auto space-y-3">
                  <div className="w-12 h-12 rounded-xl bg-[#F1F5F9] flex items-center justify-center mx-auto">
                    <Calendar size={20} className="text-[#94A3B8]" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-[#0F172A]">{emptyStateCopy.title}</p>
                    <p className="text-xs text-[#64748B] mt-1 leading-relaxed">{emptyStateCopy.desc}</p>
                  </div>
                  <Link
                    href="/clients"
                    className="inline-flex items-center gap-1.5 px-4 py-2 border border-[#E2E8F0] text-[#475569] text-xs font-semibold rounded-lg hover:bg-[#F8FAFC] transition-colors"
                  >
                    View Clients <ArrowRight size={13} />
                  </Link>
                </div>
              ) : records.length === 0 && clients.length === 0 ? (
                /* No clients at all */
                <div className="max-w-xs mx-auto space-y-3">
                  <div className="w-12 h-12 rounded-xl bg-[#F1F5F9] flex items-center justify-center mx-auto">
                    <Users size={20} className="text-[#94A3B8]" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-[#0F172A]">No clients yet</p>
                    <p className="text-xs text-[#64748B] mt-1 leading-relaxed">
                      Deadlines are tracked per-client. Add your first client to start managing compliance schedules.
                    </p>
                  </div>
                  <Link
                    href="/clients"
                    className="inline-flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white text-xs font-semibold rounded-lg hover:bg-blue-700 transition-colors"
                  >
                    Add First Client <ArrowRight size={13} />
                  </Link>
                </div>
              ) : records.length === 0 ? (
                /* Clients exist but no compliance records seeded yet */
                <div className="max-w-xs mx-auto space-y-3">
                  <div className="w-12 h-12 rounded-xl bg-[#F1F5F9] flex items-center justify-center mx-auto">
                    <Calendar size={20} className="text-[#94A3B8]" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-[#0F172A]">No compliance records yet</p>
                    <p className="text-xs text-[#64748B] mt-1 leading-relaxed">
                      Open a client and go to the Compliance tab to seed their filing schedule for this year.
                    </p>
                  </div>
                  <Link
                    href="/clients"
                    className="inline-flex items-center gap-1.5 px-4 py-2 border border-[#E2E8F0] text-[#475569] text-xs font-semibold rounded-lg hover:bg-[#F8FAFC] transition-colors"
                  >
                    View Clients <ArrowRight size={13} />
                  </Link>
                </div>
              ) : (
                /* Records exist but secondary filters hide them */
                <div className="space-y-2">
                  <p className="text-sm text-[#94A3B8]">No records match your filters.</p>
                  <button
                    onClick={() => { setStatusFilter(""); setTypeFilter(""); setClientFilter(""); }}
                    className="text-xs text-blue-600 hover:underline"
                  >
                    Clear filters
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </Card>

      {demoEntry && (
        <DemoFilingModal
          entry={demoEntry}
          clientName={clientMap[demoEntry.client_id] ?? demoEntry.client_id.slice(0, 8)}
          onConfirmed={handleSimulated}
          onClose={() => setDemoEntry(null)}
        />
      )}
    </div>
  );
}

// ─── Page export — Suspense required for useSearchParams in App Router ────────
export default function DeadlinesPage() {
  return (
    <Suspense fallback={<LoadingSpinner />}>
      <DeadlinesContent />
    </Suspense>
  );
}
