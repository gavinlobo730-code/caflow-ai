"use client";

import { useState, useEffect, useRef } from "react";
import {
  ExternalLink, Copy, CheckCircle, FileText, MessageSquare, Receipt,
  Plus, Trash2, Download, Upload, FolderOpen, AlertTriangle, BarChart3,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getClients } from "@/lib/data/clients";
import { getComplianceCalendar } from "@/lib/data/compliance";
import { getTransactions } from "@/lib/data/transactions";
import { getFirmId } from "@/lib/data/getFirmId";
import { getSupabaseClient } from "@/lib/supabase/client";
import type { Client } from "@/lib/types";
import type { ComplianceEntry } from "@/lib/data/compliance";
import type { Transaction } from "@/lib/data/transactions";
import { formatDate } from "@/lib/services/formatting";
import { formatPaise } from "@/lib/services/formatting";

type PortalTab = "requests" | "shared" | "reports" | "filings" | "dues" | "messages";

const PORTAL_TABS: { id: PortalTab; label: string; icon: React.ElementType }[] = [
  { id: "requests", label: "Document Requests", icon: FileText },
  { id: "shared", label: "Shared Documents", icon: FolderOpen },
  { id: "reports", label: "Shared Reports", icon: BarChart3 },
  { id: "filings", label: "Recent Filings", icon: Receipt },
  { id: "dues", label: "Outstanding Dues", icon: Receipt },
  { id: "messages", label: "Messages", icon: MessageSquare },
];

const MOCK_DUES = [
  { id: "1", description: "Professional fees — FY 2025-26 Q4", amount: "₹18,000", due: "15 Jun 2026", status: "Unpaid" },
  { id: "2", description: "GSTR filing charges — Mar 2026", amount: "₹2,500", due: "30 May 2026", status: "Overdue" },
];

const MOCK_MESSAGES = [
  { id: "1", from: "CA", text: "Your GSTR-1 for March 2026 has been filed successfully. ✓", time: "2 days ago" },
  { id: "2", from: "CA", text: "Please upload your Q4 bank statement at the earliest so we can reconcile before the audit.", time: "5 days ago" },
  { id: "3", from: "CA", text: "Advance tax instalment of 15% was due on 15 Jun. Please confirm payment made.", time: "1 week ago" },
];

const FILING_STATUS_COLORS: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  in_progress: "bg-blue-100 text-blue-700",
  filed: "bg-green-100 text-green-700",
  overdue: "bg-red-100 text-red-700",
  na: "bg-white/[0.06] text-white/40",
};

interface DocumentRequest {
  id: string;
  title: string;
  description: string | null;
  is_urgent: boolean;
  status: string;
  fulfilled_at: string | null;
  created_at: string;
}

interface SharedDocument {
  id: string;
  file_name: string;
  label: string;
  storage_path: string;
  file_size_bytes: number | null;
  created_at: string;
}

interface SharedReport {
  id: string;
  report_label: string;
  report_type: string;
  financial_year: string;
  storage_path: string;
  file_name: string;
  file_size_bytes: number | null;
  created_at: string;
}

interface NewRequestForm {
  title: string;
  description: string;
  is_urgent: boolean;
}

function formatFileSize(bytes: number | null): string {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ClientPortalPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<string>("");
  const [selectedClient, setSelectedClient] = useState<Client | null>(null);
  const [compliance, setCompliance] = useState<ComplianceEntry[]>([]);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(false);
  const [clientsLoading, setClientsLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<PortalTab>("requests");
  const [copied, setCopied] = useState(false);

  // Document requests state
  const [docRequests, setDocRequests] = useState<DocumentRequest[]>([]);
  const [requestsLoading, setRequestsLoading] = useState(false);
  const [showNewRequestModal, setShowNewRequestModal] = useState(false);
  const [newRequest, setNewRequest] = useState<NewRequestForm>({ title: "", description: "", is_urgent: false });
  const [savingRequest, setSavingRequest] = useState(false);

  // Shared documents state
  const [sharedDocs, setSharedDocs] = useState<SharedDocument[]>([]);
  const [sharedReports, setSharedReports] = useState<SharedReport[]>([]);
  const [sharedLoading, setSharedLoading] = useState(false);
  const [uploadingDoc, setUploadingDoc] = useState(false);
  const [uploadLabel, setUploadLabel] = useState("");
  const sharedUploadRef = useRef<HTMLInputElement | null>(null);

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
      setDocRequests([]);
      setSharedDocs([]);
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

    loadDocRequests(selectedClientId);
    loadSharedDocs(selectedClientId);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedClientId, clients]);

  async function loadDocRequests(clientId: string) {
    setRequestsLoading(true);
    try {
      const sb = getSupabaseClient();
      const { data } = await sb
        .from("document_requests")
        .select("id, title, description, is_urgent, status, fulfilled_at, created_at")
        .eq("client_id", clientId)
        .order("created_at", { ascending: false });
      setDocRequests(data ?? []);
    } catch {
      setDocRequests([]);
    } finally {
      setRequestsLoading(false);
    }
  }

  async function loadSharedDocs(clientId: string) {
    setSharedLoading(true);
    try {
      const sb = getSupabaseClient();
      const { data } = await sb
        .from("client_documents")
        .select("id, file_name, label, storage_path, file_size_bytes, created_at")
        .eq("client_id", clientId)
        .order("created_at", { ascending: false });
      setSharedDocs(data ?? []);

      // Load shared reports
      const { data: reportData } = await sb
        .from("shared_reports")
        .select("id, report_label, report_type, financial_year, storage_path, file_name, file_size_bytes, created_at")
        .eq("client_id", clientId)
        .order("created_at", { ascending: false });
      setSharedReports(reportData ?? []);
    } catch {
      setSharedDocs([]);
    } finally {
      setSharedLoading(false);
    }
  }

  async function handleCreateRequest() {
    if (!newRequest.title.trim() || !selectedClientId) return;
    setSavingRequest(true);
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();
      await sb.from("document_requests").insert({
        firm_id: firmId,
        client_id: selectedClientId,
        title: newRequest.title.trim(),
        description: newRequest.description.trim() || null,
        is_urgent: newRequest.is_urgent,
      });
      setShowNewRequestModal(false);
      setNewRequest({ title: "", description: "", is_urgent: false });
      await loadDocRequests(selectedClientId);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to create request");
    } finally {
      setSavingRequest(false);
    }
  }

  async function handleDeleteRequest(id: string) {
    if (!confirm("Delete this document request?")) return;
    const sb = getSupabaseClient();
    await sb.from("document_requests").delete().eq("id", id);
    setDocRequests((prev) => prev.filter((r) => r.id !== id));
  }

  async function handleSharedDocUpload(file: File) {
    if (!selectedClientId) return;
    const label = uploadLabel.trim() || file.name;
    setUploadingDoc(true);
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();
      const uuid = crypto.randomUUID();
      const storagePath = `${firmId}/${selectedClientId}/${uuid}-${file.name}`;

      const { error: uploadErr } = await sb.storage
        .from("Documents")
        .upload(storagePath, file, { contentType: file.type || "application/octet-stream" });
      if (uploadErr) throw new Error(uploadErr.message);

      const { data: userSession } = await sb.auth.getSession();
      await sb.from("client_documents").insert({
        firm_id: firmId,
        client_id: selectedClientId,
        uploaded_by: userSession?.session?.user?.id ?? null,
        file_name: file.name,
        label,
        storage_path: storagePath,
        file_size_bytes: file.size,
        mime_type: file.type || null,
      });

      setUploadLabel("");
      await loadSharedDocs(selectedClientId);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploadingDoc(false);
    }
  }

  async function handleDeleteSharedDoc(doc: SharedDocument) {
    if (!confirm(`Delete "${doc.label}"?`)) return;
    const sb = getSupabaseClient();
    await sb.storage.from("Documents").remove([doc.storage_path]);
    await sb.from("client_documents").delete().eq("id", doc.id);
    setSharedDocs((prev) => prev.filter((d) => d.id !== doc.id));
  }

  async function handleDownloadSharedDoc(doc: SharedDocument) {
    const sb = getSupabaseClient();
    const { data, error: err } = await sb.storage
      .from("Documents")
      .createSignedUrl(doc.storage_path, 3600);
    if (err || !data) {
      alert("Could not generate download link.");
      return;
    }
    window.open(data.signedUrl, "_blank");
  }

  async function handleCopyPortalLink() {
    const url = `${window.location.origin}/portal`;
    await navigator.clipboard.writeText(url).catch(() => undefined);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  }

  const recentFilings = compliance.filter((c) => c.filing_status === "filed").slice(0, 8);
  const unpaidInvoices = transactions.filter((t) => t.status !== "posted");

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Page Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white/85">Client Portal Preview</h1>
          <p className="text-sm text-white/40 mt-1">
            Manage document requests and shared files for your clients
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
            <ExternalLink size={16} className="text-white/30 shrink-0" />
            <div className="flex-1">
              <label htmlFor="client-select" className="block text-xs font-medium text-white/40 mb-1">
                Select a client to manage their portal
              </label>
              <select
                id="client-select"
                value={selectedClientId}
                onChange={(e) => setSelectedClientId(e.target.value)}
                className="w-full max-w-sm px-3 py-1.5 text-sm border border-white/[0.07] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#131620]"
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
        <div className="flex flex-col items-center justify-center py-20 text-white/30">
          <ExternalLink size={40} className="mb-3 opacity-30" />
          <p className="text-base font-medium">Select a client to manage their portal</p>
          <p className="text-sm mt-1 opacity-70">
            Request documents, share files, and view compliance status
          </p>
        </div>
      )}

      {/* Portal management area */}
      {selectedClient && (
        <div className="space-y-5">
          {/* Client info banner */}
          <div className="rounded-xl border border-blue-100 bg-gradient-to-br from-blue-50 to-blue-500 p-5">
            <div>
              <p className="text-xs font-semibold text-blue-500 uppercase tracking-widest mb-1">
                Portal Management
              </p>
              <h2 className="text-xl font-bold text-white/85">{selectedClient.client_name}</h2>
              <p className="text-sm text-white/40 mt-1">Manage documents and requests for this client</p>
            </div>
            <div className="mt-4 flex flex-wrap gap-4 text-sm">
              {selectedClient.gstin && (
                <div>
                  <span className="text-xs text-white/30 block">GSTIN</span>
                  <span className="font-mono font-semibold text-white/75">{selectedClient.gstin}</span>
                </div>
              )}
              <div>
                <span className="text-xs text-white/30 block">PAN</span>
                <span className="font-mono font-semibold text-white/75">{selectedClient.pan}</span>
              </div>
              {selectedClient.entity_type && (
                <div>
                  <span className="text-xs text-white/30 block">Entity Type</span>
                  <span className="font-semibold text-white/75 capitalize">
                    {selectedClient.entity_type.replace(/_/g, " ")}
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Tabs */}
          <div className="flex gap-1 border-b border-white/[0.05] overflow-x-auto">
            {PORTAL_TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                  activeTab === tab.id
                    ? "border-blue-600 text-blue-700"
                    : "border-transparent text-white/40 hover:text-white/65"
                }`}
              >
                <tab.icon size={14} />
                {tab.label}
              </button>
            ))}
          </div>

          {loading && (
            <div className="text-center py-8 text-sm text-white/30 animate-pulse">
              Loading client data…
            </div>
          )}

          {!loading && (
            <>
              {/* Document Requests tab */}
              {activeTab === "requests" && (
                <Card>
                  <CardHeader className="pb-3 flex flex-row items-center justify-between">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <FileText size={15} /> Document Requests
                    </CardTitle>
                    <button
                      onClick={() => setShowNewRequestModal(true)}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700 transition-colors"
                    >
                      <Plus size={13} /> New Request
                    </button>
                  </CardHeader>
                  <CardContent>
                    {requestsLoading ? (
                      <div className="text-center py-6 text-sm text-white/30 animate-pulse">Loading…</div>
                    ) : docRequests.length === 0 ? (
                      <div className="text-center py-10 space-y-2">
                        <FileText size={32} className="text-gray-200 mx-auto" />
                        <p className="text-sm text-white/30">
                          No document requests yet — click New Request to ask your client for files
                        </p>
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {docRequests.map((req) => (
                          <div
                            key={req.id}
                            className="flex items-start gap-3 p-3 rounded-lg border border-white/[0.05] hover:bg-[#0e1017]"
                          >
                            <div className="w-8 h-8 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center shrink-0 mt-0.5">
                              <FileText size={14} />
                            </div>
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-medium text-white/85">{req.title}</p>
                              {req.description && (
                                <p className="text-xs text-white/40 mt-0.5">{req.description}</p>
                              )}
                              <p className="text-xs text-white/30 mt-1">{formatDate(req.created_at)}</p>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                              {req.is_urgent && (
                                <Badge className="text-xs bg-amber-100 text-amber-700">
                                  <AlertTriangle size={10} className="mr-1" /> Urgent
                                </Badge>
                              )}
                              <Badge
                                className={`text-xs ${
                                  req.status === "fulfilled"
                                    ? "bg-green-100 text-green-700"
                                    : "bg-white/[0.06] text-white/55"
                                }`}
                              >
                                {req.status === "fulfilled" ? "Fulfilled" : "Pending"}
                              </Badge>
                              <button
                                onClick={() => handleDeleteRequest(req.id)}
                                className="p-1.5 text-white/30 hover:text-red-500 hover:bg-red-50 rounded transition-colors"
                                title="Delete request"
                              >
                                <Trash2 size={13} />
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              )}

              {/* Shared Documents tab */}
              {activeTab === "shared" && (
                <Card>
                  <CardHeader className="pb-3 flex flex-row items-center justify-between">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <FolderOpen size={15} /> Shared Documents
                      <span className="text-xs text-white/30 font-normal ml-1">(CA → Client)</span>
                    </CardTitle>
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        placeholder="Label (optional)"
                        value={uploadLabel}
                        onChange={(e) => setUploadLabel(e.target.value)}
                        className="text-xs px-2 py-1.5 border border-white/[0.07] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 w-36"
                      />
                      <input
                        type="file"
                        className="hidden"
                        ref={sharedUploadRef}
                        onChange={(e) => {
                          const f = e.target.files?.[0];
                          if (f) handleSharedDocUpload(f);
                          e.target.value = "";
                        }}
                      />
                      <button
                        onClick={() => sharedUploadRef.current?.click()}
                        disabled={uploadingDoc}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-60"
                      >
                        <Upload size={13} />
                        {uploadingDoc ? "Uploading…" : "Upload"}
                      </button>
                    </div>
                  </CardHeader>
                  <CardContent>
                    {sharedLoading ? (
                      <div className="text-center py-6 text-sm text-white/30 animate-pulse">Loading…</div>
                    ) : sharedDocs.length === 0 ? (
                      <div className="text-center py-10 space-y-2">
                        <FolderOpen size={32} className="text-gray-200 mx-auto" />
                        <p className="text-sm text-white/30">
                          No documents shared yet — upload returns, notices, and certificates for this client
                        </p>
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {sharedDocs.map((doc) => (
                          <div
                            key={doc.id}
                            className="flex items-center gap-3 p-3 rounded-lg border border-white/[0.05] hover:bg-[#0e1017]"
                          >
                            <div className="w-8 h-8 rounded-full bg-blue-500/10 text-blue-400 flex items-center justify-center shrink-0">
                              <FolderOpen size={14} />
                            </div>
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-medium text-white/85 truncate">{doc.label}</p>
                              <p className="text-xs text-white/30 mt-0.5">
                                {doc.file_name}
                                {doc.file_size_bytes ? ` · ${formatFileSize(doc.file_size_bytes)}` : ""}
                                {" · "}{formatDate(doc.created_at)}
                              </p>
                            </div>
                            <div className="flex items-center gap-1.5 shrink-0">
                              <button
                                onClick={() => handleDownloadSharedDoc(doc)}
                                className="p-1.5 text-white/30 hover:text-blue-600 hover:bg-blue-50 rounded transition-colors"
                                title="Download"
                              >
                                <Download size={13} />
                              </button>
                              <button
                                onClick={() => handleDeleteSharedDoc(doc)}
                                className="p-1.5 text-white/30 hover:text-red-500 hover:bg-red-50 rounded transition-colors"
                                title="Delete"
                              >
                                <Trash2 size={13} />
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              )}

              {/* Shared Reports tab */}
              {activeTab === "reports" && (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <BarChart3 size={14} className="text-blue-600" />
                      Reports Shared with Client
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-0">
                    {sharedReports.length === 0 ? (
                      <div className="px-6 py-10 text-center text-sm text-white/30">
                        <BarChart3 size={28} className="mx-auto mb-2 opacity-20" />
                        <p>No reports shared yet.</p>
                        <p className="text-xs mt-1 text-white/20">Go to Reports → Financial Statements → Generate → Share with Client</p>
                      </div>
                    ) : (
                      <div className="divide-y divide-white/[0.03]">
                        {sharedReports.map((r) => (
                          <div key={r.id} className="px-4 py-3 flex items-center justify-between gap-4">
                            <div className="min-w-0">
                              <p className="text-sm font-medium text-white/85 truncate">{r.report_label}</p>
                              <p className="text-xs text-white/30 mt-0.5">
                                FY {r.financial_year}
                                {r.file_size_bytes ? ` · ${formatFileSize(r.file_size_bytes)}` : ""}
                                {" · "}{formatDate(r.created_at)}
                              </p>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                              <button
                                onClick={async () => {
                                  const sb = getSupabaseClient();
                                  const { data } = await sb.storage.from("Documents").createSignedUrl(r.storage_path, 3600);
                                  if (data) window.open(data.signedUrl, "_blank");
                                }}
                                className="flex items-center gap-1.5 text-xs bg-blue-50 text-blue-700 px-3 py-1.5 rounded-lg hover:bg-blue-100"
                              >
                                <Download size={12} /> Download
                              </button>
                              <button
                                onClick={async () => {
                                  if (!confirm("Remove this shared report?")) return;
                                  const sb = getSupabaseClient();
                                  await sb.from("shared_reports").delete().eq("id", r.id);
                                  setSharedReports((prev) => prev.filter((x) => x.id !== r.id));
                                }}
                                className="flex items-center gap-1 text-xs text-red-400 hover:text-red-600 px-2 py-1.5 rounded-lg hover:bg-red-50"
                              >
                                <Trash2 size={12} />
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              )}

              {/* Recent Filings tab */}
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
                        <tr className="border-b border-white/[0.05] text-xs text-white/30">
                          <th className="px-5 py-3 text-left font-semibold">Form</th>
                          <th className="px-3 py-3 text-left font-semibold">Period</th>
                          <th className="px-3 py-3 text-left font-semibold">Status</th>
                          <th className="px-3 py-3 text-left font-semibold">Filed Date</th>
                          <th className="px-5 py-3 text-left font-semibold">ARN</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/[0.03]">
                        {recentFilings.length > 0
                          ? recentFilings.map((c) => (
                              <tr key={c.id} className="hover:bg-[#0e1017]">
                                <td className="px-5 py-3 text-sm font-medium text-white/85">
                                  {c.compliance_type}
                                </td>
                                <td className="px-3 py-3 text-xs text-white/40 whitespace-nowrap">
                                  {formatDate(c.period_start)} – {formatDate(c.period_end)}
                                </td>
                                <td className="px-3 py-3">
                                  <Badge className={`text-xs ${FILING_STATUS_COLORS[c.filing_status] ?? "bg-white/[0.06] text-white/55"}`}>
                                    {c.filing_status}
                                  </Badge>
                                </td>
                                <td className="px-3 py-3 text-xs text-white/40 whitespace-nowrap">
                                  {c.filed_date ? formatDate(c.filed_date) : "—"}
                                </td>
                                <td className="px-5 py-3 text-xs font-mono text-white/30">
                                  {c.arn_number ?? "—"}
                                </td>
                              </tr>
                            ))
                          : (
                            <tr>
                              <td colSpan={5} className="text-center text-xs text-white/30 py-8">
                                No filed entries in compliance calendar for this client
                              </td>
                            </tr>
                          )}
                      </tbody>
                    </table>
                  </div>
                </Card>
              )}

              {/* Outstanding Dues tab */}
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
                          className="flex items-center gap-4 p-3 rounded-lg border border-white/[0.05] hover:bg-[#0e1017]"
                        >
                          <div className="flex-1">
                            <p className="text-sm font-medium text-white/85">{t.party_name}</p>
                            <p className="text-xs text-white/40 mt-0.5">
                              {formatDate(t.transaction_date)}
                              {t.reference_no ? ` · Ref: ${t.reference_no}` : ""}
                            </p>
                          </div>
                          <span className="text-sm font-semibold text-white/75">
                            {formatPaise(t.total_paise)}
                          </span>
                          <Badge className="text-xs bg-amber-100 text-amber-700">{t.status}</Badge>
                        </div>
                      ))
                    ) : (
                      MOCK_DUES.map((due) => (
                        <div
                          key={due.id}
                          className="flex items-center gap-4 p-3 rounded-lg border border-white/[0.05] hover:bg-[#0e1017]"
                        >
                          <div className="flex-1">
                            <p className="text-sm font-medium text-white/85">{due.description}</p>
                            <p className="text-xs text-white/40 mt-0.5">Due: {due.due}</p>
                          </div>
                          <span className="text-sm font-semibold text-white/75">{due.amount}</span>
                          <Badge
                            className={`text-xs ${
                              due.status === "Overdue" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"
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

              {/* Messages tab */}
              {activeTab === "messages" && (
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <MessageSquare size={15} /> Messages from CA
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {MOCK_MESSAGES.map((msg) => (
                      <div key={msg.id} className="flex gap-3">
                        <div className="w-7 h-7 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs font-bold shrink-0 mt-0.5">
                          CA
                        </div>
                        <div className="flex-1 bg-[#0e1017] rounded-lg px-4 py-3">
                          <p className="text-sm text-white/75">{msg.text}</p>
                          <p className="text-xs text-white/30 mt-1">{msg.time}</p>
                        </div>
                      </div>
                    ))}
                    <div className="pt-2 border-t border-white/[0.05]">
                      <p className="text-xs text-white/30 text-center">
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

      {/* New Request Modal */}
      {showNewRequestModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-[#131620] rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
            <h3 className="text-base font-semibold text-white/85">New Document Request</h3>
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-white/55 mb-1">Title *</label>
                <input
                  type="text"
                  placeholder="e.g. Upload Q4 Bank Statement"
                  value={newRequest.title}
                  onChange={(e) => setNewRequest((p) => ({ ...p, title: e.target.value }))}
                  className="w-full px-3 py-2 text-sm border border-white/[0.07] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  autoFocus
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-white/55 mb-1">Description</label>
                <textarea
                  placeholder="e.g. For the period Jan–Mar 2026"
                  value={newRequest.description}
                  onChange={(e) => setNewRequest((p) => ({ ...p, description: e.target.value }))}
                  className="w-full px-3 py-2 text-sm border border-white/[0.07] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                  rows={3}
                />
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={newRequest.is_urgent}
                  onChange={(e) => setNewRequest((p) => ({ ...p, is_urgent: e.target.checked }))}
                  className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                <span className="text-sm text-white/65">Mark as Urgent</span>
                <AlertTriangle size={14} className="text-amber-500" />
              </label>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => {
                  setShowNewRequestModal(false);
                  setNewRequest({ title: "", description: "", is_urgent: false });
                }}
                className="px-4 py-2 text-sm text-white/55 border border-white/[0.07] rounded-lg hover:bg-[#0e1017]"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateRequest}
                disabled={!newRequest.title.trim() || savingRequest}
                className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium"
              >
                {savingRequest ? "Creating…" : "Create Request"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
