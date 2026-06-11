"use client";

import { useState, useEffect, useRef } from "react";
import {
  Building2, Mail, Phone, MapPin, Calendar, FileText, Clock,
  ChevronRight, CheckCircle, AlertTriangle, Globe, Copy, X,
  Upload, Download, Trash2, FolderOpen, Sparkles,
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

type TabId = "overview" | "compliance" | "accounts" | "documents" | "tasks" | "ai_insights";
type ComplianceSubTab = "all" | "gst" | "tds" | "income_tax" | "mca";
type AccountsSubTab = "transactions" | "bank_statements";

const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "compliance", label: "Compliance" },
  { id: "accounts", label: "Accounts" },
  { id: "documents", label: "Documents" },
  { id: "tasks", label: "Tasks" },
  { id: "ai_insights", label: "AI Insights" },
];

interface ClientDocument {
  id: string;
  file_name: string;
  label: string;
  storage_path: string;
  file_size_bytes: number | null;
  mime_type: string | null;
  created_at: string;
  version: number | null;
  parent_document_id: string | null;
}

const TASK_STATUS_COLORS: Record<string, string> = {
  todo: "bg-[#F1F5F9] text-[#475569]",
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
  na: "bg-[#F1F5F9] text-[#64748B]",
};

function LoadingSkeleton() {
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6 animate-pulse">
      <div className="h-8 bg-white/[0.08] rounded w-64" />
      <div className="grid grid-cols-5 gap-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-20 bg-[#F1F5F9] rounded-lg" />
        ))}
      </div>
      <div className="h-64 bg-[#F1F5F9] rounded-xl" />
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
  const [complianceSubTab, setComplianceSubTab] = useState<ComplianceSubTab>("all");
  const [accountsSubTab, setAccountsSubTab] = useState<AccountsSubTab>("transactions");
  const [markFiled, setMarkFiled] = useState<MarkFiledForm | null>(null);
  const [filingLoading, setFilingLoading] = useState(false);
  const [portal, setPortal] = useState<PortalState | null>(null);
  const [showPortalModal, setShowPortalModal] = useState(false);
  const [portalLoading, setPortalLoading] = useState(false);
  const [showPortalInviteModal, setShowPortalInviteModal] = useState(false);
  const [portalInviteEmail, setPortalInviteEmail] = useState("");
  const [portalInviteSent, setPortalInviteSent] = useState(false);
  const [portalInviteError, setPortalInviteError] = useState<string | null>(null);

  // Documents state
  const [documents, setDocuments] = useState<ClientDocument[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadLabel, setUploadLabel] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [deletingDocId, setDeletingDocId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Version control state
  const [versionPromptDoc, setVersionPromptDoc] = useState<ClientDocument | null>(null);
  const [showVersionHistory, setShowVersionHistory] = useState<string | null>(null);
  const [versionHistory, setVersionHistory] = useState<ClientDocument[]>([]);

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

  function handleInviteToPortal() {
    // Pre-fill email from client record if available
    setPortalInviteEmail((client as (typeof client & { email?: string }) | null)?.email ?? "");
    setPortalInviteSent(false);
    setPortalInviteError(null);
    setShowPortalInviteModal(true);
  }

  async function handleSendPortalInvite() {
    if (!id || !portalInviteEmail.trim()) return;
    setPortalLoading(true);
    setPortalInviteError(null);
    try {
      const { getSupabaseClient } = await import("@/lib/supabase/client");
      const supabase = getSupabaseClient();

      // Send magic link with client ID in redirect URL
      const portalUrl =
        (typeof window !== "undefined" ? window.location.origin : "") +
        "/portal?client=" +
        encodeURIComponent(id);
      const { error: otpErr } = await supabase.auth.signInWithOtp({
        email: portalInviteEmail.trim(),
        options: { emailRedirectTo: portalUrl },
      });
      if (otpErr) throw new Error(otpErr.message);

      // Update client record
      await supabase
        .from("clients")
        .update({ portal_enabled: true, portal_invited_at: new Date().toISOString() })
        .eq("id", id);
      setPortal({ enabled: true, invitedAt: new Date().toISOString() });
      setPortalInviteSent(true);
    } catch (err) {
      setPortalInviteError(err instanceof Error ? err.message : "Failed to send invite");
    } finally {
      setPortalLoading(false);
    }
  }

  async function loadDocuments() {
    if (!id) return;
    setDocsLoading(true);
    try {
      const { getSupabaseClient } = await import("@/lib/supabase/client");
      const supabase = getSupabaseClient();
      const { data, error: err } = await supabase
        .from("client_documents")
        .select("id, file_name, label, storage_path, file_size_bytes, mime_type, created_at, version, parent_document_id")
        .eq("client_id", id)
        .order("created_at", { ascending: false });
      if (err) throw new Error(err.message);
      setDocuments(data ?? []);
    } catch (e) {
      console.error("loadDocuments:", e);
    } finally {
      setDocsLoading(false);
    }
  }

  useEffect(() => {
    if (activeTab === "documents" && id) loadDocuments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, id]);

  async function handleUploadDocument(asNewVersion: boolean = false, parentDoc: ClientDocument | null = null) {
    if (!uploadFile || !uploadLabel.trim() || !id) return;
    if (uploadFile.size > 50 * 1024 * 1024) {
      setUploadError("File must be under 50 MB");
      return;
    }

    // Check for existing document with same label (version control)
    if (!asNewVersion && !parentDoc) {
      const existing = documents.find(d => d.label.toLowerCase() === uploadLabel.trim().toLowerCase() && !d.parent_document_id);
      if (existing) {
        setVersionPromptDoc(existing);
        return;
      }
    }

    setUploading(true);
    setUploadError(null);
    try {
      const { getSupabaseClient } = await import("@/lib/supabase/client");
      const { getFirmId } = await import("@/lib/data/getFirmId");
      const supabase = getSupabaseClient();
      const firmId = await getFirmId();

      // Sanitize filename
      const sanitized = uploadFile.name.replace(/[^a-zA-Z0-9._-]/g, "_");
      const uuid = crypto.randomUUID();
      const storagePath = `${firmId}/${id}/${uuid}-${sanitized}`;

      const { error: storageErr } = await supabase.storage
        .from("Documents")
        .upload(storagePath, uploadFile, { contentType: uploadFile.type, upsert: false });
      if (storageErr) throw new Error(storageErr.message);

      // Compute version number — integer arithmetic
      const versionNum = parentDoc ? (parentDoc.version ?? 1) + 1 : 1;

      const { error: dbErr } = await supabase.from("client_documents").insert({
        firm_id: firmId,
        client_id: id,
        file_name: uploadFile.name,
        label: uploadLabel.trim(),
        storage_path: storagePath,
        file_size_bytes: uploadFile.size,
        mime_type: uploadFile.type || null,
        version: versionNum,
        parent_document_id: parentDoc?.id ?? null,
      });
      if (dbErr) {
        // Rollback storage upload on DB failure
        await supabase.storage.from("Documents").remove([storagePath]);
        throw new Error(dbErr.message);
      }

      setShowUploadModal(false);
      setUploadFile(null);
      setUploadLabel("");
      setVersionPromptDoc(null);
      await loadDocuments();
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  async function handleViewVersionHistory(label: string) {
    const { getSupabaseClient } = await import("@/lib/supabase/client");
    const supabase = getSupabaseClient();
    const { data } = await supabase
      .from("client_documents")
      .select("id, file_name, label, storage_path, file_size_bytes, mime_type, created_at, version, parent_document_id")
      .eq("client_id", id)
      .ilike("label", label)
      .order("version", { ascending: true });
    setVersionHistory(data ?? []);
    setShowVersionHistory(label);
  }

  async function handleDownloadDocument(doc: ClientDocument) {
    try {
      const { getSupabaseClient } = await import("@/lib/supabase/client");
      const supabase = getSupabaseClient();
      const { data, error: err } = await supabase.storage
        .from("Documents")
        .createSignedUrl(doc.storage_path, 3600); // 1 hour expiry
      if (err) throw new Error(err.message);
      window.open(data.signedUrl, "_blank");
    } catch (e) {
      alert(e instanceof Error ? e.message : "Could not generate download link");
    }
  }

  async function handleDeleteDocument(doc: ClientDocument) {
    if (!confirm(`Delete "${doc.label}" (${doc.file_name})?`)) return;
    setDeletingDocId(doc.id);
    try {
      const { getSupabaseClient } = await import("@/lib/supabase/client");
      const supabase = getSupabaseClient();
      await supabase.storage.from("Documents").remove([doc.storage_path]);
      const { error: dbErr } = await supabase
        .from("client_documents")
        .delete()
        .eq("id", doc.id);
      if (dbErr) throw new Error(dbErr.message);
      setDocuments(prev => prev.filter(d => d.id !== doc.id));
    } catch (e) {
      alert(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeletingDocId(null);
    }
  }

  function formatFileSize(bytes: number | null): string {
    if (bytes === null) return "—";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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
          <div className="flex items-center gap-2 text-sm text-[#64748B] mb-1">
            <span>Clients</span>
            <ChevronRight size={14} />
            <span className="text-[#0F172A] font-medium">{client.client_name}</span>
          </div>
          <h1 className="text-2xl font-bold text-[#0F172A]">{client.client_name}</h1>
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
        <div className={`rounded-lg px-4 py-3 ${pendingFilings > 0 ? "bg-amber-50 text-amber-800" : "bg-[#F1F5F9] text-[#475569]"}`}>
          <p className="text-2xl font-bold">{pendingFilings}</p>
          <p className="text-xs mt-0.5 opacity-80">Pending Filings</p>
        </div>
        <div className="rounded-lg bg-purple-50 text-purple-800 px-4 py-3">
          <p className="text-2xl font-bold">{invoicesThisMonth}</p>
          <p className="text-xs mt-0.5 opacity-80">Invoices This Month</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[#F1F5F9]">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.id
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-[#64748B] hover:text-[#334155]"
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
                <p className="text-xs text-[#64748B]">PAN</p>
                <p className="font-mono font-medium">{client.pan}</p>
              </div>
              {client.gstin && (
                <div>
                  <p className="text-xs text-[#64748B]">GSTIN</p>
                  <p className="font-mono font-medium">{client.gstin}</p>
                </div>
              )}
              {client.mobile && (
                <div className="flex items-center gap-2 text-[#334155]">
                  <Phone size={13} /><span>{client.mobile}</span>
                </div>
              )}
              {client.email && (
                <div className="flex items-center gap-2 text-[#334155]">
                  <Mail size={13} /><span className="truncate">{client.email}</span>
                </div>
              )}
              {client.city && (
                <div className="flex items-center gap-2 text-[#334155]">
                  <MapPin size={13} />
                  <span>{client.city}{client.state ? `, ${client.state}` : ""}{client.pincode ? ` — ${client.pincode}` : ""}</span>
                </div>
              )}
              <div className="flex items-center gap-2 text-[#334155]">
                <Calendar size={13} />
                <span>GST filing: {client.gst_filing_frequency}</span>
              </div>
              {client.notes && (
                <div>
                  <p className="text-xs text-[#64748B]">Notes</p>
                  <p className="text-xs text-[#334155]">{client.notes}</p>
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
                  <p className="text-sm text-[#94A3B8] text-center py-4">No tasks</p>
                ) : (
                  <div className="space-y-2">
                    {tasks.slice(0, 5).map(t => (
                      <div key={t.id} className="flex items-center gap-3 py-2 border-b border-gray-50 last:border-0">
                        <div className="flex-1">
                          <p className="text-sm font-medium text-[#0F172A]">{t.title}</p>
                          {t.due_date && <p className="text-xs text-[#64748B]">Due: {formatDate(t.due_date)}</p>}
                        </div>
                        <Badge className={`text-xs ${TASK_STATUS_COLORS[t.status] ?? "bg-[#F1F5F9] text-[#475569]"}`}>
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
                  <p className="text-sm text-[#94A3B8] text-center py-4">No upcoming filings</p>
                ) : (
                  <div className="space-y-2">
                    {compliance.filter(c => c.filing_status !== "filed" && c.due_date >= today).slice(0, 5).map(c => (
                      <div key={c.id} className="flex items-center gap-3 py-2 border-b border-gray-50 last:border-0">
                        <div className="flex-1">
                          <p className="text-sm font-medium text-[#0F172A]">{c.compliance_type}</p>
                          <p className="text-xs text-[#64748B]">Due: {formatDate(c.due_date)}</p>
                        </div>
                        <Badge className={`text-xs ${FILING_STATUS_COLORS[c.filing_status] ?? "bg-[#F1F5F9] text-[#475569]"}`}>
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
              <p className="text-sm text-[#94A3B8] text-center py-8">No tasks for this client</p>
            ) : (
              <div className="divide-y divide-[#F8FAFC]">
                {tasks.map(t => (
                  <div key={t.id} className="flex items-center gap-4 py-3">
                    <div className="flex-1">
                      <p className="text-sm font-medium text-[#0F172A]">{t.title}</p>
                      {t.description && <p className="text-xs text-[#64748B] mt-0.5">{t.description}</p>}
                    </div>
                    {t.due_date && (
                      <p className={`text-xs shrink-0 ${t.due_date < today && t.status !== "completed" ? "text-red-600 font-medium" : "text-[#64748B]"}`}>
                        {formatDate(t.due_date)}
                      </p>
                    )}
                    <Badge className={`text-xs shrink-0 ${TASK_STATUS_COLORS[t.status] ?? "bg-[#F1F5F9] text-[#475569]"}`}>
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
          {/* Compliance sub-tabs */}
          <div className="flex gap-0.5 bg-[#F8FAFC] rounded-lg p-1 w-fit">
            {(
              [
                { id: "all", label: "All" },
                { id: "gst", label: "GST" },
                { id: "tds", label: "TDS" },
                { id: "income_tax", label: "Income Tax" },
                { id: "mca", label: "MCA" },
              ] as { id: ComplianceSubTab; label: string }[]
            ).map((sub) => (
              <button
                key={sub.id}
                onClick={() => setComplianceSubTab(sub.id)}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  complianceSubTab === sub.id
                    ? "bg-white text-[#0F172A] shadow-sm"
                    : "text-[#64748B] hover:text-[#334155]"
                }`}
              >
                {sub.label}
              </button>
            ))}
          </div>

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
                    className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-md hover:bg-[#F1F5F9]"
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
                  <tr className="border-b border-[#F1F5F9] text-xs text-[#94A3B8]">
                    <th className="px-5 py-3 text-left font-semibold">Type</th>
                    <th className="px-3 py-3 text-left font-semibold">Period</th>
                    <th className="px-3 py-3 text-left font-semibold">Due Date</th>
                    <th className="px-3 py-3 text-left font-semibold">Status</th>
                    <th className="px-3 py-3 text-left font-semibold">ARN</th>
                    <th className="px-5 py-3 text-left font-semibold">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F8FAFC]">
                  {compliance.filter(c => {
                    if (complianceSubTab === "all") return true;
                    if (complianceSubTab === "gst") return /GSTR/i.test(c.compliance_type);
                    if (complianceSubTab === "tds") return /TDS|24Q|26Q/i.test(c.compliance_type);
                    if (complianceSubTab === "income_tax") return /ITR|ADVANCE_TAX/i.test(c.compliance_type);
                    if (complianceSubTab === "mca") return /MCA|ROC|DIR/i.test(c.compliance_type);
                    return true;
                  }).map(c => (
                    <tr key={c.id} className="hover:bg-[#F8FAFC]">
                      <td className="px-5 py-3 text-sm font-medium text-[#0F172A]">{c.compliance_type}</td>
                      <td className="px-3 py-3 text-xs text-[#64748B]">
                        {formatDate(c.period_start)} – {formatDate(c.period_end)}
                      </td>
                      <td className={`px-3 py-3 text-xs whitespace-nowrap ${c.due_date < today && c.filing_status !== "filed" ? "text-red-600 font-medium" : "text-[#475569]"}`}>
                        {formatDate(c.due_date)}
                      </td>
                      <td className="px-3 py-3">
                        <Badge className={`text-xs ${FILING_STATUS_COLORS[c.filing_status] ?? "bg-[#F1F5F9] text-[#475569]"}`}>
                          {c.filing_status}
                        </Badge>
                      </td>
                      <td className="px-3 py-3 text-xs text-[#64748B] font-mono">{c.arn_number ?? "—"}</td>
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
                <div className="text-center py-8 text-sm text-[#94A3B8]">No compliance deadlines found</div>
              )}
            </div>
          </Card>
        </div>
      )}

      {/* Accounts tab */}
      {activeTab === "accounts" && (
        <div className="space-y-4">
          <div className="flex gap-0.5 bg-[#F8FAFC] rounded-lg p-1 w-fit">
            {(
              [
                { id: "transactions", label: "Transactions" },
                { id: "bank_statements", label: "Bank Statements" },
              ] as { id: AccountsSubTab; label: string }[]
            ).map((sub) => (
              <button
                key={sub.id}
                onClick={() => setAccountsSubTab(sub.id)}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  accountsSubTab === sub.id
                    ? "bg-white text-[#0F172A] shadow-sm"
                    : "text-[#64748B] hover:text-[#334155]"
                }`}
              >
                {sub.label}
              </button>
            ))}
          </div>

          {accountsSubTab === "transactions" && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <FileText size={15} /> Transactions ({transactions.length})
                </CardTitle>
              </CardHeader>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[#F1F5F9] text-xs text-[#94A3B8]">
                      <th className="px-5 py-3 text-left font-semibold">Date</th>
                      <th className="px-3 py-3 text-left font-semibold">Type</th>
                      <th className="px-3 py-3 text-left font-semibold">Party</th>
                      <th className="px-3 py-3 text-left font-semibold">Ref</th>
                      <th className="px-3 py-3 text-right font-semibold">Amount</th>
                      <th className="px-5 py-3 text-left font-semibold">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F8FAFC]">
                    {transactions.map(t => (
                      <tr key={t.id} className="hover:bg-[#F8FAFC]">
                        <td className="px-5 py-3 text-xs text-[#475569] whitespace-nowrap">{formatDate(t.transaction_date)}</td>
                        <td className="px-3 py-3 text-xs text-[#475569]">{t.transaction_type.replace(/_/g, " ")}</td>
                        <td className="px-3 py-3 text-sm font-medium text-[#0F172A]">{t.party_name}</td>
                        <td className="px-3 py-3 text-xs text-[#64748B] font-mono">{t.reference_no ?? "—"}</td>
                        <td className="px-3 py-3 text-sm text-right tabular-nums text-[#334155]">{formatPaise(t.total_paise)}</td>
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
                  <div className="text-center py-8 text-sm text-[#94A3B8]">No transactions found</div>
                )}
              </div>
            </Card>
          )}

          {accountsSubTab === "bank_statements" && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Bank Statements ({bankStatements.length})</CardTitle>
              </CardHeader>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[#F1F5F9] text-xs text-[#94A3B8]">
                      <th className="px-5 py-3 text-left font-semibold">Bank</th>
                      <th className="px-3 py-3 text-left font-semibold">Account</th>
                      <th className="px-3 py-3 text-left font-semibold">Period</th>
                      <th className="px-3 py-3 text-right font-semibold">Debits</th>
                      <th className="px-3 py-3 text-right font-semibold">Credits</th>
                      <th className="px-3 py-3 text-center font-semibold">Rows</th>
                      <th className="px-5 py-3 text-left font-semibold">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F8FAFC]">
                    {bankStatements.map(bs => (
                      <tr key={bs.id} className="hover:bg-[#F8FAFC]">
                        <td className="px-5 py-3 text-sm font-medium text-[#0F172A]">{bs.bank_name}</td>
                        <td className="px-3 py-3 text-xs text-[#64748B] font-mono">{bs.account_number ?? "—"}</td>
                        <td className="px-3 py-3 text-xs text-[#64748B] whitespace-nowrap">
                          {formatDate(bs.statement_from)} – {formatDate(bs.statement_to)}
                        </td>
                        <td className="px-3 py-3 text-sm text-right tabular-nums text-red-600">{formatPaise(bs.total_debits_paise)}</td>
                        <td className="px-3 py-3 text-sm text-right tabular-nums text-green-600">{formatPaise(bs.total_credits_paise)}</td>
                        <td className="px-3 py-3 text-xs text-center text-[#64748B]">{bs.row_count}</td>
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
                  <div className="text-center py-8 text-sm text-[#94A3B8]">No bank statements imported</div>
                )}
              </div>
            </Card>
          )}
        </div>
      )}

      {/* Documents tab */}
      {activeTab === "documents" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-[#334155]">Documents ({documents.length})</h2>
            <button
              onClick={() => { setShowUploadModal(true); setUploadError(null); }}
              className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"
            >
              <Upload size={13} /> Upload Document
            </button>
          </div>

          {docsLoading ? (
            <div className="text-sm text-[#94A3B8] text-center py-8">Loading documents…</div>
          ) : documents.length === 0 ? (
            <div className="bg-white rounded-xl border border-[#F1F5F9] px-5 py-12 text-center space-y-2">
              <FolderOpen className="w-8 h-8 text-gray-200 mx-auto" />
              <p className="text-sm text-[#94A3B8]">No documents uploaded yet</p>
              <p className="text-xs text-[#CBD5E1]">Upload returns, notices, Form 16, and other files for this client</p>
            </div>
          ) : (
            <Card>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[#F1F5F9] text-xs text-[#94A3B8]">
                      <th className="px-5 py-3 text-left font-semibold">Label</th>
                      <th className="px-3 py-3 text-left font-semibold">File Name</th>
                      <th className="px-3 py-3 text-left font-semibold">Size</th>
                      <th className="px-3 py-3 text-left font-semibold">Uploaded</th>
                      <th className="px-5 py-3 text-left font-semibold">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F8FAFC]">
                    {documents.map(doc => {
                      // Count versions for this label
                      const versionCount = documents.filter(d => d.label.toLowerCase() === doc.label.toLowerCase()).length;
                      return (
                        <tr key={doc.id} className="hover:bg-[#F8FAFC]">
                          <td className="px-5 py-3 text-sm font-medium text-[#0F172A]">
                            <div className="flex items-center gap-2">
                              {doc.label}
                              {(doc.version ?? 1) > 1 && (
                                <span className="text-xs bg-blue-50 text-blue-600 px-1.5 py-0.5 rounded font-mono">v{doc.version}</span>
                              )}
                            </div>
                          </td>
                          <td className="px-3 py-3 text-xs text-[#64748B] font-mono max-w-[200px] truncate">{doc.file_name}</td>
                          <td className="px-3 py-3 text-xs text-[#64748B]">{formatFileSize(doc.file_size_bytes)}</td>
                          <td className="px-3 py-3 text-xs text-[#64748B] whitespace-nowrap">
                            {new Date(doc.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
                          </td>
                          <td className="px-5 py-3">
                            <div className="flex items-center gap-2 flex-wrap">
                              <button
                                onClick={() => handleDownloadDocument(doc)}
                                className="flex items-center gap-1 text-xs text-blue-600 hover:underline"
                              >
                                <Download size={12} /> Download
                              </button>
                              {versionCount > 1 && (
                                <button
                                  onClick={() => handleViewVersionHistory(doc.label)}
                                  className="flex items-center gap-1 text-xs text-blue-600 hover:underline"
                                >
                                  History
                                </button>
                              )}
                              <button
                                onClick={() => handleDeleteDocument(doc)}
                                disabled={deletingDocId === doc.id}
                                className="flex items-center gap-1 text-xs text-red-500 hover:underline disabled:opacity-40"
                              >
                                <Trash2 size={12} /> {deletingDocId === doc.id ? "Deleting…" : "Delete"}
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {/* Upload Modal */}
          {showUploadModal && (
            <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
              <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-[#0F172A]">Upload Document</h3>
                  <button onClick={() => { setShowUploadModal(false); setUploadFile(null); setUploadLabel(""); }} className="text-[#94A3B8] hover:text-[#475569]">
                    <X className="w-4 h-4" />
                  </button>
                </div>

                <div className="space-y-3">
                  <div>
                    <label className="block text-xs font-medium text-[#334155] mb-1">Label *</label>
                    <input
                      type="text"
                      value={uploadLabel}
                      onChange={e => setUploadLabel(e.target.value)}
                      placeholder="e.g. GSTR-9 FY 2024-25, ITR AY 2024-25, Form 16"
                      className="w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-[#334155] mb-1">File * (max 50 MB)</label>
                    <input
                      ref={fileInputRef}
                      type="file"
                      onChange={e => setUploadFile(e.target.files?.[0] ?? null)}
                      className="w-full text-sm text-[#475569] file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:text-xs file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
                    />
                    {uploadFile && (
                      <p className="text-xs text-[#94A3B8] mt-1">{uploadFile.name} — {formatFileSize(uploadFile.size)}</p>
                    )}
                  </div>

                  {uploadError && (
                    <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{uploadError}</p>
                  )}
                </div>

                <div className="flex gap-3 justify-end">
                  <button
                    onClick={() => { setShowUploadModal(false); setUploadFile(null); setUploadLabel(""); }}
                    className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => handleUploadDocument()}
                    disabled={uploading || !uploadFile || !uploadLabel.trim()}
                    className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40"
                  >
                    {uploading ? "Uploading…" : "Upload"}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Version Prompt Modal */}
          {versionPromptDoc && (
            <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
              <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4">
                <h3 className="text-sm font-semibold text-[#0F172A]">Document already exists</h3>
                <p className="text-xs text-[#475569]">
                  A document with the label <strong>{versionPromptDoc.label}</strong> already exists (v{versionPromptDoc.version ?? 1}).
                  Upload as a new version?
                </p>
                <div className="flex gap-3 justify-end">
                  <button
                    onClick={() => setVersionPromptDoc(null)}
                    className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => { setVersionPromptDoc(null); handleUploadDocument(false, null); }}
                    className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]"
                  >
                    Upload as New
                  </button>
                  <button
                    onClick={() => { const doc = versionPromptDoc; setVersionPromptDoc(null); handleUploadDocument(true, doc); }}
                    className="text-xs px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
                  >
                    New Version
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Version History Modal */}
          {showVersionHistory && (
            <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
              <div className="bg-white rounded-xl shadow-xl w-full max-w-lg p-6 space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-[#0F172A]">Version History — {showVersionHistory}</h3>
                  <button onClick={() => setShowVersionHistory(null)} className="text-[#94A3B8] hover:text-[#475569]">
                    <X className="w-4 h-4" />
                  </button>
                </div>
                <div className="space-y-2">
                  {versionHistory.map(v => (
                    <div key={v.id} className="flex items-center justify-between py-2 border-b border-gray-50 last:border-0">
                      <div>
                        <span className="text-xs bg-blue-50 text-blue-600 px-1.5 py-0.5 rounded font-mono mr-2">v{v.version ?? 1}</span>
                        <span className="text-xs text-[#64748B]">{v.file_name}</span>
                      </div>
                      <span className="text-xs text-[#94A3B8]">
                        {new Date(v.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Portal Access section — always visible below tabs */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] p-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Globe className="w-4 h-4 text-blue-600" />
            <div>
              <h3 className="text-sm font-semibold text-[#0F172A]">Portal Access</h3>
              <p className="text-xs text-[#94A3B8] mt-0.5">
                {portal?.enabled
                  ? `Portal active${portal.invitedAt ? ` · Invited ${new Date(portal.invitedAt).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}` : ""}`
                  : "Not enabled — client cannot log in yet"}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${portal?.enabled ? "bg-green-100 text-green-700" : "bg-[#F1F5F9] text-[#64748B]"}`}>
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
              <h3 className="text-sm font-semibold text-[#0F172A]">Share Portal Link</h3>
              <button onClick={() => setShowPortalModal(false)} className="text-[#94A3B8] hover:text-[#475569]">
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
            <p className="text-xs text-[#64748B]">
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

      {/* Portal invite modal — sends magic link to client */}
      {showPortalInviteModal && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-[#0F172A]">
                Invite {client?.client_name ?? "Client"} to Portal
              </h3>
              <button onClick={() => setShowPortalInviteModal(false)} className="text-[#94A3B8] hover:text-[#475569]">
                <X className="w-4 h-4" />
              </button>
            </div>

            {portalInviteSent ? (
              <div className="text-center space-y-3 py-2">
                <div className="w-10 h-10 rounded-full bg-green-100 flex items-center justify-center mx-auto">
                  <CheckCircle className="w-5 h-5 text-green-600" />
                </div>
                <p className="text-sm font-medium text-[#0F172A]">Invite sent!</p>
                <p className="text-xs text-[#64748B]">
                  Magic link sent to <strong>{portalInviteEmail}</strong>
                </p>
                <button
                  onClick={() => setShowPortalInviteModal(false)}
                  className="w-full bg-blue-600 text-white text-sm py-2 rounded-lg hover:bg-blue-700"
                >
                  Done
                </button>
              </div>
            ) : (
              <>
                <p className="text-xs text-[#64748B]">
                  They&apos;ll receive a magic link to access their documents and filings.
                </p>
                {portalInviteError && (
                  <div className="bg-red-50 border border-red-100 rounded-lg px-3 py-2 text-xs text-red-700">
                    {portalInviteError}
                  </div>
                )}
                <div>
                  <label className="text-xs font-medium text-[#334155] block mb-1">Client Email</label>
                  <input
                    type="email"
                    value={portalInviteEmail}
                    onChange={(e) => setPortalInviteEmail(e.target.value)}
                    placeholder="client@example.com"
                    className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <button
                  onClick={handleSendPortalInvite}
                  disabled={portalLoading || !portalInviteEmail.trim()}
                  className="w-full bg-blue-600 text-white text-sm py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50"
                >
                  {portalLoading ? "Sending…" : "Send Invite"}
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {/* AI Insights tab */}
      {activeTab === "ai_insights" && (
        <div className="space-y-4">
          <div className="bg-gradient-to-br from-blue-600 to-blue-400 rounded-xl border border-blue-500/20 p-8 text-center space-y-3">
            <div className="w-12 h-12 rounded-xl bg-blue-50 flex items-center justify-center mx-auto">
              <Sparkles className="w-6 h-6 text-blue-600" />
            </div>
            <h3 className="text-sm font-semibold text-[#0F172A]">AI Insights</h3>
            <p className="text-xs text-[#64748B] max-w-sm mx-auto">
              AI-powered analysis for {client.client_name} — anomaly detection,
              missed deductions, advance tax projections, and compliance risk signals.
            </p>
            <p className="text-xs text-blue-600 font-medium">Coming soon</p>
          </div>
        </div>
      )}
    </div>
  );
}
