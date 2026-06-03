"use client";

import { useState, useEffect, useRef, ChangeEvent } from "react";
import {
  FileText,
  Upload,
  Search,
  Download,
  Trash2,
  X,
  AlertCircle,
  Loader2,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getClients } from "@/lib/data/clients";
import { formatDate } from "@/lib/services/formatting";
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

// ─── Helpers ─────────────────────────────────────────────────────────────────

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
    AGREEMENT: "bg-indigo-100 text-indigo-700",
    OTHER: "bg-gray-100 text-gray-600",
  };
  return map[value] ?? "bg-gray-100 text-gray-600";
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
        file_size: file.size,
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-white shadow-xl">
        {/* Modal header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4">
          <h2 className="text-base font-semibold text-gray-900">Upload Document</h2>
          <button
            onClick={onClose}
            className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
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
            <label className="mb-1 block text-sm font-medium text-gray-700">
              Client <span className="text-red-500">*</span>
            </label>
            <select
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
              disabled={uploading}
            >
              <option value="">Select client…</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.client_name}
                </option>
              ))}
            </select>
          </div>

          {/* Document type */}
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
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
            <label className="mb-1 block text-sm font-medium text-gray-700">
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
            <label className="mb-1 block text-sm font-medium text-gray-700">
              File <span className="text-red-500">*</span>
            </label>
            <div
              onClick={() => !uploading && fileRef.current?.click()}
              className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-6 transition-colors ${
                file
                  ? "border-blue-400 bg-blue-50"
                  : "border-gray-200 hover:border-blue-300 hover:bg-gray-50"
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
                  <p className="text-xs text-gray-500">{formatBytes(file.size)}</p>
                </>
              ) : (
                <>
                  <Upload className="h-6 w-6 text-gray-400" />
                  <p className="text-sm font-medium text-gray-600">
                    Click to browse or drop a file
                  </p>
                  <p className="text-xs text-gray-400">PDF, Excel, Word, Images</p>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Modal footer */}
        <div className="flex items-center justify-end gap-3 border-t border-gray-100 px-6 py-4">
          <button
            onClick={onClose}
            disabled={uploading}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
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

  // Filters
  const [search, setSearch] = useState("");
  const [filterClient, setFilterClient] = useState("ALL");
  const [filterType, setFilterType] = useState("ALL");
  const [filterYear, setFilterYear] = useState("ALL");

  const [showUploadModal, setShowUploadModal] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

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
    if (!confirm(`Delete "${doc.file_name}"? This cannot be undone.`)) return;
    setDeleting(doc.id);
    try {
      const sb = getSupabaseClient();
      // Remove from storage
      await sb.storage.from(doc.storage_bucket).remove([doc.storage_path]);
      // Remove DB record
      const { error } = await sb.from("documents").delete().eq("id", doc.id);
      if (error) throw new Error(error.message);
      setDocuments((prev) => prev.filter((d) => d.id !== doc.id));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeleting(null);
    }
  }

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

  // Client lookup map
  const clientMap = Object.fromEntries(clients.map((c) => [c.id, c.client_name]));

  // Filtered documents
  const filtered = documents.filter((doc) => {
    const matchSearch =
      !search ||
      doc.file_name.toLowerCase().includes(search.toLowerCase()) ||
      (clientMap[doc.client_id ?? ""] ?? "").toLowerCase().includes(search.toLowerCase());
    const matchClient = filterClient === "ALL" || doc.client_id === filterClient;
    const matchType = filterType === "ALL" || doc.document_type === filterType;
    const matchYear =
      filterYear === "ALL" || doc.financial_year === filterYear;
    return matchSearch && matchClient && matchType && matchYear;
  });

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* ── Header ── */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Documents</h1>
          <p className="text-sm text-gray-500 mt-0.5">
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

      {/* ── Filter bar ── */}
      <div className="flex flex-wrap items-center gap-3 mb-5">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <Search
            size={15}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
          />
          <input
            type="text"
            placeholder="Search documents…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-gray-300 py-2 pl-9 pr-3 text-sm outline-none focus:border-blue-500"
          />
        </div>

        {/* Client filter */}
        <select
          value={filterClient}
          onChange={(e) => setFilterClient(e.target.value)}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
        >
          <option value="ALL">All Clients</option>
          {clients.map((c) => (
            <option key={c.id} value={c.id}>
              {c.client_name}
            </option>
          ))}
        </select>

        {/* Type filter */}
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
        >
          {FILTER_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>

        {/* Year filter */}
        <select
          value={filterYear}
          onChange={(e) => setFilterYear(e.target.value)}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
        >
          <option value="ALL">All Years</option>
          {FINANCIAL_YEARS.map((fy) => (
            <option key={fy} value={fy}>
              {fy}
            </option>
          ))}
        </select>
      </div>

      {/* ── Content ── */}
      {loading ? (
        <div className="flex items-center justify-center py-24">
          <Loader2 className="h-7 w-7 animate-spin text-blue-500" />
        </div>
      ) : pageError ? (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <AlertCircle className="h-10 w-10 text-red-400 mb-3" />
          <p className="text-sm font-medium text-red-700">{pageError}</p>
          <button
            onClick={loadData}
            className="mt-3 text-xs text-blue-600 hover:underline"
          >
            Retry
          </button>
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 py-20 text-center">
          <FileText className="h-12 w-12 text-gray-300 mb-3" />
          {documents.length === 0 ? (
            <>
              <p className="text-sm font-medium text-gray-600">No documents yet.</p>
              <p className="text-xs text-gray-400 mt-1">
                Upload your first document to get started.
              </p>
              <button
                onClick={() => setShowUploadModal(true)}
                className="mt-4 flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
              >
                <Upload size={14} />
                Upload Document
              </button>
            </>
          ) : (
            <p className="text-sm text-gray-500">No documents match the current filters.</p>
          )}
        </div>
      ) : (
        <Card className="overflow-hidden p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50 text-left">
                  <th className="px-4 py-3 font-medium text-gray-500">File Name</th>
                  <th className="px-4 py-3 font-medium text-gray-500">Client</th>
                  <th className="px-4 py-3 font-medium text-gray-500">Type</th>
                  <th className="px-4 py-3 font-medium text-gray-500">Financial Year</th>
                  <th className="px-4 py-3 font-medium text-gray-500">Uploaded</th>
                  <th className="px-4 py-3 font-medium text-gray-500">Size</th>
                  <th className="px-4 py-3 font-medium text-gray-500 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filtered.map((doc) => (
                  <tr key={doc.id} className="hover:bg-gray-50 transition-colors">
                    {/* File name */}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <FileText size={15} className="shrink-0 text-gray-400" />
                        <span
                          className="max-w-[220px] truncate font-medium text-gray-800"
                          title={doc.file_name}
                        >
                          {doc.file_name}
                        </span>
                      </div>
                    </td>

                    {/* Client */}
                    <td className="px-4 py-3 text-gray-600">
                      {doc.client_id
                        ? (clientMap[doc.client_id] ?? "Unknown")
                        : "—"}
                    </td>

                    {/* Type */}
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${docTypeBadgeColor(doc.document_type)}`}
                      >
                        {docTypeLabel(doc.document_type)}
                      </span>
                    </td>

                    {/* Financial year */}
                    <td className="px-4 py-3 text-gray-600">
                      {doc.financial_year ?? "—"}
                    </td>

                    {/* Uploaded date */}
                    <td className="px-4 py-3 text-gray-500">
                      {formatDate(doc.created_at)}
                    </td>

                    {/* Size */}
                    <td className="px-4 py-3 text-gray-500">
                      {formatBytes(doc.file_size)}
                    </td>

                    {/* Actions */}
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => handleDownload(doc)}
                          title="Download"
                          className="rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-blue-600"
                        >
                          <Download size={15} />
                        </button>
                        <button
                          onClick={() => handleDelete(doc)}
                          disabled={deleting === doc.id}
                          title="Delete"
                          className="rounded p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
                        >
                          {deleting === doc.id ? (
                            <Loader2 size={15} className="animate-spin" />
                          ) : (
                            <Trash2 size={15} />
                          )}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Row count */}
          <div className="border-t border-gray-100 px-4 py-2 text-xs text-gray-400">
            {filtered.length} document{filtered.length !== 1 ? "s" : ""}
            {filtered.length !== documents.length && ` (filtered from ${documents.length})`}
          </div>
        </Card>
      )}

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
