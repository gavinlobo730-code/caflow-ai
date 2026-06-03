"use client";

import { useState, useEffect } from "react";
import {
  Building2, Mail, Phone, MapPin, Calendar, FileText, Clock,
  ChevronRight, CheckCircle, AlertTriangle, Globe, Copy, X,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getClient } from "@/lib/data/clients";
import { getTasks } from "@/lib/data/tasks";
import { getComplianceCalendar, updateFilingStatus, seedComplianceCalendar } from "@/lib/data/compliance";
import { getTransactions } from "@/lib/data/transactions";
import { getBankStatements } from "@/lib/data/bankStatements";
import type { Client } from "@/lib/types";
import type { Task } from "@/lib/types";
import type { ComplianceEntry } from "@/lib/data/compliance";
import type { Transaction } from "@/lib/data/transactions";
import type { BankStatement } from "@/lib/data/bankStatements";
import { formatDate, ENTITY_TYPE_LABELS } from "@/lib/services/formatting";
import { formatPaise } from "@/lib/services/formatting";

interface PortalState {
  enabled: boolean;
  invitedAt: string | null;
}

type TabId = "overview" | "tasks" | "compliance" | "invoices" | "bank";

const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "tasks", label: "Tasks" },
  { id: "compliance", label: "Compliance" },
  { id: "invoices", label: "Invoices" },
  { id: "bank", label: "Bank Statements" },
];

const TASK_STATUS_COLORS: Record<string, string> = {
  todo: "bg-gray-100 text-gray-600",
  in_progress: "bg-blue-100 text-blue-700",
  waiting_client: "bg-purple-100 text-purple-700",
  review_required: "bg-amber-100 text-amber-700",
  completed: "bg-green-100 text-green-700",
};

const FILING_STATUS_COLORS: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  in_progress: "bg-blue-100 text-blue-700",
  filed: "bg-green-100 text-green-700",
  overdue: "bg-red-100 text-red-700",
  na: "bg-gray-100 text-gray-500",
};

function LoadingSkeleton() {
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6 animate-pulse">
      <div className="h-8 bg-gray-200 rounded w-64" />
      <div className="grid grid-cols-5 gap-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-20 bg-gray-100 rounded-lg" />
        ))}
      </div>
      <div className="h-64 bg-gray-100 rounded-xl" />
    </div>
  );
}

interface MarkFiledForm {
  id: string;
  arn: string;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default function ClientWorkspacePage() {
  const [id, setId] = useState<string>("");
  useEffect(() => {
    const match = window.location.pathname.match(/\/clients\/([^/]+)/);
    if (!match?.[1]) return;
    const seg = match[1];
    // Only set ID if it's actually a UUID — ignore pipeline, portal, documents etc.
    if (UUID_RE.test(seg)) setId(seg);
  }, []);

  const [client, setClient] = useState<Client | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [compliance, setCompliance] = useState<ComplianceEntry[]>([]);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [bankStatements, setBankStatements] = useState<BankStatement[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  const [markFiled, setMarkFiled] = useState<MarkFiledForm | null>(null);
  const [filingLoading, setFilingLoading] = useState(false);
  const [portal, setPortal] = useState<PortalState | null>(null);
  const [showPortalModal, setShowPortalModal] = useState(false);
  const [portalLoading, setPortalLoading] = useState(false);

  useEffect(() => {
    if (!id || id === "_placeholder") return;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [c, t, comp, txns, bs] = await Promise.all([
          getClient(id as string),
          getTasks(id as string).catch(() => [] as Task[]),
          getComplianceCalendar(id as string).catch(() => [] as ComplianceEntry[]),
          getTransactions(id as string).catch(() => [] as Transaction[]),
          getBankStatements(id as string).catch(() => [] as BankStatement[]),
        ]);
        setClient(c);

        // Load portal status
        const { getSupabaseClient } = await import("@/lib/supabase/client");
        const supabase = getSupabaseClient();
        const { data: portalRow } = await supabase
          .from("clients")
          .select("portal_enabled, portal_invited_at")
          .eq("id", id as string)
          .maybeSingle();
        if (portalRow) {
          setPortal({ enabled: !!portalRow.portal_enabled, invitedAt: portalRow.portal_invited_at ?? null });
        }
        setTasks(t);
        // Seed compliance calendar if empty
        if (comp.length === 0) {
          await seedComplianceCalendar(id as string).catch(() => undefined);
          const seeded = await getComplianceCalendar(id as string).catch(() => [] as ComplianceEntry[]);
          setCompliance(seeded);
        } else {
          setCompliance(comp);
        }
        setTransactions(txns);
        setBankStatements(bs);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load client");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [id]);

  async function handleInviteToPortal() {
    if (!id) return;
    setPortalLoading(true);
    try {
      const { getSupabaseClient } = await import("@/lib/supabase/client");
      const supabase = getSupabaseClient();
      await supabase
        .from("clients")
        .update({ portal_enabled: true, portal_invited_at: new Date().toISOString() })
        .eq("id", id);
      setPortal({ enabled: true, invitedAt: new Date().toISOString() });
      setShowPortalModal(true);
    } finally {
      setPortalLoading(false);
    }
  }

  async function handleMarkFiled() {
    if (!markFiled) return;
    setFilingLoading(true);
    try {
      await updateFilingStatus(markFiled.id, "filed", markFiled.arn || undefined);
      setCompliance(prev => prev.map(c =>
        c.id === markFiled.id ? { ...c, filing_status: "filed", arn_number: markFiled.arn } : c
      ));
      setMarkFiled(null);
    } finally {
      setFilingLoading(false);
    }
  }

  if (!id) return null;
  if (loading) return <LoadingSkeleton />;
  if (error || !client) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error ?? "Client not found"}</div>
      </div>
    );
  }

  const today = new Date().toISOString().split("T")[0];
  const monthStart = today.slice(0, 7) + "-01";

  const openTasks = tasks.filter(t => t.status !== "completed").length;
  const pendingFilings = compliance.filter(c => c.filing_status === "pending" || c.filing_status === "overdue").length;
  const invoicesThisMonth = transactions.filter(t => t.transaction_date >= monthStart).length;

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm text-gray-500 mb-1">
            <span>Clients</span>
            <ChevronRight size={14} />
            <span className="text-gray-900 font-medium">{client.client_name}</span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">{client.client_name}</h1>
          <div className="flex items-center gap-2 mt-1">
            <Badge variant="secondary" className="text-xs">
              {ENTITY_TYPE_LABELS[client.entity_type] ?? client.entity_type}
            </Badge>
            <Badge variant="secondary" className={`text-xs ${client.status === "active" ? "bg-green-100 text-green-700" : ""}`}>
              {client.status}
            </Badge>
          </div>
        </div>
      </div>

      {/* Quick stats row */}
      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-lg bg-blue-50 text-blue-800 px-4 py-3">
          <p className="text-2xl font-bold">{openTasks}</p>
          <p className="text-xs mt-0.5 opacity-80">Open Tasks</p>
        </div>
        <div className={`rounded-lg px-4 py-3 ${pendingFilings > 0 ? "bg-amber-50 text-amber-800" : "bg-gray-100 text-gray-600"}`}>
          <p className="text-2xl font-bold">{pendingFilings}</p>
          <p className="text-xs mt-0.5 opacity-80">Pending Filings</p>
        </div>
        <div className="rounded-lg bg-purple-50 text-purple-800 px-4 py-3">
          <p className="text-2xl font-bold">{invoicesThisMonth}</p>
          <p className="text-xs mt-0.5 opacity-80">Invoices This Month</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-100">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.id
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Overview tab */}
      {activeTab === "overview" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                <Building2 size={15} /> Client Information
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div>
                <p className="text-xs text-gray-500">PAN</p>
                <p className="font-mono font-medium">{client.pan}</p>
              </div>
              {client.gstin && (
                <div>
                  <p className="text-xs text-gray-500">GSTIN</p>
                  <p className="font-mono font-medium">{client.gstin}</p>
                </div>
              )}
              {client.mobile && (
                <div className="flex items-center gap-2 text-gray-700">
                  <Phone size={13} /><span>{client.mobile}</span>
                </div>
              )}
              {client.email && (
                <div className="flex items-center gap-2 text-gray-700">
                  <Mail size={13} /><span className="truncate">{client.email}</span>
                </div>
              )}
              {client.city && (
                <div className="flex items-center gap-2 text-gray-700">
                  <MapPin size={13} />
                  <span>{client.city}{client.state ? `, ${client.state}` : ""}{client.pincode ? ` — ${client.pincode}` : ""}</span>
                </div>
              )}
              <div className="flex items-center gap-2 text-gray-700">
                <Calendar size={13} />
                <span>GST filing: {client.gst_filing_frequency}</span>
              </div>
              {client.notes && (
                <div>
                  <p className="text-xs text-gray-500">Notes</p>
                  <p className="text-xs text-gray-700">{client.notes}</p>
                </div>
              )}
            </CardContent>
          </Card>

          <div className="lg:col-span-2 space-y-4">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm flex items-center gap-2"><Clock size={15} /> Recent Tasks</CardTitle>
              </CardHeader>
              <CardContent>
                {tasks.length === 0 ? (
                  <p className="text-sm text-gray-400 text-center py-4">No tasks</p>
                ) : (
                  <div className="space-y-2">
                    {tasks.slice(0, 5).map(t => (
                      <div key={t.id} className="flex items-center gap-3 py-2 border-b border-gray-50 last:border-0">
                        <div className="flex-1">
                          <p className="text-sm font-medium text-gray-900">{t.title}</p>
                          {t.due_date && <p className="text-xs text-gray-500">Due: {formatDate(t.due_date)}</p>}
                        </div>
                        <Badge className={`text-xs ${TASK_STATUS_COLORS[t.status] ?? "bg-gray-100 text-gray-600"}`}>
                          {t.status.replace(/_/g, " ")}
                        </Badge>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm flex items-center gap-2"><AlertTriangle size={15} /> Upcoming Filings</CardTitle>
              </CardHeader>
              <CardContent>
                {compliance.filter(c => c.filing_status !== "filed" && c.due_date >= today).slice(0, 5).length === 0 ? (
                  <p className="text-sm text-gray-400 text-center py-4">No upcoming filings</p>
                ) : (
                  <div className="space-y-2">
                    {compliance.filter(c => c.filing_status !== "filed" && c.due_date >= today).slice(0, 5).map(c => (
                      <div key={c.id} className="flex items-center gap-3 py-2 border-b border-gray-50 last:border-0">
                        <div className="flex-1">
                          <p className="text-sm font-medium text-gray-900">{c.compliance_type}</p>
                          <p className="text-xs text-gray-500">Due: {formatDate(c.due_date)}</p>
                        </div>
                        <Badge className={`text-xs ${FILING_STATUS_COLORS[c.filing_status] ?? "bg-gray-100 text-gray-600"}`}>
                          {c.filing_status}
                        </Badge>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {/* Tasks tab */}
      {activeTab === "tasks" && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <Clock size={15} /> Tasks ({tasks.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            {tasks.length === 0 ? (
              <p className="text-sm text-gray-400 text-center py-8">No tasks for this client</p>
            ) : (
              <div className="divide-y divide-gray-50">
                {tasks.map(t => (
                  <div key={t.id} className="flex items-center gap-4 py-3">
                    <div className="flex-1">
                      <p className="text-sm font-medium text-gray-900">{t.title}</p>
                      {t.description && <p className="text-xs text-gray-500 mt-0.5">{t.description}</p>}
                    </div>
                    {t.due_date && (
                      <p className={`text-xs shrink-0 ${t.due_date < today && t.status !== "completed" ? "text-red-600 font-medium" : "text-gray-500"}`}>
                        {formatDate(t.due_date)}
                      </p>
                    )}
                    <Badge className={`text-xs shrink-0 ${TASK_STATUS_COLORS[t.status] ?? "bg-gray-100 text-gray-600"}`}>
                      {t.status.replace(/_/g, " ")}
                    </Badge>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Compliance tab */}
      {activeTab === "compliance" && (
        <div className="space-y-4">
          {/* Mark as Filed inline form */}
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
                    className="text-xs px-3 py-1.5 border border-gray-200 rounded-md hover:bg-gray-100"
                  >
                    Cancel
                  </button>
                </div>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Compliance Calendar ({compliance.length} deadlines)</CardTitle>
            </CardHeader>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100 text-xs text-gray-400">
                    <th className="px-5 py-3 text-left font-semibold">Type</th>
                    <th className="px-3 py-3 text-left font-semibold">Period</th>
                    <th className="px-3 py-3 text-left font-semibold">Due Date</th>
                    <th className="px-3 py-3 text-left font-semibold">Status</th>
                    <th className="px-3 py-3 text-left font-semibold">ARN</th>
                    <th className="px-5 py-3 text-left font-semibold">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {compliance.map(c => (
                    <tr key={c.id} className="hover:bg-gray-50">
                      <td className="px-5 py-3 text-sm font-medium text-gray-900">{c.compliance_type}</td>
                      <td className="px-3 py-3 text-xs text-gray-500">
                        {formatDate(c.period_start)} – {formatDate(c.period_end)}
                      </td>
                      <td className={`px-3 py-3 text-xs whitespace-nowrap ${c.due_date < today && c.filing_status !== "filed" ? "text-red-600 font-medium" : "text-gray-600"}`}>
                        {formatDate(c.due_date)}
                      </td>
                      <td className="px-3 py-3">
                        <Badge className={`text-xs ${FILING_STATUS_COLORS[c.filing_status] ?? "bg-gray-100 text-gray-600"}`}>
                          {c.filing_status}
                        </Badge>
                      </td>
                      <td className="px-3 py-3 text-xs text-gray-500 font-mono">{c.arn_number ?? "—"}</td>
                      <td className="px-5 py-3">
                        {c.filing_status !== "filed" && (
                          <button
                            onClick={() => setMarkFiled({ id: c.id, arn: c.arn_number ?? "" })}
                            className="text-xs text-blue-600 hover:underline flex items-center gap-1"
                          >
                            <CheckCircle size={12} /> Mark Filed
                          </button>
                        )}
                        {c.filing_status === "filed" && (
                          <span className="text-xs text-green-600 flex items-center gap-1">
                            <CheckCircle size={12} /> Filed {c.filed_date ? `on ${formatDate(c.filed_date)}` : ""}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {compliance.length === 0 && (
                <div className="text-center py-8 text-sm text-gray-400">No compliance deadlines found</div>
              )}
            </div>
          </Card>
        </div>
      )}

      {/* Invoices tab */}
      {activeTab === "invoices" && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <FileText size={15} /> Transactions ({transactions.length})
            </CardTitle>
          </CardHeader>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 text-xs text-gray-400">
                  <th className="px-5 py-3 text-left font-semibold">Date</th>
                  <th className="px-3 py-3 text-left font-semibold">Type</th>
                  <th className="px-3 py-3 text-left font-semibold">Party</th>
                  <th className="px-3 py-3 text-left font-semibold">Ref</th>
                  <th className="px-3 py-3 text-right font-semibold">Amount</th>
                  <th className="px-5 py-3 text-left font-semibold">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {transactions.map(t => (
                  <tr key={t.id} className="hover:bg-gray-50">
                    <td className="px-5 py-3 text-xs text-gray-600 whitespace-nowrap">{formatDate(t.transaction_date)}</td>
                    <td className="px-3 py-3 text-xs text-gray-600">{t.transaction_type.replace(/_/g, " ")}</td>
                    <td className="px-3 py-3 text-sm font-medium text-gray-900">{t.party_name}</td>
                    <td className="px-3 py-3 text-xs text-gray-500 font-mono">{t.reference_no ?? "—"}</td>
                    <td className="px-3 py-3 text-sm text-right tabular-nums text-gray-700">{formatPaise(t.total_paise)}</td>
                    <td className="px-5 py-3">
                      <Badge className={`text-xs ${t.status === "posted" ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}`}>
                        {t.status}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {transactions.length === 0 && (
              <div className="text-center py-8 text-sm text-gray-400">No transactions found</div>
            )}
          </div>
        </Card>
      )}

      {/* Portal Access section — always visible below tabs */}
      <div className="bg-white rounded-xl border border-gray-100 p-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Globe className="w-4 h-4 text-blue-600" />
            <div>
              <h3 className="text-sm font-semibold text-gray-900">Portal Access</h3>
              <p className="text-xs text-gray-400 mt-0.5">
                {portal?.enabled
                  ? `Portal active${portal.invitedAt ? ` · Invited ${new Date(portal.invitedAt).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}` : ""}`
                  : "Not enabled — client cannot log in yet"}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${portal?.enabled ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"}`}>
              {portal?.enabled ? "Active" : "Not enabled"}
            </span>
            <button
              onClick={handleInviteToPortal}
              disabled={portalLoading}
              className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {portalLoading ? "Saving…" : portal?.enabled ? "Resend Invite" : "Invite to Portal"}
            </button>
          </div>
        </div>
      </div>

      {/* Portal invite modal */}
      {showPortalModal && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-gray-900">Share Portal Link</h3>
              <button onClick={() => setShowPortalModal(false)} className="text-gray-400 hover:text-gray-600">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 space-y-2">
              <p className="text-xs font-medium text-blue-900">Portal URL</p>
              <div className="flex items-center gap-2">
                <code className="text-xs text-blue-700 flex-1 break-all">
                  {typeof window !== "undefined" ? `${window.location.origin}/portal` : "/portal"}
                </code>
                <button
                  onClick={() => {
                    if (typeof window !== "undefined") {
                      navigator.clipboard.writeText(`${window.location.origin}/portal`);
                    }
                  }}
                  className="shrink-0 text-blue-600 hover:text-blue-800"
                  title="Copy URL"
                >
                  <Copy className="w-4 h-4" />
                </button>
              </div>
            </div>
            <p className="text-xs text-gray-500">
              Copy this link and share it with your client. They will need to sign up at this URL using the email address on their profile.
            </p>
            <button
              onClick={() => setShowPortalModal(false)}
              className="w-full bg-blue-600 text-white text-sm py-2 rounded-lg hover:bg-blue-700"
            >
              Done
            </button>
          </div>
        </div>
      )}

      {/* Bank Statements tab */}
      {activeTab === "bank" && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Bank Statements ({bankStatements.length})</CardTitle>
          </CardHeader>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 text-xs text-gray-400">
                  <th className="px-5 py-3 text-left font-semibold">Bank</th>
                  <th className="px-3 py-3 text-left font-semibold">Account</th>
                  <th className="px-3 py-3 text-left font-semibold">Period</th>
                  <th className="px-3 py-3 text-right font-semibold">Debits</th>
                  <th className="px-3 py-3 text-right font-semibold">Credits</th>
                  <th className="px-3 py-3 text-center font-semibold">Rows</th>
                  <th className="px-5 py-3 text-left font-semibold">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {bankStatements.map(bs => (
                  <tr key={bs.id} className="hover:bg-gray-50">
                    <td className="px-5 py-3 text-sm font-medium text-gray-900">{bs.bank_name}</td>
                    <td className="px-3 py-3 text-xs text-gray-500 font-mono">{bs.account_number ?? "—"}</td>
                    <td className="px-3 py-3 text-xs text-gray-500 whitespace-nowrap">
                      {formatDate(bs.statement_from)} – {formatDate(bs.statement_to)}
                    </td>
                    <td className="px-3 py-3 text-sm text-right tabular-nums text-red-600">{formatPaise(bs.total_debits_paise)}</td>
                    <td className="px-3 py-3 text-sm text-right tabular-nums text-green-600">{formatPaise(bs.total_credits_paise)}</td>
                    <td className="px-3 py-3 text-xs text-center text-gray-500">{bs.row_count}</td>
                    <td className="px-5 py-3">
                      <Badge className={`text-xs ${bs.import_status === "posted" ? "bg-green-100 text-green-700" : bs.import_status === "reviewed" ? "bg-blue-100 text-blue-700" : "bg-amber-100 text-amber-700"}`}>
                        {bs.import_status}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {bankStatements.length === 0 && (
              <div className="text-center py-8 text-sm text-gray-400">No bank statements imported</div>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
