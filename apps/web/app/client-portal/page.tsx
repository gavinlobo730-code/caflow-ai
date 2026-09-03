"use client";

import { useState, useEffect, useRef } from "react";
import {
  ExternalLink, Copy, CheckCircle, FileText, MessageSquare, Receipt,
  Plus, Trash2, Download, Upload, FolderOpen, AlertTriangle, BarChart3,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { getClients } from "@/lib/data/clients";
import { getComplianceCalendar } from "@/lib/data/compliance";
import { getTransactions } from "@/lib/data/transactions";
import { getFirmId } from "@/lib/data/getFirmId";
import { getSupabaseClient } from "@/lib/supabase/client";
import { api } from "@/lib/api";
import type { Client } from "@/lib/types";
import type { ComplianceEntry } from "@/lib/data/compliance";
import type { Transaction } from "@/lib/data/transactions";
import { formatDate } from "@/lib/services/formatting";
import { formatPaise } from "@/lib/services/formatting";
import { ListSkeleton, TransactionListSkeleton } from "@/components/ui/skeleton";

type PortalTab = "requests" | "shared" | "reports" | "filings" | "dues" | "messages";

const PORTAL_TABS: { id: PortalTab; label: string; icon: React.ElementType }[] = [
  { id: "requests", label: "Document Requests", icon: FileText },
  { id: "shared", label: "Shared Documents", icon: FolderOpen },
  { id: "reports", label: "Shared Reports", icon: BarChart3 },
  { id: "filings", label: "Recent Filings", icon: Receipt },
  { id: "dues", label: "Outstanding Dues", icon: Receipt },
  { id: "messages", label: "Messages", icon: MessageSquare },
];


const FILING_STATUS_COLORS: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  in_progress: "bg-blue-100 text-blue-700",
  filed: "bg-green-100 text-green-700",
  overdue: "bg-red-100 text-red-700",
  na: "bg-[#F1F5F9] text-[#64748B]",
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

// Mirrors client_documents as it actually is. Migration 023 defines this table
// with label/storage_path/file_size_bytes — but 014 had already created it with
// file_path/file_size and no label, and 023 uses CREATE TABLE IF NOT EXISTS, so
// 023's definition was a silent no-op. The live table is 014's. This page was
// written against 023's shape, so every query and insert here failed.
//
// NOTE: SharedReport below keeps storage_path/file_size_bytes — shared_reports
// is a different table and genuinely has those columns. Do not "fix" them.
interface SharedDocument {
  id: string;
  file_name: string;
  description: string | null;   // the user-supplied label
  file_path: string;            // Supabase Storage path
  file_size: number | null;     // bytes
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

interface PortalMessage {
  id: string;
  firm_id: string;
  client_id: string;
  text: string;
  from_ca: boolean;
  created_at: string;
}

interface ApiDue {
  id: string;
  party_name: string;
  transaction_date: string;
  reference_no: string | null;
  total_paise: number;
  status: string;
}

interface DuesResponse {
  dues: ApiDue[];
  total_paise: number;
  overdue_count: number;
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
  // Distinguishes "fetch failed" from "no clients yet" — a masked failure
  // previously rendered the client picker as empty with no indication.
  const [clientsFailed, setClientsFailed] = useState(false);
  const [activeTab, setActiveTab] = useState<PortalTab>("requests");
  const [copied, setCopied] = useState(false);

  // Document requests state
  const [docRequests, setDocRequests] = useState<DocumentRequest[]>([]);
  const [requestsLoading, setRequestsLoading] = useState(false);
  // Mirrors duesFailed below — distinguishes "fetch failed" from "no
  // document requests yet."
  const [requestsFailed, setRequestsFailed] = useState(false);
  const [showNewRequestModal, setShowNewRequestModal] = useState(false);
  const [newRequest, setNewRequest] = useState<NewRequestForm>({ title: "", description: "", is_urgent: false });
  const [savingRequest, setSavingRequest] = useState(false);

  // Shared documents state
  const [sharedDocs, setSharedDocs] = useState<SharedDocument[]>([]);
  const [sharedReports, setSharedReports] = useState<SharedReport[]>([]);
  const [sharedLoading, setSharedLoading] = useState(false);
  // Distinguishes "fetch failed" from "nothing shared yet."
  const [sharedFailed, setSharedFailed] = useState(false);
  const [uploadingDoc, setUploadingDoc] = useState(false);
  const [uploadLabel, setUploadLabel] = useState("");
  const sharedUploadRef = useRef<HTMLInputElement | null>(null);

  // Portal messages state
  const [portalMessages, setPortalMessages] = useState<PortalMessage[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  // Distinguishes "fetch failed" from "no messages yet."
  const [messagesFailed, setMessagesFailed] = useState(false);
  const [newMessageText, setNewMessageText] = useState("");
  const [sendingMessage, setSendingMessage] = useState(false);

  // Dues state
  const [apiDues, setApiDues] = useState<ApiDue[]>([]);
  const [duesLoading, setDuesLoading] = useState(false);
  // True when the LAST dues fetch failed (error/timeout) rather than the client
  // genuinely having nothing outstanding. Without this, a failed load renders as
  // "No outstanding dues" — indistinguishable, to the portal viewer, from a
  // paid-up client (audit M17). Mirrors TrialBalance.loadFailed in accounting.
  const [duesFailed, setDuesFailed] = useState(false);

  // Load clients list on mount
  useEffect(() => {
    getClients()
      .then((c) => { setClients(c); setClientsFailed(false); })
      .catch(() => { setClients([]); setClientsFailed(true); })
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
      setPortalMessages([]);
      setApiDues([]);
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
    loadPortalMessages(selectedClientId);
    loadDues(selectedClientId);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedClientId, clients]);

  async function loadDocRequests(clientId: string) {
    setRequestsLoading(true);
    try {
      const sb = getSupabaseClient();
      const { data, error } = await sb
        .from("document_requests")
        .select("id, title, description, is_urgent, status, fulfilled_at, created_at")
        .eq("client_id", clientId)
        .order("created_at", { ascending: false });
      if (error) throw error;
      setDocRequests(data ?? []);
      setRequestsFailed(false);
    } catch {
      setDocRequests([]);
      setRequestsFailed(true);
    } finally {
      setRequestsLoading(false);
    }
  }

  async function loadSharedDocs(clientId: string) {
    setSharedLoading(true);
    try {
      const sb = getSupabaseClient();
      // Fetched together and only committed to state together — if either
      // query fails, an already-successful result from the other must not
      // be wiped by the failure (the old code's catch cleared sharedDocs
      // unconditionally, discarding a good fetch whenever shared_reports
      // alone failed).
      const [docsRes, reportsRes] = await Promise.all([
        sb.from("client_documents")
          .select("id, file_name, description, file_path, file_size, created_at")
          .eq("client_id", clientId)
          .order("created_at", { ascending: false }),
        sb.from("shared_reports")
          .select("id, report_label, report_type, financial_year, storage_path, file_name, file_size_bytes, created_at")
          .eq("client_id", clientId)
          .order("created_at", { ascending: false }),
      ]);
      if (docsRes.error || reportsRes.error) {
        setSharedFailed(true);
      } else {
        setSharedDocs(docsRes.data ?? []);
        setSharedReports(reportsRes.data ?? []);
        setSharedFailed(false);
      }
    } catch {
      setSharedFailed(true);
    } finally {
      setSharedLoading(false);
    }
  }

  async function loadPortalMessages(clientId: string) {
    setMessagesLoading(true);
    try {
      const firmId = await getFirmId();
      const res = await api.portal.getMessages(firmId, clientId) as { success: boolean; data: PortalMessage[] };
      if (!res.success) throw new Error("Failed to load messages");
      setPortalMessages(res.data ?? []);
      setMessagesFailed(false);
    } catch {
      setPortalMessages([]);
      setMessagesFailed(true);
    } finally {
      setMessagesLoading(false);
    }
  }

  async function loadDues(clientId: string) {
    setDuesLoading(true);
    try {
      const firmId = await getFirmId();
      const res = await api.portal.getDues(firmId, clientId) as { success: boolean; data: DuesResponse };
      // res.success===false only ever comes from a backend error path — a client
      // with nothing outstanding still returns success=true with an empty list.
      if (res.success) {
        setApiDues(res.data?.dues ?? []);
        setDuesFailed(false);
      } else {
        setApiDues([]);
        setDuesFailed(true);
      }
    } catch {
      setApiDues([]);
      setDuesFailed(true);
    } finally {
      setDuesLoading(false);
    }
  }

  async function handleSendMessage() {
    if (!newMessageText.trim() || !selectedClientId) return;
    setSendingMessage(true);
    try {
      const firmId = await getFirmId();
      await api.portal.sendMessage({
        firm_id: firmId,
        client_id: selectedClientId,
        text: newMessageText.trim(),
        from_ca: true,
      });
      setNewMessageText("");
      await loadPortalMessages(selectedClientId);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to send message");
    } finally {
      setSendingMessage(false);
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

      // uploaded_by is deliberately NOT set. It is a foreign key to
      // public.users(id) — the internal id of a FIRM user — and the value
      // available here is the Supabase AUTH id, which is never equal to it
      // (production: 0 of 2 users have id = auth_user_id). Writing it made
      // every portal upload fail the foreign key. A portal uploader is the
      // CLIENT, who has no public.users row at all, so there is no correct
      // value to put here; client_id already carries the attribution, and the
      // CA-side upload page omits the column for the same reason.
      await sb.from("client_documents").insert({
        firm_id: firmId,
        client_id: selectedClientId,
        file_name: file.name,
        description: label,
        file_path: storagePath,
        file_size: file.size,
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
    if (!confirm(`Delete "${doc.description ?? doc.file_name}"?`)) return;
    const sb = getSupabaseClient();
    await sb.storage.from("Documents").remove([doc.file_path]);
    await sb.from("client_documents").delete().eq("id", doc.id);
    setSharedDocs((prev) => prev.filter((d) => d.id !== doc.id));
  }

  async function handleDownloadSharedDoc(doc: SharedDocument) {
    const sb = getSupabaseClient();
    const { data, error: err } = await sb.storage
      .from("Documents")
      .createSignedUrl(doc.file_path, 3600);
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
          <h1 className="text-2xl font-bold text-[#0F172A]">Client Portal Preview</h1>
          <p className="text-sm text-[#64748B] mt-1">
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
            <ExternalLink size={16} className="text-[#94A3B8] shrink-0" />
            <div className="flex-1">
              <label htmlFor="client-select" className="block text-xs font-medium text-[#64748B] mb-1">
                Select a client to manage their portal
              </label>
              <div className="w-full max-w-sm">
                <ClientLookup
                  clients={clients}
                  value={selectedClientId}
                  onChange={setSelectedClientId}
                  ariaLabel="Client"
                  placeholder={clientsLoading ? "Loading clients…" : "— Choose a client —"}
                  disabled={clientsLoading}
                />
              </div>
            </div>
          </div>
          {clientsFailed && (
            <p className="text-xs text-red-600 mt-2">
              Couldn&apos;t load your client list.{" "}
              <button onClick={() => window.location.reload()} className="underline hover:no-underline">Retry</button>
            </p>
          )}
        </CardContent>
      </Card>

      {/* Empty state */}
      {!selectedClient && !loading && (
        <div className="flex flex-col items-center justify-center py-20 text-[#94A3B8]">
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
              <h2 className="text-xl font-bold text-[#0F172A]">{selectedClient.client_name}</h2>
              <p className="text-sm text-[#64748B] mt-1">Manage documents and requests for this client</p>
            </div>
            <div className="mt-4 flex flex-wrap gap-4 text-sm">
              {selectedClient.gstin && (
                <div>
                  <span className="text-xs text-[#94A3B8] block">GSTIN</span>
                  <span className="font-mono font-semibold text-[#1E293B]">{selectedClient.gstin}</span>
                </div>
              )}
              <div>
                <span className="text-xs text-[#94A3B8] block">PAN</span>
                <span className="font-mono font-semibold text-[#1E293B]">{selectedClient.pan}</span>
              </div>
              {selectedClient.entity_type && (
                <div>
                  <span className="text-xs text-[#94A3B8] block">Entity Type</span>
                  <span className="font-semibold text-[#1E293B] capitalize">
                    {selectedClient.entity_type.replace(/_/g, " ")}
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Tabs */}
          <div className="flex gap-1 border-b border-[#F1F5F9] overflow-x-auto">
            {PORTAL_TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                  activeTab === tab.id
                    ? "border-blue-600 text-blue-700"
                    : "border-transparent text-[#64748B] hover:text-[#334155]"
                }`}
              >
                <tab.icon size={14} />
                {tab.label}
              </button>
            ))}
          </div>

          {loading && (
            <div className="text-center py-8 text-sm text-[#94A3B8] animate-pulse">
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
                      <ListSkeleton rows={3} />
                    ) : requestsFailed ? (
                      <div className="text-center py-10 space-y-2">
                        <p className="text-sm text-red-600 font-medium">Couldn&apos;t load document requests.</p>
                        <button onClick={() => loadDocRequests(selectedClientId)} className="text-xs px-3 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
                      </div>
                    ) : docRequests.length === 0 ? (
                      <div className="text-center py-10 space-y-2">
                        <FileText size={32} className="text-gray-200 mx-auto" />
                        <p className="text-sm text-[#94A3B8]">
                          No document requests yet — click New Request to ask your client for files
                        </p>
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {docRequests.map((req) => (
                          <div
                            key={req.id}
                            className="flex items-start gap-3 p-3 rounded-lg border border-[#F1F5F9] hover:bg-[#F8FAFC]"
                          >
                            <div className="w-8 h-8 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center shrink-0 mt-0.5">
                              <FileText size={14} />
                            </div>
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-medium text-[#0F172A]">{req.title}</p>
                              {req.description && (
                                <p className="text-xs text-[#64748B] mt-0.5">{req.description}</p>
                              )}
                              <p className="text-xs text-[#94A3B8] mt-1">{formatDate(req.created_at)}</p>
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
                                    : "bg-[#F1F5F9] text-[#475569]"
                                }`}
                              >
                                {req.status === "fulfilled" ? "Fulfilled" : "Pending"}
                              </Badge>
                              <button
                                onClick={() => handleDeleteRequest(req.id)}
                                className="p-1.5 text-[#94A3B8] hover:text-red-500 hover:bg-red-50 rounded transition-colors"
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
                      <span className="text-xs text-[#94A3B8] font-normal ml-1">(CA → Client)</span>
                    </CardTitle>
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        placeholder="Label (optional)"
                        value={uploadLabel}
                        onChange={(e) => setUploadLabel(e.target.value)}
                        className="text-xs px-2 py-1.5 border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 w-36"
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
                      <ListSkeleton rows={3} />
                    ) : sharedFailed ? (
                      <div className="text-center py-10 space-y-2">
                        <p className="text-sm text-red-600 font-medium">Couldn&apos;t load shared documents.</p>
                        <button onClick={() => loadSharedDocs(selectedClientId)} className="text-xs px-3 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
                      </div>
                    ) : sharedDocs.length === 0 ? (
                      <div className="text-center py-10 space-y-2">
                        <FolderOpen size={32} className="text-gray-200 mx-auto" />
                        <p className="text-sm text-[#94A3B8]">
                          No documents shared yet — upload returns, notices, and certificates for this client
                        </p>
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {sharedDocs.map((doc) => (
                          <div
                            key={doc.id}
                            className="flex items-center gap-3 p-3 rounded-lg border border-[#F1F5F9] hover:bg-[#F8FAFC]"
                          >
                            <div className="w-8 h-8 rounded-full bg-blue-50 text-blue-600 flex items-center justify-center shrink-0">
                              <FolderOpen size={14} />
                            </div>
                            <div className="flex-1 min-w-0">
                              {/* description is the user-supplied label and is nullable; the file name
                                  is the only always-present identifier. */}
                              <p className="text-sm font-medium text-[#0F172A] truncate">{doc.description ?? doc.file_name}</p>
                              <p className="text-xs text-[#94A3B8] mt-0.5">
                                {doc.file_name}
                                {doc.file_size ? ` · ${formatFileSize(doc.file_size)}` : ""}
                                {" · "}{formatDate(doc.created_at)}
                              </p>
                            </div>
                            <div className="flex items-center gap-1.5 shrink-0">
                              <button
                                onClick={() => handleDownloadSharedDoc(doc)}
                                className="p-1.5 text-[#94A3B8] hover:text-blue-600 hover:bg-blue-50 rounded transition-colors"
                                title="Download"
                              >
                                <Download size={13} />
                              </button>
                              <button
                                onClick={() => handleDeleteSharedDoc(doc)}
                                className="p-1.5 text-[#94A3B8] hover:text-red-500 hover:bg-red-50 rounded transition-colors"
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
                      <div className="px-6 py-10 text-center text-sm text-[#94A3B8]">
                        <BarChart3 size={28} className="mx-auto mb-2 opacity-20" />
                        <p>No reports shared yet.</p>
                        <p className="text-xs mt-1 text-[#CBD5E1]">Go to Reports → Financial Statements → Generate → Share with Client</p>
                      </div>
                    ) : (
                      <div className="divide-y divide-[#F8FAFC]">
                        {sharedReports.map((r) => (
                          <div key={r.id} className="px-4 py-3 flex items-center justify-between gap-4">
                            <div className="min-w-0">
                              <p className="text-sm font-medium text-[#0F172A] truncate">{r.report_label}</p>
                              <p className="text-xs text-[#94A3B8] mt-0.5">
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
                                className="flex items-center gap-1 text-xs text-red-600 hover:text-red-600 px-2 py-1.5 rounded-lg hover:bg-red-50"
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
                        <tr className="border-b border-[#F1F5F9] text-xs text-[#94A3B8]">
                          <th className="px-5 py-3 text-left font-semibold">Form</th>
                          <th className="px-3 py-3 text-left font-semibold">Period</th>
                          <th className="px-3 py-3 text-left font-semibold">Status</th>
                          <th className="px-3 py-3 text-left font-semibold">Filed Date</th>
                          <th className="px-5 py-3 text-left font-semibold">ARN</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#F8FAFC]">
                        {recentFilings.length > 0
                          ? recentFilings.map((c) => (
                              <tr key={c.id} className="hover:bg-[#F8FAFC]">
                                <td className="px-5 py-3 text-sm font-medium text-[#0F172A]">
                                  {c.compliance_type}
                                </td>
                                <td className="px-3 py-3 text-xs text-[#64748B] whitespace-nowrap">
                                  {formatDate(c.period_start)} – {formatDate(c.period_end)}
                                </td>
                                <td className="px-3 py-3">
                                  <Badge className={`text-xs ${FILING_STATUS_COLORS[c.filing_status] ?? "bg-[#F1F5F9] text-[#475569]"}`}>
                                    {c.filing_status}
                                  </Badge>
                                </td>
                                <td className="px-3 py-3 text-xs text-[#64748B] whitespace-nowrap">
                                  {c.filed_date ? formatDate(c.filed_date) : "—"}
                                </td>
                                <td className="px-5 py-3 text-xs font-mono text-[#94A3B8]">
                                  {c.arn_number ?? "—"}
                                </td>
                              </tr>
                            ))
                          : (
                            <tr>
                              <td colSpan={5} className="text-center text-xs text-[#94A3B8] py-8">
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
                    {duesLoading ? (
                      <TransactionListSkeleton rows={3} />
                    ) : (() => {
                      const duesData = apiDues.length > 0 ? apiDues : unpaidInvoices;
                      if (duesData.length === 0) {
                        if (duesFailed) {
                          return (
                            <div className="text-center py-10 space-y-3">
                              <p className="text-sm text-red-600 font-medium">Couldn&apos;t load outstanding dues — the request failed or timed out.</p>
                              <button
                                onClick={() => loadDues(selectedClientId)}
                                className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]"
                              >
                                Retry
                              </button>
                            </div>
                          );
                        }
                        return (
                          <div className="text-center py-10 space-y-2">
                            <Receipt size={32} className="text-gray-200 mx-auto" />
                            <p className="text-sm text-[#94A3B8]">No outstanding dues for this client</p>
                          </div>
                        );
                      }
                      if (apiDues.length > 0) {
                        return apiDues.map((due) => (
                          <div
                            key={due.id}
                            className="flex items-center gap-4 p-3 rounded-lg border border-[#F1F5F9] hover:bg-[#F8FAFC]"
                          >
                            <div className="flex-1">
                              <p className="text-sm font-medium text-[#0F172A]">{due.party_name}</p>
                              <p className="text-xs text-[#64748B] mt-0.5">
                                {formatDate(due.transaction_date)}
                                {due.reference_no ? ` · Ref: ${due.reference_no}` : ""}
                              </p>
                            </div>
                            <span className="text-sm font-semibold text-[#1E293B]">
                              {formatPaise(due.total_paise)}
                            </span>
                            <Badge
                              className={`text-xs ${due.status === "overdue" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"}`}
                            >
                              {due.status}
                            </Badge>
                          </div>
                        ));
                      }
                      return unpaidInvoices.map((t) => (
                        <div
                          key={t.id}
                          className="flex items-center gap-4 p-3 rounded-lg border border-[#F1F5F9] hover:bg-[#F8FAFC]"
                        >
                          <div className="flex-1">
                            <p className="text-sm font-medium text-[#0F172A]">{t.party_name}</p>
                            <p className="text-xs text-[#64748B] mt-0.5">
                              {formatDate(t.transaction_date)}
                              {t.reference_no ? ` · Ref: ${t.reference_no}` : ""}
                            </p>
                          </div>
                          <span className="text-sm font-semibold text-[#1E293B]">
                            {formatPaise(t.total_paise)}
                          </span>
                          <Badge className="text-xs bg-amber-100 text-amber-700">{t.status}</Badge>
                        </div>
                      ));
                    })()}
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
                    {messagesLoading ? (
                      <ListSkeleton rows={3} />
                    ) : messagesFailed ? (
                      <div className="text-center py-10 space-y-2">
                        <p className="text-sm text-red-600 font-medium">Couldn&apos;t load messages.</p>
                        <button onClick={() => loadPortalMessages(selectedClientId)} className="text-xs px-3 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
                      </div>
                    ) : portalMessages.length === 0 ? (
                      <div className="text-center py-10 space-y-2">
                        <MessageSquare size={32} className="text-gray-200 mx-auto" />
                        <p className="text-sm text-[#94A3B8]">No messages yet — send a message to your client below</p>
                      </div>
                    ) : (
                      portalMessages.map((msg) => (
                        <div key={msg.id} className="flex gap-3">
                          <div className="w-7 h-7 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs font-bold shrink-0 mt-0.5">
                            {msg.from_ca ? "CA" : "C"}
                          </div>
                          <div className="flex-1 bg-[#F8FAFC] rounded-lg px-4 py-3">
                            <p className="text-sm text-[#1E293B]">{msg.text}</p>
                            <p className="text-xs text-[#94A3B8] mt-1">{formatDate(msg.created_at)}</p>
                          </div>
                        </div>
                      ))
                    )}
                    <div className="pt-2 border-t border-[#F1F5F9] space-y-2">
                      <textarea
                        rows={2}
                        placeholder="Type a message to send to this client…"
                        value={newMessageText}
                        onChange={(e) => setNewMessageText(e.target.value)}
                        className="w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                      />
                      <div className="flex justify-end">
                        <button
                          onClick={handleSendMessage}
                          disabled={!newMessageText.trim() || sendingMessage}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
                        >
                          <MessageSquare size={12} />
                          {sendingMessage ? "Sending…" : "Send Message"}
                        </button>
                      </div>
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
        <div className="fixed inset-0 bg-[#0F172A]/60 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
            <h3 className="text-base font-semibold text-[#0F172A]">New Document Request</h3>
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-[#475569] mb-1">Title *</label>
                <input
                  type="text"
                  placeholder="e.g. Upload Q4 Bank Statement"
                  value={newRequest.title}
                  onChange={(e) => setNewRequest((p) => ({ ...p, title: e.target.value }))}
                  className="w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  autoFocus
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-[#475569] mb-1">Description</label>
                <textarea
                  placeholder="e.g. For the period Jan–Mar 2026"
                  value={newRequest.description}
                  onChange={(e) => setNewRequest((p) => ({ ...p, description: e.target.value }))}
                  className="w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
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
                <span className="text-sm text-[#334155]">Mark as Urgent</span>
                <AlertTriangle size={14} className="text-amber-500" />
              </label>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => {
                  setShowNewRequestModal(false);
                  setNewRequest({ title: "", description: "", is_urgent: false });
                }}
                className="px-4 py-2 text-sm text-[#475569] border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]"
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
