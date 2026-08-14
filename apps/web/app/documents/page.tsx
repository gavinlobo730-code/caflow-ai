"use client";

import { useState, useEffect, useRef, useMemo, useCallback, ChangeEvent } from "react";
import {
  FileText,
  Upload,
  Download,
  Trash2,
  X,
  AlertCircle,
  Loader2,
} from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getClients } from "@/lib/data/clients";
import { formatDate } from "@/lib/services/formatting";
import { DataTable, exportSelectedAction } from "@/components/ui/data-table";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { useToast } from "@/components/ui/use-toast";
import type { BulkAction, Column, FilterDef } from "@/lib/table/types";
import type { Client } from "@/lib/types";

// ─── Types ───────────────────────────────────────────────────────────────────

interface Document {
  id: string;
  firm_id: string;
  client_id: string | null;
  document_type: string;
  file_name: string;
  storage_path: string;
  storage_bucket: string;
  file_size: number | null;
  created_at: string;
  financial_year?: string | null;
}

const DOCUMENT_TYPES = [
  { value: "GST_RETURN", label: "GST Return" },
  { value: "ITR", label: "ITR" },
  { value: "TDS_CERTIFICATE", label: "TDS Certificate" },
  { value: "BANK_STATEMENT", label: "Bank Statement" },
  { value: "INVOICE", label: "Invoice" },
  { value: "AUDIT_REPORT", label: "Audit Report" },
  { value: "AGREEMENT", label: "Agreement" },
  { value: "OTHER", label: "Other" },
] as const;

type DocTypeValue = (typeof DOCUMENT_TYPES)[number]["value"];

const FILTER_TYPES = [
  { value: "ALL", label: "All" },
  { value: "GST_RETURN", label: "GST Returns" },
  { value: "ITR", label: "ITR" },
  { value: "TDS_CERTIFICATE", label: "TDS" },
  { value: "BANK_STATEMENT", label: "Bank Statements" },
  { value: "INVOICE", label: "Invoices" },
  { value: "OTHER", label: "Other" },
] as const;

const FINANCIAL_YEARS = ["2023-24", "2024-25", "2025-26"] as const;
type FinancialYear = (typeof FINANCIAL_YEARS)[number];

const STORAGE_BUCKET = "Documents";
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ─── Helpers ─────────────────────────────────────────────────────────────────

async function apiFetch(path: string, opts?: RequestInit) {
  const { data: { session } } = await getSupabaseClient().auth.getSession();
  const token = session?.access_token ?? "";
  const res = await fetch(`${API}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json() as { error?: string; detail?: string };
      detail = body.error ?? body.detail ?? detail;
    } catch { /* not JSON */ }
    throw new Error(detail);
  }
  return res.json();
}

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const {
    data: { session },
  } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb
    .from("users")
    .select("firm_id")
    .eq("auth_user_id", session.user.id)
    .single();
  if (!data) throw new Error("User not found");
  return data.firm_id as string;
}

function formatBytes(bytes: number | null): string {
  if (bytes === null || bytes === undefined) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function docTypeLabel(value: string): string {
  return DOCUMENT_TYPES.find((t) => t.value === value)?.label ?? value;
}

function docTypeBadgeColor(value: string): string {
  const map: Record<string, string> = {
    GST_RETURN: "bg-green-100 text-green-700",
    ITR: "bg-blue-100 text-blue-700",
    TDS_CERTIFICATE: "bg-purple-100 text-purple-700",
    BANK_STATEMENT: "bg-yellow-100 text-yellow-700",
    INVOICE: "bg-orange-100 text-orange-700",
    AUDIT_REPORT: "bg-red-100 text-red-700",
    AGREEMENT: "bg-blue-50 text-blue-600",
    OTHER: "bg-[#F1F5F9] text-[#475569]",
  };
  return map[value] ?? "bg-[#F1F5F9] text-[#475569]";
}

// ─── Upload Modal ─────────────────────────────────────────────────────────────

interface UploadModalProps {
  clients: Client[];
  onClose: () => void;
  onUploaded: () => void;
}

function UploadModal({ clients, onClose, onUploaded }: UploadModalProps) {
  const [clientId, setClientId] = useState("");
  const [docType, setDocType] = useState<DocTypeValue>("OTHER");
  const [financialYear, setFinancialYear] = useState<FinancialYear>("2025-26");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    setFile(e.target.files?.[0] ?? null);
  }

  async function handleUpload() {
    if (!file) { setError("Please select a file."); return; }
    if (!clientId) { setError("Please select a client."); return; }

    setUploading(true);
    setError(null);

    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();

      // Sanitise filename to avoid path issues
      const safeName = file.name.replace(/[^a-zA-Z0-9._\-]/g, "_");
      const storagePath = `${firmId}/${clientId}/${docType}/${safeName}`;

      // Upload to Supabase Storage
      const { error: storageErr } = await sb.storage
        .from(STORAGE_BUCKET)
        .upload(storagePath, file, { upsert: true });

      if (storageErr) {
        if (
          storageErr.message.toLowerCase().includes("bucket") ||
          storageErr.message.toLowerCase().includes("not found")
        ) {
          throw new Error(
            "Storage not configured. Please create a 'Documents' bucket in Supabase Storage."
          );
        }
        throw new Error(storageErr.message);
      }

      // Insert document record
      const { error: dbErr } = await sb.from("documents").insert({
        firm_id: firmId,
        client_id: clientId,
        document_type: docType,
        file_name: file.name,
        storage_path: storagePath,
        storage_bucket: STORAGE_BUCKET,
        file_size_bytes: file.size,   // the column is file_size_bytes
        financial_year: financialYear,
      });

      if (dbErr) throw new Error(dbErr.message);

      onUploaded();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0F172A]/60 p-4">
      <div className="w-full max-w-md rounded-xl bg-white shadow-xl">
        {/* Modal header */}
        <div className="flex items-center justify-between border-b border-[#F1F5F9] px-6 py-4">
          <h2 className="text-base font-semibold text-[#0F172A]">Upload Document</h2>
          <button
            onClick={onClose}
            className="rounded p-1 text-[#94A3B8] hover:bg-[#F1F5F9] hover:text-[#475569]"
          >
            <X size={18} />
          </button>
        </div>

        {/* Modal body */}
        <div className="space-y-4 px-6 py-5">
          {error && (
            <div className="flex items-start gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-700">
              <AlertCircle size={16} className="mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* Client */}
          <div>
            <label className="mb-1 block text-sm font-medium text-[#334155]">
              Client <span className="text-red-500">*</span>
            </label>
            <div className="w-full">
              <ClientLookup
                clients={clients}
                value={clientId}
                onChange={setClientId}
                ariaLabel="Client"
                placeholder="Select client…"
                disabled={uploading}
              />
            </div>
          </div>

          {/* Document type */}
          <div>
            <label className="mb-1 block text-sm font-medium text-[#334155]">
              Document Type <span className="text-red-500">*</span>
            </label>
            <select
              value={docType}
              onChange={(e) => setDocType(e.target.value as DocTypeValue)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
              disabled={uploading}
            >
              {DOCUMENT_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>

          {/* Financial year */}
          <div>
            <label className="mb-1 block text-sm font-medium text-[#334155]">
              Financial Year
            </label>
            <select
              value={financialYear}
              onChange={(e) => setFinancialYear(e.target.value as FinancialYear)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
              disabled={uploading}
            >
              {FINANCIAL_YEARS.map((fy) => (
                <option key={fy} value={fy}>
                  {fy}
                </option>
              ))}
            </select>
          </div>

          {/* File picker */}
          <div>
            <label className="mb-1 block text-sm font-medium text-[#334155]">
              File <span className="text-red-500">*</span>
            </label>
            <div
              onClick={() => !uploading && fileRef.current?.click()}
              className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-6 transition-colors ${
                file
                  ? "border-blue-400 bg-blue-50"
                  : "border-[#E2E8F0] hover:border-blue-300 hover:bg-[#F8FAFC]"
              } ${uploading ? "pointer-events-none opacity-60" : ""}`}
            >
              <input
                ref={fileRef}
                type="file"
                className="hidden"
                onChange={handleFileChange}
                accept=".pdf,.png,.jpg,.jpeg,.xlsx,.xls,.csv,.doc,.docx"
              />
              {file ? (
                <>
                  <FileText className="h-6 w-6 text-blue-500" />
                  <p className="text-sm font-medium text-blue-700">{file.name}</p>
                  <p className="text-xs text-[#64748B]">{formatBytes(file.size)}</p>
                </>
              ) : (
                <>
                  <Upload className="h-6 w-6 text-[#94A3B8]" />
                  <p className="text-sm font-medium text-[#475569]">
                    Click to browse or drop a file
                  </p>
                  <p className="text-xs text-[#94A3B8]">PDF, Excel, Word, Images</p>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Modal footer */}
        <div className="flex items-center justify-end gap-3 border-t border-[#F1F5F9] px-6 py-4">
          <button
            onClick={onClose}
            disabled={uploading}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-[#334155] hover:bg-[#F8FAFC] disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleUpload}
            disabled={uploading || !file}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {uploading ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                Uploading…
              </>
            ) : (
              <>
                <Upload size={14} />
                Upload
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);

  const [showUploadModal, setShowUploadModal] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  const { toast } = useToast();

  async function loadData() {
    setLoading(true);
    setPageError(null);
    try {
      const [clientList, firmId] = await Promise.all([
        getClients(),
        getFirmId(),
      ]);
      setClients(clientList);

      const sb = getSupabaseClient();
      const { data, error } = await sb
        .from("documents")
        .select("*")
        .eq("firm_id", firmId)
        .order("created_at", { ascending: false });

      if (error) throw new Error(error.message);
      setDocuments((data ?? []) as Document[]);
    } catch (err) {
      setPageError(err instanceof Error ? err.message : "Failed to load documents");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  async function handleDelete(doc: Document) {
    if (!confirm(`Delete "${doc.file_name}"?`)) return;
    setDeleting(doc.id);
    try {
      await apiFetch(`/api/documents/${doc.id}`, { method: "DELETE" });
      setDocuments((prev) => prev.filter((d) => d.id !== doc.id));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeleting(null);
    }
  }

  // Bulk delete over the DataTable's selected rows (reuses the same
  // DELETE /api/documents/{id} soft-delete call as the single-row action;
  // confirm dialog is handled by DataTable via the bulk action's `confirm`).
  const handleBulkDelete = useCallback(async (rows: Document[]) => {
    const results = await Promise.all(
      rows.map((doc) =>
        apiFetch(`/api/documents/${doc.id}`, { method: "DELETE" })
          .then(() => true)
          .catch(() => false)
      )
    );
    await loadData();

    const failedCount = results.filter((ok) => !ok).length;
    if (failedCount > 0) {
      toast({
        variant: "destructive",
        title: "Some documents couldn't be deleted",
        description: `${rows.length - failedCount} of ${rows.length} deleted. ${failedCount} failed — please try again.`,
      });
      return false;
    }

    toast({
      title: "Documents deleted",
      description: `${rows.length} document${rows.length === 1 ? "" : "s"} deleted.`,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toast]);

  async function handleDownload(doc: Document) {
    try {
      const sb = getSupabaseClient();
      const { data, error } = await sb.storage
        .from(doc.storage_bucket)
        .createSignedUrl(doc.storage_path, 60);
      if (error) throw new Error(error.message);
      window.open(data.signedUrl, "_blank");
    } catch (err) {
      alert(err instanceof Error ? err.message : "Download failed");
    }
  }

  // Client lookup map — name resolution for the client column + search.
  const clientMap = useMemo(
    () => Object.fromEntries(clients.map((c) => [c.id, c.client_name])),
    [clients],
  );

  const clientName = (doc: Document) =>
    doc.client_id ? clientMap[doc.client_id] ?? "Unknown" : "";

  const columns: Column<Document>[] = useMemo(() => [
    {
      key: "file_name", header: "File Name", accessor: (d) => d.file_name,
      searchable: true, sortable: true, sticky: true, hideable: false,
      render: (d) => (
        <div className="flex items-center gap-2">
          <FileText size={15} className="shrink-0 text-[#94A3B8]" />
          <span className="max-w-[220px] truncate font-medium text-[#1E293B]" title={d.file_name}>
            {d.file_name}
          </span>
        </div>
      ),
    },
    {
      key: "client", header: "Client", accessor: (d) => clientName(d),
      searchable: true, sortable: true,
      render: (d) => <span className="text-[#475569]">{d.client_id ? (clientMap[d.client_id] ?? "Unknown") : "—"}</span>,
    },
    {
      key: "document_type", header: "Type", accessor: (d) => docTypeLabel(d.document_type),
      sortable: true,
      render: (d) => (
        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${docTypeBadgeColor(d.document_type)}`}>
          {docTypeLabel(d.document_type)}
        </span>
      ),
    },
    {
      key: "financial_year", header: "Financial Year", accessor: (d) => d.financial_year ?? "",
      sortable: true,
      render: (d) => <span className="text-[#475569]">{d.financial_year ?? "—"}</span>,
    },
    {
      key: "created_at", header: "Uploaded", accessor: (d) => d.created_at,
      sortable: true,
      render: (d) => <span className="text-[#64748B]">{formatDate(d.created_at)}</span>,
    },
    {
      key: "file_size", header: "Size", accessor: (d) => d.file_size ?? 0,
      sortable: true, align: "right", defaultHidden: true,
      render: (d) => <span className="text-[#64748B]">{formatBytes(d.file_size)}</span>,
    },
  ], [clientMap]); // eslint-disable-line react-hooks/exhaustive-deps

  const filters: FilterDef<Document>[] = useMemo(() => [
    {
      key: "client", label: "Client", type: "select", accessor: (d) => d.client_id ?? "",
      options: clients.map((c) => ({ value: c.id, label: c.client_name })),
    },
    {
      key: "document_type", label: "Type", type: "select", accessor: (d) => d.document_type,
      options: FILTER_TYPES.filter((t) => t.value !== "ALL").map((t) => ({ value: t.value, label: t.label })),
    },
    {
      key: "financial_year", label: "Financial Year", type: "select", accessor: (d) => d.financial_year ?? "",
      options: FINANCIAL_YEARS.map((fy) => ({ value: fy, label: fy })),
    },
    {
      key: "created_at", label: "Uploaded", type: "dateRange", accessor: (d) => d.created_at,
    },
  ], [clients]);

  // ── DataTable bulk actions ───────────────────────────────────────────────────
  const bulkActions: BulkAction<Document>[] = useMemo(() => [
    {
      id: "delete", label: "Delete", icon: <Trash2 size={13} />, variant: "danger",
      confirm: "Delete the selected documents? This cannot be undone.",
      run: handleBulkDelete,
    },
    exportSelectedAction<Document>("documents-selected.csv", columns),
  ], [handleBulkDelete, columns]);

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* ── Header ── */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">Documents</h1>
          <p className="text-sm text-[#64748B] mt-0.5">
            Manage client documents and files
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowUploadModal(true)}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            <Upload size={16} />
            Upload Document
          </button>
        </div>
      </div>

      {/* ── Documents table — shared DataTable (search, sort, filters, pagination, export, prefs) ── */}
      <DataTable
        data={documents}
        columns={columns}
        filters={filters}
        getRowId={(d) => d.id}
        loading={loading}
        error={pageError}
        onRetry={loadData}
        onRefresh={loadData}
        searchPlaceholder="Search by file name or client…"
        initialSort={{ key: "created_at", dir: "desc" }}
        bulkActions={bulkActions}
        exportFilename="documents"
        persistKey="documents.list"
        emptyTitle={documents.length === 0 ? "No documents yet." : "No documents match the current filters."}
        emptyDescription={documents.length === 0 ? "Upload your first document to get started." : undefined}
        emptyAction={
          documents.length === 0 ? (
            <button
              onClick={() => setShowUploadModal(true)}
              className="mt-4 flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
            >
              <Upload size={14} />
              Upload Document
            </button>
          ) : undefined
        }
        rowActions={(doc) => (
          <div className="flex items-center justify-end gap-1">
            <button
              onClick={() => handleDownload(doc)}
              title="Download"
              className="rounded p-1.5 text-[#94A3B8] hover:bg-[#F1F5F9] hover:text-blue-600"
            >
              <Download size={15} />
            </button>
            <button
              onClick={() => handleDelete(doc)}
              disabled={deleting === doc.id}
              title="Delete"
              className="rounded p-1.5 text-[#94A3B8] hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
            >
              {deleting === doc.id ? (
                <Loader2 size={15} className="animate-spin" />
              ) : (
                <Trash2 size={15} />
              )}
            </button>
          </div>
        )}
      />

      {/* ── Upload modal ── */}
      {showUploadModal && (
        <UploadModal
          clients={clients}
          onClose={() => setShowUploadModal(false)}
          onUploaded={loadData}
        />
      )}
    </div>
  );
}
