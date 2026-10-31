"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
  ExternalLink, Copy, CheckCircle, FileText, MessageSquare, Receipt,
  Plus, Trash2, Download, Upload, FolderOpen, AlertTriangle, BarChart3,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { getClients } from "@/lib/data/clients";
import { getComplianceCalendar } from "@/lib/data/compliance";
import { getFirmId } from "@/lib/data/getFirmId";
import { getSupabaseClient } from "@/lib/supabase/client";
import { deleteRowAndConfirm, ROW_NOT_DELETED } from "@/lib/data/deleteRowAndConfirm";
import { api } from "@/lib/api";
import type { ClientDocumentList, ClientNotice, PortalUnreadSummary } from "@/lib/api";
import { arrayOrEmpty, objectOrNull, objectWithLists } from "@/lib/api/shape";
import type { Client } from "@/lib/types";
import type { ComplianceEntry } from "@/lib/data/compliance";
import { formatDate } from "@/lib/services/formatting";
import { formatPaise } from "@/lib/services/formatting";
import { ListSkeleton, TransactionListSkeleton } from "@/components/ui/skeleton";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { toast } from "@/components/ui/use-toast";
import { PageHeader } from "@/components/ui/page-header";

import { Button } from "@/components/ui/button";
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
  pending: "bg-state-attention-surface text-state-attention",
  in_progress: "bg-state-working-surface text-state-working",
  filed: "bg-state-ready-surface text-state-ready",
  overdue: "bg-state-problem-surface text-state-problem",
  na: "bg-ps-muted text-ps-label",
};

interface DocumentRequest {
  id: string;
  title: string;
  description: string | null;
  is_urgent: boolean;
  status: string;
  fulfilled_at: string | null;
  created_at: string;
  due_date?: string | null;
}

/** One sentence for "it was saved" AND "the client was / was not told" — two
 *  facts, and the CA is entitled to both. The words are the server's. */
function describeNotice(saved: string, n: ClientNotice | undefined): { tone: "ok" | "warn"; text: string } {
  if (!n) return { tone: "ok", text: `${saved}.` };
  if (n.emailed > 0) {
    return { tone: "ok", text: `${saved}. The client was emailed (${n.emailed} contact${n.emailed === 1 ? "" : "s"}).` };
  }
  return { tone: "warn", text: `${saved}, but the client was not emailed. ${n.reason ?? ""}`.trim() };
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
  due_date: string;
}

interface PortalMessage {
  id: string;
  firm_id: string;
  client_id: string;
  text: string;
  from_ca: boolean;
  /** Whether the FIRM has opened it. Meaningful for a message the client sent. */
  is_read?: boolean;
  created_at: string;
}

/** One open fee invoice, as `GET /api/portal/dues` returns it (portal_data_service.safe_invoice). The page used to
 *  declare the retired `transactions` shape (party_name, transaction_date, reference_no), none of which the server
 *  sends any more, so every row printed a blank name and date. */
interface ApiDue {
  id: string;
  invoice_no: string | null;
  invoice_date: string | null;
  due_date: string | null;
  total_paise: number;
  paid_paise: number;
  /** What is still owed: the figure a "due" is. */
  outstanding_paise: number;
  status: string;
  /** Derived by the server from the due date and what is still owed; the `status` column never says "overdue". */
  is_overdue: boolean;
  days_overdue: number;
}

interface DuesResponse {
  dues: ApiDue[];
  /** None of the three totals is a number when `available` is false: the fee ledger could not be read, which is not
   *  the same as the client owing nothing. */
  total_outstanding_paise: number | null;
  overdue_paise: number | null;
  overdue_count: number | null;
  /** False when this client has no fee ledger linked. Absent from an older server, which is read as available. */
  available?: boolean;
  /** The server's sentence for the unavailable case. */
  reason?: string | null;
}

/** Shown when an older or newer server says the fee ledger is unavailable and sends no sentence of its own. */
const DUES_UNAVAILABLE_FALLBACK = "Outstanding fees can't be shown here yet: this client has no fee ledger linked.";

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
  const [newRequest, setNewRequest] = useState<NewRequestForm>({ title: "", description: "", is_urgent: false, due_date: "" });
  const [savingRequest, setSavingRequest] = useState(false);
  // A delete is in flight: one at a time, so a second click cannot withdraw the same request twice.
  const [deletingRequest, setDeletingRequest] = useState(false);
  // A shared file is being deleted or opened: one at a time, for the same reason.
  const [docBusy, setDocBusy] = useState(false);

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
  // One action at a time: every button that starts work waits for whichever
  // is already running. Guarding each on its own flag alone let two fire at
  // once, and the second could act on what the first was still changing.
  const actionInFlight = savingRequest || sendingMessage || deletingRequest || docBusy;

  // practice_management-02: the firm-wide count of client messages nobody at the
  // firm has opened, and what the server said about telling the CLIENT. Both are
  // the server's answers; this screen computes neither.
  const [unread, setUnread] = useState<PortalUnreadSummary | null>(null);
  const [notice, setNotice] = useState<{ tone: "ok" | "warn"; text: string } | null>(null);

  // Dues state
  const [apiDues, setApiDues] = useState<ApiDue[]>([]);
  const [duesLoading, setDuesLoading] = useState(false);
  // True when the LAST dues fetch failed (error/timeout) rather than the client
  // genuinely having nothing outstanding. Without this, a failed load renders as
  // "No outstanding dues" — indistinguishable, to the portal viewer, from a
  // paid-up client (audit M17). Mirrors TrialBalance.loadFailed in accounting.
  const [duesFailed, setDuesFailed] = useState(false);
  // The server's sentence when the client's fee ledger could not be read at all (no link). Not a failure to load and not
  // "owes nothing": a third state, so it is kept apart from both (POST-A-245).
  const [duesUnavailable, setDuesUnavailable] = useState<string | null>(null);

  // Load clients list on mount
  useEffect(() => {
    getClients()
      .then((c) => { setClients(c); setClientsFailed(false); })
      .catch(() => { setClients([]); setClientsFailed(true); })
      .finally(() => setClientsLoading(false));
  }, []);

  // The in-app notification for a client's message links here with
  // `?client=<id>&tab=messages`. Read inside an effect: this is a static
  // export, so nothing may touch `window` during render. An unknown tab is
  // ignored and an unknown client simply selects nothing.
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const tab = q.get("tab");
    if (tab && PORTAL_TABS.some((t) => t.id === tab)) setActiveTab(tab as PortalTab);
    const client = q.get("client");
    if (client) setSelectedClientId(client);
  }, []);

  const loadUnread = useCallback(async () => {
    try {
      const res = await api.portal.unreadMessages();
      if (!res.success) throw new Error(res.error ?? "unread");
      const body = objectOrNull<{ unread_total?: number; clients?: unknown }>(res.data);
      setUnread({
        unread_total: Number(body?.unread_total ?? 0),
        clients: arrayOrEmpty<PortalUnreadSummary["clients"][number]>(body?.clients),
      });
    } catch {
      // The count is a convenience over a screen that still works; a failed
      // read must not look like "nobody has written", so it shows nothing.
      setUnread(null);
    }
  }, []);

  useEffect(() => { loadUnread(); }, [loadUnread]);

  // Load client data when a client is selected
  useEffect(() => {
    if (!selectedClientId) {
      setSelectedClient(null);
      setCompliance([]);
      setDocRequests([]);
      setSharedDocs([]);
      setPortalMessages([]);
      setApiDues([]);
      setDuesUnavailable(null);
      return;
    }
    const client = clients.find((c) => c.id === selectedClientId) ?? null;
    setSelectedClient(client);

    setLoading(true);
    getComplianceCalendar(selectedClientId)
      .catch(() => [] as ComplianceEntry[])
      .then((comp) => setCompliance(comp))
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
      // Asked of the server (POST-A-010), which asks the caller's Portal permission and client assignment.
      const firmId = await getFirmId();
      const res = await api.portal.getDocumentRequests(firmId, clientId) as { success?: boolean; data?: unknown };
      if (!res?.success) throw new Error("Failed to load document requests");
      setDocRequests(arrayOrEmpty<DocumentRequest>(res.data));
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
      //
      // The documents come from the server (POST-A-010), which reads every one of the client's, newest first, in pages
      // of its own, after the Documents permission and the client assignment; the shared reports are a separate read.
      const [docsRes, reportsRes] = await Promise.all([
        api.clientDocuments.list(clientId).then(
          (r) => ({ data: r?.success ? objectWithLists<ClientDocumentList>(r.data, "documents") : null, error: !r?.success }),
          () => ({ data: null, error: true })),
        sb.from("shared_reports")
          .select("id, report_label, report_type, financial_year, storage_path, file_name, file_size_bytes, created_at")
          .eq("client_id", clientId)
          .order("created_at", { ascending: false }),
      ]);
      if (docsRes.error || !docsRes.data || reportsRes.error) {
        setSharedFailed(true);
      } else {
        setSharedDocs(arrayOrEmpty<SharedDocument>(docsRes.data.documents));
        setSharedReports(reportsRes.data ?? []);
        setSharedFailed(false);
      }
    } catch {
      setSharedFailed(true);
    } finally {
      setSharedLoading(false);
    }
  }

  // Opening a client's thread IS reading it: the messages the client sent are
  // marked read on the server and the firm-wide count is asked again. Only once
  // they have loaded, and only when there is something unread, so an empty
  // thread makes no write.
  useEffect(() => {
    if (activeTab !== "messages" || !selectedClientId || messagesLoading || messagesFailed) return;
    if (!portalMessages.some((m) => !m.from_ca && m.is_read === false)) return;
    let live = true;
    (async () => {
      try {
        const res = await api.portal.markThreadRead(selectedClientId);
        if (!live || !res.success) return;
        setPortalMessages((prev) => prev.map((m) => (m.from_ca ? m : { ...m, is_read: true })));
        loadUnread();
      } catch { /* the thread stays unread, which is the honest answer */ }
    })();
    return () => { live = false; };
  }, [activeTab, selectedClientId, messagesLoading, messagesFailed, portalMessages, loadUnread]);

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
        setDuesUnavailable(res.data?.available === false ? (res.data.reason ?? DUES_UNAVAILABLE_FALLBACK) : null);
      } else {
        setApiDues([]);
        setDuesFailed(true);
        setDuesUnavailable(null);
      }
    } catch {
      setApiDues([]);
      setDuesFailed(true);
      setDuesUnavailable(null);
    } finally {
      setDuesLoading(false);
    }
  }

  async function handleSendMessage() {
    if (!newMessageText.trim() || !selectedClientId) return;
    setSendingMessage(true);
    try {
      const firmId = await getFirmId();
      const sent = await api.portal.sendMessage({
        firm_id: firmId,
        client_id: selectedClientId,
        text: newMessageText.trim(),
        from_ca: true,
      }) as { success?: boolean; data?: { client_notice?: ClientNotice } };
      setNotice(describeNotice("Message sent", sent?.data?.client_notice));
      setNewMessageText("");
      await loadPortalMessages(selectedClientId);
    } catch (e) {
      toast({ title: e instanceof Error ? e.message : "Failed to send message", variant: "destructive" });
    } finally {
      setSendingMessage(false);
    }
  }

  async function handleCreateRequest() {
    if (!newRequest.title.trim() || !selectedClientId) return;
    setSavingRequest(true);
    try {
      // THROUGH THE API, NOT STRAIGHT OVER POSTGREST. The screen used to insert
      // `document_requests` itself, so rbac() never ran and the server could
      // never tell the client — which is the point of this call (practice_
      // management-02). It did that because the API door named a column the
      // table lacked and failed on every call; migration 450 repaired it.
      const firmId = await getFirmId();
      const res = await api.portal.createDocumentRequest({
        firm_id: firmId,
        client_id: selectedClientId,
        title: newRequest.title.trim(),
        description: newRequest.description.trim() || undefined,
        due_date: newRequest.due_date || undefined,
        is_urgent: newRequest.is_urgent,
      }) as { success?: boolean; error?: string | null; data?: { client_notice?: ClientNotice } };
      if (!res?.success) throw new Error(res?.error ?? "Failed to create request");
      setNotice(describeNotice("Request created", res.data?.client_notice));
      setShowNewRequestModal(false);
      setNewRequest({ title: "", description: "", is_urgent: false, due_date: "" });
      await loadDocRequests(selectedClientId);
    } catch (e) {
      toast({ title: e instanceof Error ? e.message : "Failed to create request", variant: "destructive" });
    } finally {
      setSavingRequest(false);
    }
  }

  async function handleDeleteRequest(id: string) {
    if (!(await confirmDialog({ message: "Delete this document request?", danger: true, confirmLabel: "Delete" }))) return;
    // The line leaves the page only when the server says a row went: the route answers success false for a request
    // that is not the caller's or is already gone, and the browser never deletes the row itself (POST-A-010).
    setDeletingRequest(true);
    try {
      const res = await api.portal.deleteDocumentRequest(id);
      if (!res?.success) { toast({ title: ROW_NOT_DELETED, variant: "destructive" }); return; }
      setDocRequests((prev) => prev.filter((r) => r.id !== id));
    } catch (e) {
      toast({ title: e instanceof Error ? e.message : ROW_NOT_DELETED, variant: "destructive" });
    } finally {
      setDeletingRequest(false);
    }
  }

  async function handleSharedDocUpload(file: File) {
    if (!selectedClientId) return;
    const label = uploadLabel.trim() || file.name;
    setUploadingDoc(true);
    try {
      // The server bounds the file, checks its bytes against its type, names and stores it under the firm and client
      // and writes the record with the signed-in person as the uploader; if the record cannot be written it removes
      // the file again (POST-A-010). The browser neither holds the bucket nor writes the table.
      const form = new FormData();
      form.append("file", file);
      form.append("client_id", selectedClientId);
      form.append("description", label);
      await api.clientDocuments.upload(form);

      setUploadLabel("");
      await loadSharedDocs(selectedClientId);
    } catch (e) {
      toast({ title: e instanceof Error ? e.message : "Upload failed", variant: "destructive" });
    } finally {
      setUploadingDoc(false);
    }
  }

  async function handleDeleteSharedDoc(doc: SharedDocument) {
    if (!(await confirmDialog({ message: `Delete "${doc.description ?? doc.file_name}"?`, danger: true, confirmLabel: "Delete" }))) return;
    // The server removes the file and then the record (Partner only) and refuses, with the reason, when something still
    // points at the record; the line leaves the page only after it has said the record is gone (POST-A-010).
    setDocBusy(true);
    try {
      await api.clientDocuments.remove(doc.id);
      setSharedDocs((prev) => prev.filter((d) => d.id !== doc.id));
    } catch (e) {
      toast({ title: e instanceof Error ? e.message : "This document was not deleted.", variant: "destructive" });
    } finally {
      setDocBusy(false);
    }
  }

  async function handleDownloadSharedDoc(doc: SharedDocument) {
    setDocBusy(true);
    try {
      const res = await api.clientDocuments.downloadUrl(doc.id);
      if (!res?.data?.download_url) throw new Error("Could not generate download link.");
      window.open(res.data.download_url, "_blank");
    } catch (e) {
      toast({ title: e instanceof Error ? e.message : "Could not generate download link.", variant: "destructive" });
    } finally {
      setDocBusy(false);
    }
  }

  async function handleCopyPortalLink() {
    const url = `${window.location.origin}/portal`;
    await navigator.clipboard.writeText(url).catch(() => undefined);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  }

  const recentFilings = compliance.filter((c) => c.filing_status === "filed").slice(0, 8);

  return (
    <div className="p-6 max-w-ps-data mx-auto space-y-6">
      {/* Page Header */}
      <PageHeader
        title="Client Portal Preview"
        subtitle="Manage document requests and shared files for your clients"
        actions={
          <>
            {selectedClient && (
              <button
                onClick={handleCopyPortalLink}
                className="flex items-center gap-2 px-4 py-2 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand-dark transition-colors"
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
          </>
        }
      />

      {notice && (
        <div role="status"
          className={`flex items-start justify-between gap-3 rounded-lg border px-4 py-2.5 text-sm ${
            notice.tone === "ok"
              ? "bg-state-ready-surface border-state-ready-border text-state-ready"
              : "bg-state-attention-surface border-state-attention-border text-state-attention"}`}>
          <span>{notice.text}</span>
          <button onClick={() => setNotice(null)} className="text-xs underline shrink-0">Dismiss</button>
        </div>
      )}

      {/* The firm-wide unread count: who has written, without opening each
          client's tab. Each name opens that client's thread. */}
      {unread && unread.unread_total > 0 && (
        <div className="rounded-lg border border-state-attention-border bg-state-attention-surface px-4 py-3">
          <p className="text-sm font-medium text-state-attention">
            {unread.unread_total} unread client message{unread.unread_total === 1 ? "" : "s"}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {unread.clients.map((c) => (
              <button key={c.client_id}
                onClick={() => { setSelectedClientId(c.client_id); setActiveTab("messages"); }}
                className="rounded-full border border-state-attention-border bg-white px-3 py-1 text-xs text-ps-ink hover:bg-ps-bg">
                {c.client_name ?? "A client"} ({c.unread})
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Client selector */}
      <Card>
        <CardContent className="pt-5 pb-4">
          <div className="flex items-center gap-3">
            <ExternalLink size={16} className="text-ps-hint shrink-0" />
            <div className="flex-1">
              <label htmlFor="client-select" className="block text-xs font-medium text-ps-label mb-1">
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
        <div className="flex flex-col items-center justify-center py-20 text-ps-hint">
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
              <h2 className="text-xl font-bold text-ps-ink">{selectedClient.client_name}</h2>
              <p className="text-sm text-ps-label mt-1">Manage documents and requests for this client</p>
            </div>
            <div className="mt-4 flex flex-wrap gap-4 text-sm">
              {selectedClient.gstin && (
                <div>
                  <span className="text-xs text-ps-hint block">GSTIN</span>
                  <span className="font-mono font-semibold text-ps-ink">{selectedClient.gstin}</span>
                </div>
              )}
              <div>
                <span className="text-xs text-ps-hint block">PAN</span>
                <span className="font-mono font-semibold text-ps-ink">{selectedClient.pan}</span>
              </div>
              {selectedClient.entity_type && (
                <div>
                  <span className="text-xs text-ps-hint block">Entity Type</span>
                  <span className="font-semibold text-ps-ink capitalize">
                    {selectedClient.entity_type.replace(/_/g, " ")}
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Tabs */}
          <div className="flex gap-1 border-b border-ps-border overflow-x-auto">
            {PORTAL_TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                  activeTab === tab.id
                    ? "border-brand text-blue-700"
                    : "border-transparent text-ps-label hover:text-ps-body"
                }`}
              >
                <tab.icon size={14} />
                {tab.label}
                {tab.id === "messages" && (() => {
                  const mine = unread?.clients.find((c) => c.client_id === selectedClientId)?.unread ?? 0;
                  return mine > 0 ? (
                    <span className="ml-1 rounded-full bg-brand px-1.5 text-3xs font-semibold text-white">{mine}</span>
                  ) : null;
                })()}
              </button>
            ))}
          </div>

          {loading && (
            <div className="text-center py-8 text-sm text-ps-hint animate-pulse">
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
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-brand text-white text-xs font-medium rounded-lg hover:bg-brand-dark transition-colors"
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
                        <button onClick={() => loadDocRequests(selectedClientId)} disabled={requestsLoading} className="text-xs px-3 py-1 border border-ps-border rounded hover:bg-ps-bg text-ps-body disabled:opacity-50">Retry</button>
                      </div>
                    ) : docRequests.length === 0 ? (
                      <div className="text-center py-10 space-y-2">
                        <FileText size={32} className="text-gray-200 mx-auto" />
                        <p className="text-sm text-ps-hint">
                          No document requests yet — click New Request to ask your client for files
                        </p>
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {docRequests.map((req) => (
                          <div
                            key={req.id}
                            className="flex items-start gap-3 p-3 rounded-lg border border-ps-border hover:bg-ps-bg"
                          >
                            <div className="w-8 h-8 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center shrink-0 mt-0.5">
                              <FileText size={14} />
                            </div>
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-medium text-ps-ink">{req.title}</p>
                              {req.description && (
                                <p className="text-xs text-ps-label mt-0.5">{req.description}</p>
                              )}
                              <p className="text-xs text-ps-hint mt-1">
                                {formatDate(req.created_at)}
                                {req.due_date ? ` · needed by ${formatDate(req.due_date)}` : ""}
                              </p>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                              {req.is_urgent && (
                                <Badge className="text-xs bg-state-attention-surface text-state-attention">
                                  <AlertTriangle size={10} className="mr-1" /> Urgent
                                </Badge>
                              )}
                              <Badge
                                className={`text-xs ${
                                  req.status === "fulfilled"
                                    ? "bg-green-100 text-green-700"
                                    : "bg-ps-muted text-ps-label"
                                }`}
                              >
                                {req.status === "fulfilled" ? "Fulfilled" : "Pending"}
                              </Badge>
                              <button
                                onClick={() => handleDeleteRequest(req.id)}
                                disabled={actionInFlight}
                                className="p-1.5 text-ps-hint hover:text-state-problem hover:bg-state-problem-hover rounded transition-colors disabled:opacity-50"
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
                      <span className="text-xs text-ps-hint font-normal ml-1">(CA → Client)</span>
                    </CardTitle>
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        placeholder="Label (optional)"
                        value={uploadLabel}
                        onChange={(e) => setUploadLabel(e.target.value)}
                        className="text-xs px-2 py-1.5 border border-ps-border rounded-md focus:outline-none focus:ring-2 focus:ring-brand w-36"
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
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-brand text-white text-xs font-medium rounded-lg hover:bg-brand-dark transition-colors disabled:opacity-60"
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
                        <button onClick={() => loadSharedDocs(selectedClientId)} disabled={sharedLoading} className="text-xs px-3 py-1 border border-ps-border rounded hover:bg-ps-bg text-ps-body disabled:opacity-50">Retry</button>
                      </div>
                    ) : sharedDocs.length === 0 ? (
                      <div className="text-center py-10 space-y-2">
                        <FolderOpen size={32} className="text-gray-200 mx-auto" />
                        <p className="text-sm text-ps-hint">
                          No documents shared yet — upload returns, notices, and certificates for this client
                        </p>
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {sharedDocs.map((doc) => (
                          <div
                            key={doc.id}
                            className="flex items-center gap-3 p-3 rounded-lg border border-ps-border hover:bg-ps-bg"
                          >
                            <div className="w-8 h-8 rounded-full bg-blue-50 text-blue-600 flex items-center justify-center shrink-0">
                              <FolderOpen size={14} />
                            </div>
                            <div className="flex-1 min-w-0">
                              {/* description is the user-supplied label and is nullable; the file name
                                  is the only always-present identifier. */}
                              <p className="text-sm font-medium text-ps-ink truncate">{doc.description ?? doc.file_name}</p>
                              <p className="text-xs text-ps-hint mt-0.5">
                                {doc.file_name}
                                {doc.file_size ? ` · ${formatFileSize(doc.file_size)}` : ""}
                                {" · "}{formatDate(doc.created_at)}
                              </p>
                            </div>
                            <div className="flex items-center gap-1.5 shrink-0">
                              <button
                                onClick={() => handleDownloadSharedDoc(doc)}
                                disabled={actionInFlight}
                                className="p-1.5 text-ps-hint hover:text-blue-600 hover:bg-blue-50 rounded transition-colors disabled:opacity-50"
                                title="Download"
                              >
                                <Download size={13} />
                              </button>
                              <button
                                onClick={() => handleDeleteSharedDoc(doc)}
                                disabled={actionInFlight}
                                className="p-1.5 text-ps-hint hover:text-state-problem hover:bg-state-problem-hover rounded transition-colors disabled:opacity-50"
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
                      <div className="px-6 py-10 text-center text-sm text-ps-hint">
                        <BarChart3 size={28} className="mx-auto mb-2 opacity-20" />
                        <p>No reports shared yet.</p>
                        <p className="text-xs mt-1 text-ps-disabled">Go to Reports → Financial Statements → Generate → Share with Client</p>
                      </div>
                    ) : (
                      <div className="divide-y divide-ps-border">
                        {sharedReports.map((r) => (
                          <div key={r.id} className="px-4 py-3 flex items-center justify-between gap-4">
                            <div className="min-w-0">
                              <p className="text-sm font-medium text-ps-ink truncate">{r.report_label}</p>
                              <p className="text-xs text-ps-hint mt-0.5">
                                FY {r.financial_year}
                                {r.file_size_bytes ? ` · ${formatFileSize(r.file_size_bytes)}` : ""}
                                {" · "}{formatDate(r.created_at)}
                              </p>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                              <button
                                disabled={actionInFlight}
                                onClick={async () => {
                                  setDocBusy(true);
                                  try {
                                    const res = await api.accounting.sharedReportUrl(r.id);
                                    if (!res?.data?.download_url) throw new Error("Could not generate download link.");
                                    window.open(res.data.download_url, "_blank");
                                  } catch (e) {
                                    toast({ title: e instanceof Error ? e.message : "Could not generate download link.", variant: "destructive" });
                                  } finally {
                                    setDocBusy(false);
                                  }
                                }}
                                className="flex items-center gap-1.5 text-xs bg-blue-50 text-blue-700 px-3 py-1.5 rounded-lg hover:bg-blue-100"
                              >
                                <Download size={12} /> Download
                              </button>
                              <Button variant="plain" size="none"
                                onClick={async () => {
                                  if (!(await confirmDialog({ message: "Remove this shared report?", danger: true, confirmLabel: "Remove" }))) return;
                                  const out = await deleteRowAndConfirm(getSupabaseClient(), "shared_reports", r.id);
                                  if (!out.deleted) { toast({ title: out.message, variant: "destructive" }); return; }
                                  setSharedReports((prev) => prev.filter((x) => x.id !== r.id));
                                }}
                                className="flex items-center gap-1 text-xs text-red-600 hover:text-state-problem px-2 py-1.5 rounded-lg hover:bg-state-problem-hover"
                              >
                                <Trash2 size={12} />
                              </Button>
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
                        <tr className="border-b border-ps-border text-xs text-ps-hint">
                          <th className="px-5 py-3 text-left font-semibold">Form</th>
                          <th className="px-3 py-3 text-left font-semibold">Period</th>
                          <th className="px-3 py-3 text-left font-semibold">Status</th>
                          <th className="px-3 py-3 text-left font-semibold">Filed Date</th>
                          <th className="px-5 py-3 text-left font-semibold">ARN</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-ps-border">
                        {recentFilings.length > 0
                          ? recentFilings.map((c) => (
                              <tr key={c.id} className="hover:bg-ps-bg">
                                <td className="px-5 py-3 text-sm font-medium text-ps-ink">
                                  {c.compliance_type}
                                </td>
                                <td className="px-3 py-3 text-xs text-ps-label whitespace-nowrap">
                                  {formatDate(c.period_start)} – {formatDate(c.period_end)}
                                </td>
                                <td className="px-3 py-3">
                                  <Badge className={`text-xs ${FILING_STATUS_COLORS[c.filing_status] ?? "bg-ps-muted text-ps-label"}`}>
                                    {c.filing_status}
                                  </Badge>
                                </td>
                                <td className="px-3 py-3 text-xs text-ps-label whitespace-nowrap">
                                  {c.filed_date ? formatDate(c.filed_date) : "—"}
                                </td>
                                <td className="px-5 py-3 text-xs font-mono text-ps-hint">
                                  {c.arn_number ?? "—"}
                                </td>
                              </tr>
                            ))
                          : (
                            <tr>
                              <td colSpan={5} className="text-center text-xs text-ps-hint py-8">
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
                      // The dues are the server's canonical answer and nothing else. A fallback to the client's whole
                      // transaction feed used to fill this panel whenever the answer was empty, so a client who owed
                      // nothing was shown every paid sale and purchase as "outstanding".
                      if (apiDues.length === 0) {
                        if (duesUnavailable !== null) {
                          return (
                            <div className="text-center py-10 space-y-2">
                              <Receipt size={32} className="text-gray-200 mx-auto" />
                              <p className="text-sm text-ps-label">{duesUnavailable}</p>
                            </div>
                          );
                        }
                        if (duesFailed) {
                          return (
                            <div className="text-center py-10 space-y-3">
                              <p className="text-sm text-red-600 font-medium">Couldn&apos;t load outstanding dues — the request failed or timed out.</p>
                              <button disabled={duesLoading}
                                onClick={() => loadDues(selectedClientId)}
                                className="disabled:opacity-40 text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg text-ps-body"
                              >
                                Retry
                              </button>
                            </div>
                          );
                        }
                        return (
                          <div className="text-center py-10 space-y-2">
                            <Receipt size={32} className="text-gray-200 mx-auto" />
                            <p className="text-sm text-ps-hint">No outstanding dues for this client</p>
                          </div>
                        );
                      }
                      return apiDues.map((due) => (
                        <div
                          key={due.id}
                          className="flex items-center gap-4 p-3 rounded-lg border border-ps-border hover:bg-ps-bg"
                        >
                          <div className="flex-1">
                            <p className="text-sm font-medium text-ps-ink">{due.invoice_no ?? "Fee invoice"}</p>
                            <p className="text-xs text-ps-label mt-0.5">
                              {due.invoice_date ? `Issued ${formatDate(due.invoice_date)}` : "Issue date not recorded"}
                              {due.due_date ? ` · Due ${formatDate(due.due_date)}` : ""}
                              {due.is_overdue && due.days_overdue > 0 ? ` · ${due.days_overdue} ${due.days_overdue === 1 ? "day" : "days"} overdue` : ""}
                            </p>
                          </div>
                          <div className="text-right">
                            <span className="text-sm font-semibold text-ps-ink">{formatPaise(due.outstanding_paise)}</span>
                            {due.outstanding_paise !== due.total_paise && (
                              <p className="text-xs text-ps-hint">of {formatPaise(due.total_paise)}</p>
                            )}
                          </div>
                          <Badge
                            className={`text-xs ${due.is_overdue ? "bg-state-problem-surface text-state-problem" : "bg-state-attention-surface text-state-attention"}`}
                          >
                            {due.is_overdue ? "overdue" : due.status}
                          </Badge>
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
                        <button disabled={messagesLoading} onClick={() => loadPortalMessages(selectedClientId)} className="disabled:opacity-40 text-xs px-3 py-1 border border-ps-border rounded hover:bg-ps-bg text-ps-body">Retry</button>
                      </div>
                    ) : portalMessages.length === 0 ? (
                      <div className="text-center py-10 space-y-2">
                        <MessageSquare size={32} className="text-gray-200 mx-auto" />
                        <p className="text-sm text-ps-hint">No messages yet — send a message to your client below</p>
                      </div>
                    ) : (
                      portalMessages.map((msg) => (
                        <div key={msg.id} className="flex gap-3">
                          <div className="w-7 h-7 rounded-full bg-brand text-white flex items-center justify-center text-xs font-bold shrink-0 mt-0.5">
                            {msg.from_ca ? "CA" : "C"}
                          </div>
                          <div className="flex-1 bg-ps-bg rounded-lg px-4 py-3">
                            <p className="text-sm text-ps-ink">{msg.text}</p>
                            <p className="text-xs text-ps-hint mt-1">{formatDate(msg.created_at)}</p>
                          </div>
                        </div>
                      ))
                    )}
                    <div className="pt-2 border-t border-ps-border space-y-2">
                      <textarea
                        rows={2}
                        placeholder="Type a message to send to this client…"
                        value={newMessageText}
                        onChange={(e) => setNewMessageText(e.target.value)}
                        className="w-full px-3 py-2 text-sm border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand resize-none"
                      />
                      <div className="flex justify-end">
                        <button
                          onClick={handleSendMessage}
                          disabled={actionInFlight || !newMessageText.trim()}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-brand text-white text-xs font-medium rounded-lg hover:bg-brand-dark disabled:opacity-50 transition-colors"
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
        <div className="fixed inset-0 bg-brand-dark/60 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
            <h3 className="text-base font-semibold text-ps-ink">New Document Request</h3>
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-ps-label mb-1">Title *</label>
                <input
                  type="text"
                  placeholder="e.g. Upload Q4 Bank Statement"
                  value={newRequest.title}
                  onChange={(e) => setNewRequest((p) => ({ ...p, title: e.target.value }))}
                  className="w-full px-3 py-2 text-sm border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand"
                  autoFocus
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-ps-label mb-1">Description</label>
                <textarea
                  placeholder="e.g. For the period Jan–Mar 2026"
                  value={newRequest.description}
                  onChange={(e) => setNewRequest((p) => ({ ...p, description: e.target.value }))}
                  className="w-full px-3 py-2 text-sm border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand resize-none"
                  rows={3}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-ps-label mb-1">Needed by</label>
                <input
                  type="date"
                  value={newRequest.due_date}
                  onChange={(e) => setNewRequest((p) => ({ ...p, due_date: e.target.value }))}
                  className="w-full px-3 py-2 text-sm border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand"
                />
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={newRequest.is_urgent}
                  onChange={(e) => setNewRequest((p) => ({ ...p, is_urgent: e.target.checked }))}
                  className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-brand"
                />
                <span className="text-sm text-ps-body">Mark as Urgent</span>
                <AlertTriangle size={14} className="text-amber-500" />
              </label>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => {
                  setShowNewRequestModal(false);
                  setNewRequest({ title: "", description: "", is_urgent: false, due_date: "" });
                }}
                className="px-4 py-2 text-sm text-ps-label border border-ps-border rounded-lg hover:bg-ps-bg"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateRequest}
                disabled={actionInFlight || !newRequest.title.trim()}
                className="px-4 py-2 text-sm bg-brand text-white rounded-lg hover:bg-brand-dark disabled:opacity-50 font-medium"
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
