"use client";

import { useState, useEffect } from "react";
import {
  ExternalLink, Copy, CheckCircle, FileText, MessageSquare, Receipt,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getClients } from "@/lib/data/clients";
import { getComplianceCalendar } from "@/lib/data/compliance";
import { getTransactions } from "@/lib/data/transactions";
import type { Client } from "@/lib/types";
import type { ComplianceEntry } from "@/lib/data/compliance";
import type { Transaction } from "@/lib/data/transactions";
import { formatDate } from "@/lib/services/formatting";
import { formatPaise } from "@/lib/services/formatting";

type PortalTab = "documents" | "filings" | "dues" | "messages";

const PORTAL_TABS: { id: PortalTab; label: string; icon: React.ElementType }[] = [
  { id: "documents", label: "Pending Documents", icon: FileText },
  { id: "filings", label: "Recent Filings", icon: Receipt },
  { id: "dues", label: "Outstanding Dues", icon: Receipt },
  { id: "messages", label: "Messages", icon: MessageSquare },
];

const MOCK_DOCUMENTS = [
  { id: "1", title: "Upload Q4 Bank Statement", desc: "For the period Jan–Mar 2026", urgent: true },
  { id: "2", title: "Provide TDS Certificate 16A", desc: "From all deductors for FY 2025–26", urgent: true },
  { id: "3", title: "Submit Investment Proofs", desc: "LIC, PPF, ELSS for 80C deductions", urgent: false },
];

const MOCK_DUES = [
  { id: "1", description: "Professional fees — FY 2025-26 Q4", amount: "₹18,000", due: "15 Jun 2026", status: "Unpaid" },
  { id: "2", description: "GSTR filing charges — Mar 2026", amount: "₹2,500", due: "30 May 2026", status: "Overdue" },
];

const MOCK_MESSAGES = [
  {
    id: "1",
    from: "CA",
    text: "Your GSTR-1 for March 2026 has been filed successfully. ✓",
    time: "2 days ago",
  },
  {
    id: "2",
    from: "CA",
    text: "Please upload your Q4 bank statement at the earliest so we can reconcile before the audit.",
    time: "5 days ago",
  },
  {
    id: "3",
    from: "CA",
    text: "Advance tax instalment of 15% was due on 15 Jun. Please confirm payment made.",
    time: "1 week ago",
  },
];

const FILING_STATUS_COLORS: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  in_progress: "bg-blue-100 text-blue-700",
  filed: "bg-green-100 text-green-700",
  overdue: "bg-red-100 text-red-700",
  na: "bg-gray-100 text-gray-500",
};

export default function ClientPortalPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<string>("");
  const [selectedClient, setSelectedClient] = useState<Client | null>(null);
  const [compliance, setCompliance] = useState<ComplianceEntry[]>([]);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(false);
  const [clientsLoading, setClientsLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<PortalTab>("documents");
  const [copied, setCopied] = useState(false);

  // Load clients list on mount
  useEffect(() => {
    getClients()
      .then(setClients)
      .catch(() => setClients([]))
      .finally(() => setClientsLoading(false));
  }, []);

  // Load client data when a client is selected
  useEffect(() => {
    if (!selectedClientId) {
      setSelectedClient(null);
      setCompliance([]);
      setTransactions([]);
      return;
    }
    const client = clients.find((c) => c.id === selectedClientId) ?? null;
    setSelectedClient(client);

    setLoading(true);
    Promise.all([
      getComplianceCalendar(selectedClientId).catch(() => [] as ComplianceEntry[]),
      getTransactions(selectedClientId).catch(() => [] as Transaction[]),
    ])
      .then(([comp, txns]) => {
        setCompliance(comp);
        setTransactions(txns);
      })
      .finally(() => setLoading(false));
  }, [selectedClientId, clients]);

  async function handleCopyPortalLink() {
    const url = `${window.location.origin}/client-portal/${selectedClientId}`;
    await navigator.clipboard.writeText(url).catch(() => undefined);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  }

  const recentFilings = compliance
    .filter((c) => c.filing_status === "filed")
    .slice(0, 8);

  const pendingFilings = compliance
    .filter((c) => c.filing_status !== "filed")
    .slice(0, 5);

  const unpaidInvoices = transactions.filter(
    (t) => t.status !== "posted"
  );

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Page Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Client Portal Preview</h1>
          <p className="text-sm text-gray-500 mt-1">
            This is how your clients see their workspace
          </p>
        </div>
        {selectedClient && (
          <button
            onClick={handleCopyPortalLink}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
          >
            {copied ? (
              <>
                <CheckCircle size={15} />
                Portal link copied!
              </>
            ) : (
              <>
                <Copy size={15} />
                Share Portal Link
              </>
            )}
          </button>
        )}
      </div>

      {/* Client selector */}
      <Card>
        <CardContent className="pt-5 pb-4">
          <div className="flex items-center gap-3">
            <ExternalLink size={16} className="text-gray-400 shrink-0" />
            <div className="flex-1">
              <label htmlFor="client-select" className="block text-xs font-medium text-gray-500 mb-1">
                Select a client to preview their portal
              </label>
              <select
                id="client-select"
                value={selectedClientId}
                onChange={(e) => setSelectedClientId(e.target.value)}
                className="w-full max-w-sm px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                disabled={clientsLoading}
              >
                <option value="">
                  {clientsLoading ? "Loading clients…" : "— Choose a client —"}
                </option>
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.client_name}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Empty state */}
      {!selectedClient && !loading && (
        <div className="flex flex-col items-center justify-center py-20 text-gray-400">
          <ExternalLink size={40} className="mb-3 opacity-30" />
          <p className="text-base font-medium">Select a client to preview their portal</p>
          <p className="text-sm mt-1 opacity-70">
            You&apos;ll see exactly what they see when they log in
          </p>
        </div>
      )}

      {/* Portal Preview */}
      {selectedClient && (
        <div className="space-y-5">
          {/* Welcome banner — simulating what the client sees */}
          <div className="rounded-xl border border-blue-100 bg-gradient-to-br from-blue-50 to-indigo-50 p-5">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-xs font-semibold text-blue-500 uppercase tracking-widest mb-1">
                  Client Portal — Preview Mode
                </p>
                <h2 className="text-xl font-bold text-gray-900">
                  Welcome, {selectedClient.client_name}
                </h2>
                <p className="text-sm text-gray-500 mt-1">
                  Managed by your CA firm
                </p>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-4 text-sm">
              {selectedClient.gstin && (
                <div>
                  <span className="text-xs text-gray-400 block">GSTIN</span>
                  <span className="font-mono font-semibold text-gray-800">
                    {selectedClient.gstin}
                  </span>
                </div>
              )}
              <div>
                <span className="text-xs text-gray-400 block">PAN</span>
                <span className="font-mono font-semibold text-gray-800">
                  {selectedClient.pan}
                </span>
              </div>
              {selectedClient.entity_type && (
                <div>
                  <span className="text-xs text-gray-400 block">Entity Type</span>
                  <span className="font-semibold text-gray-800 capitalize">
                    {selectedClient.entity_type.replace(/_/g, " ")}
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Portal tabs */}
          <div className="flex gap-1 border-b border-gray-100">
            {PORTAL_TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === tab.id
                    ? "border-blue-600 text-blue-700"
                    : "border-transparent text-gray-500 hover:text-gray-700"
                }`}
              >
                <tab.icon size={14} />
                {tab.label}
              </button>
            ))}
          </div>

          {loading && (
            <div className="text-center py-8 text-sm text-gray-400 animate-pulse">
              Loading portal data…
            </div>
          )}

          {!loading && (
            <>
              {/* Pending Documents */}
              {activeTab === "documents" && (
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <FileText size={15} /> Documents Requested by Your CA
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {MOCK_DOCUMENTS.map((doc) => (
                      <div
                        key={doc.id}
                        className="flex items-start gap-3 p-3 rounded-lg border border-gray-100 hover:bg-gray-50"
                      >
                        <div className="mt-0.5">
                          <div className="w-8 h-8 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center shrink-0">
                            <FileText size={14} />
                          </div>
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-gray-900">
                            {doc.title}
                          </p>
                          <p className="text-xs text-gray-500 mt-0.5">{doc.desc}</p>
                        </div>
                        {doc.urgent && (
                          <Badge className="text-xs bg-amber-100 text-amber-700 shrink-0">
                            Urgent
                          </Badge>
                        )}
                        <button className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors shrink-0">
                          Upload
                        </button>
                      </div>
                    ))}
                    {pendingFilings.length > 0 && (
                      <div className="mt-2 pt-3 border-t border-gray-100">
                        <p className="text-xs font-medium text-gray-500 mb-2">
                          Also pending from compliance calendar:
                        </p>
                        {pendingFilings.map((c) => (
                          <div
                            key={c.id}
                            className="flex items-center gap-3 py-2 text-sm text-gray-600"
                          >
                            <CheckCircle size={13} className="text-amber-400 shrink-0" />
                            <span className="flex-1">{c.compliance_type}</span>
                            <span className="text-xs text-gray-400">
                              Due {formatDate(c.due_date)}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              )}

              {/* Recent Filings */}
              {activeTab === "filings" && (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <Receipt size={15} /> Recent Filings
                    </CardTitle>
                  </CardHeader>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-gray-100 text-xs text-gray-400">
                          <th className="px-5 py-3 text-left font-semibold">Form</th>
                          <th className="px-3 py-3 text-left font-semibold">Period</th>
                          <th className="px-3 py-3 text-left font-semibold">Status</th>
                          <th className="px-3 py-3 text-left font-semibold">Filed Date</th>
                          <th className="px-5 py-3 text-left font-semibold">ARN</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-50">
                        {recentFilings.length > 0
                          ? recentFilings.map((c) => (
                              <tr key={c.id} className="hover:bg-gray-50">
                                <td className="px-5 py-3 text-sm font-medium text-gray-900">
                                  {c.compliance_type}
                                </td>
                                <td className="px-3 py-3 text-xs text-gray-500 whitespace-nowrap">
                                  {formatDate(c.period_start)} – {formatDate(c.period_end)}
                                </td>
                                <td className="px-3 py-3">
                                  <Badge
                                    className={`text-xs ${
                                      FILING_STATUS_COLORS[c.filing_status] ??
                                      "bg-gray-100 text-gray-600"
                                    }`}
                                  >
                                    {c.filing_status}
                                  </Badge>
                                </td>
                                <td className="px-3 py-3 text-xs text-gray-500 whitespace-nowrap">
                                  {c.filed_date ? formatDate(c.filed_date) : "—"}
                                </td>
                                <td className="px-5 py-3 text-xs font-mono text-gray-400">
                                  {c.arn_number ?? "—"}
                                </td>
                              </tr>
                            ))
                          : [
                              {
                                id: "m1",
                                form: "GSTR-3B",
                                period: "Mar 2026",
                                status: "Filed",
                                filed: "20 Apr 2026",
                                arn: "AA261200099999",
                              },
                              {
                                id: "m2",
                                form: "GSTR-1",
                                period: "Mar 2026",
                                status: "Filed",
                                filed: "11 Apr 2026",
                                arn: "AA261100088888",
                              },
                              {
                                id: "m3",
                                form: "GSTR-3B",
                                period: "Feb 2026",
                                status: "Filed",
                                filed: "20 Mar 2026",
                                arn: "AA260300077777",
                              },
                            ].map((row) => (
                              <tr key={row.id} className="hover:bg-gray-50">
                                <td className="px-5 py-3 text-sm font-medium text-gray-900">
                                  {row.form}
                                </td>
                                <td className="px-3 py-3 text-xs text-gray-500">{row.period}</td>
                                <td className="px-3 py-3">
                                  <Badge className="text-xs bg-green-100 text-green-700">
                                    {row.status}
                                  </Badge>
                                </td>
                                <td className="px-3 py-3 text-xs text-gray-500">{row.filed}</td>
                                <td className="px-5 py-3 text-xs font-mono text-gray-400">
                                  {row.arn}
                                </td>
                              </tr>
                            ))}
                      </tbody>
                    </table>
                    {recentFilings.length === 0 && (
                      <p className="text-center text-xs text-gray-400 py-2 pb-4">
                        Showing sample data — no filed entries found in compliance calendar
                      </p>
                    )}
                  </div>
                </Card>
              )}

              {/* Outstanding Dues */}
              {activeTab === "dues" && (
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <Receipt size={15} /> Outstanding Dues
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {unpaidInvoices.length > 0 ? (
                      unpaidInvoices.map((t) => (
                        <div
                          key={t.id}
                          className="flex items-center gap-4 p-3 rounded-lg border border-gray-100 hover:bg-gray-50"
                        >
                          <div className="flex-1">
                            <p className="text-sm font-medium text-gray-900">
                              {t.party_name}
                            </p>
                            <p className="text-xs text-gray-500 mt-0.5">
                              {formatDate(t.transaction_date)}
                              {t.reference_no ? ` · Ref: ${t.reference_no}` : ""}
                            </p>
                          </div>
                          <span className="text-sm font-semibold text-gray-800">
                            {formatPaise(t.total_paise)}
                          </span>
                          <Badge className="text-xs bg-amber-100 text-amber-700">
                            {t.status}
                          </Badge>
                        </div>
                      ))
                    ) : (
                      // Mock dues when no real unpaid transactions
                      MOCK_DUES.map((due) => (
                        <div
                          key={due.id}
                          className="flex items-center gap-4 p-3 rounded-lg border border-gray-100 hover:bg-gray-50"
                        >
                          <div className="flex-1">
                            <p className="text-sm font-medium text-gray-900">
                              {due.description}
                            </p>
                            <p className="text-xs text-gray-500 mt-0.5">Due: {due.due}</p>
                          </div>
                          <span className="text-sm font-semibold text-gray-800">
                            {due.amount}
                          </span>
                          <Badge
                            className={`text-xs ${
                              due.status === "Overdue"
                                ? "bg-red-100 text-red-700"
                                : "bg-amber-100 text-amber-700"
                            }`}
                          >
                            {due.status}
                          </Badge>
                        </div>
                      ))
                    )}
                  </CardContent>
                </Card>
              )}

              {/* Messages */}
              {activeTab === "messages" && (
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <MessageSquare size={15} /> Messages from Your CA
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {MOCK_MESSAGES.map((msg) => (
                      <div key={msg.id} className="flex gap-3">
                        <div className="w-7 h-7 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs font-bold shrink-0 mt-0.5">
                          CA
                        </div>
                        <div className="flex-1 bg-gray-50 rounded-lg px-4 py-3">
                          <p className="text-sm text-gray-800">{msg.text}</p>
                          <p className="text-xs text-gray-400 mt-1">{msg.time}</p>
                        </div>
                      </div>
                    ))}
                    <div className="pt-2 border-t border-gray-100">
                      <p className="text-xs text-gray-400 text-center">
                        To reply or send documents, contact your CA directly via phone or email.
                      </p>
                    </div>
                  </CardContent>
                </Card>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
