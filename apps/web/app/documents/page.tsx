"use client";

import { useState, useEffect, useRef, useMemo, useCallback, ChangeEvent } from "react";
import {
  FileText,
  Upload,
  Download,
  Trash2,
  X,
  Loader2,
} from "lucide-react";
import { api } from "@/lib/api";
import { objectWithLists } from "@/lib/api/shape";
import { getClients } from "@/lib/data/clients";
import { formatDate } from "@/lib/services/formatting";
import { DataTable, exportSelectedAction } from "@/components/ui/data-table";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { useToast } from "@/components/ui/use-toast";
import type { BulkAction, Column, FilterDef } from "@/lib/table/types";
import type { Client } from "@/lib/types";
import { financialYearChoicesAround } from "@/lib/dates/periods";
import { YearPicker } from "@/components/ui/year-picker";
import { Callout } from "@/components/ui/callout";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyStateAction, EmptyStateActions } from "@/components/ui/empty-state-action";

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

// Must match the DB CHECK constraint exactly (migration 001,
// documents_document_type_check) — these are the only nine values the
// documents table will accept. Offering a value the constraint does not
// allow lets the upload modal store the file in Supabase Storage and THEN
// fail the documents-table insert with a raw 23514 check-violation, leaving
// an orphaned, untracked blob with no DB row (sweep-reports-documents-02).
const DOCUMENT_TYPES = [
  { value: "FORM16", label: "Form 16" },
  { value: "GST_INVOICE", label: "GST Invoice" },
  { value: "BANK_STATEMENT", label: "Bank Statement" },
  { value: "AIS", label: "AIS" },
  { value: "FORM26AS", label: "Form 26AS" },
  { value: "TDS_CERTIFICATE", label: "TDS Certificate" },
  { value: "RENTAL_AGREEMENT", label: "Rental Agreement" },
  { value: "CAPITAL_GAINS_STATEMENT", label: "Capital Gains Statement" },
  { value: "OTHER", label: "Other" },
] as const;

type DocTypeValue = (typeof DOCUMENT_TYPES)[number]["value"];

const FILTER_TYPES = [
  { value: "ALL", label: "All" },
  { value: "FORM16", label: "Form 16" },
  { value: "GST_INVOICE", label: "GST Invoice" },
  { value: "BANK_STATEMENT", label: "Bank Statement" },
  { value: "AIS", label: "AIS" },
  { value: "FORM26AS", label: "Form 26AS" },
  { value: "TDS_CERTIFICATE", label: "TDS Certificate" },
  { value: "RENTAL_AGREEMENT", label: "Rental Agreement" },
  { value: "CAPITAL_GAINS_STATEMENT", label: "Capital Gains Statement" },
  { value: "OTHER", label: "Other" },
] as const;

// FROM THE CLOCK, NOT A LITERAL. This list ended at a year that is now in the
// past, so the current financial year could not be selected at all — broken on
// 1 April with nothing saying so. `financialYearChoicesAround` is the one
// helper (lib/dates/periods.ts); see
// scripts/a-financial-year-choice-comes-from-the-clock.test.ts.
const FINANCIAL_YEARS = financialYearChoicesAround(null);
type FinancialYear = (typeof FINANCIAL_YEARS)[number];

// ─── Helpers ─────────────────────────────────────────────────────────────────

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
    FORM16: "bg-blue-100 text-blue-700",
    GST_INVOICE: "bg-green-100 text-green-700",
    BANK_STATEMENT: "bg-yellow-100 text-yellow-700",
    AIS: "bg-purple-100 text-purple-700",
    FORM26AS: "bg-blue-50 text-blue-600",
    TDS_CERTIFICATE: "bg-purple-100 text-purple-700",
    RENTAL_AGREEMENT: "bg-state-attention-surface text-state-attention",
    CAPITAL_GAINS_STATEMENT: "bg-state-problem-surface text-state-problem",
    OTHER: "bg-ps-muted text-ps-label",
  };
  return map[value] ?? "bg-ps-muted text-ps-label";
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
  // FROM THE CLOCK, NOT A LITERAL — FINANCIAL_YEARS[0] is the current FY
  // (financialYearChoicesAround sorts newest first); a hardcoded year goes
  // stale every 1 April with nothing saying so.
  const [financialYear, setFinancialYear] = useState<FinancialYear>(FINANCIAL_YEARS[0]);
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
      // The server stores the file under the firm and client, names it itself, bounds its size, checks its type
      // against its bytes, and writes the record; if the record cannot be written it removes the file again
      // (routers/documents.py). The browser neither holds the bucket nor writes the table.
      const form = new FormData();
      form.append("file", file);
      form.append("client_id", clientId);
      form.append("document_type", docType);
      form.append("financial_year", financialYear);
      await api.documents.upload(form);

      onUploaded();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand-dark/60 p-4">
      <div className="w-full max-w-md rounded-xl bg-white shadow-xl">
        {/* Modal header */}
        <div className="flex items-center justify-between border-b border-ps-border px-6 py-4">
          <h2 className="text-base font-semibold text-ps-ink">Upload Document</h2>
          <button
            onClick={onClose}
            className="rounded p-1 text-ps-hint hover:bg-ps-muted hover:text-ps-label"
          >
            <X size={18} />
          </button>
        </div>

        {/* Modal body */}
        <div className="space-y-4 px-6 py-5">
          {error && <Callout tone="problem">{error}</Callout>}

          {/* Client */}
          <div>
            <label className="mb-1 block text-sm font-medium text-ps-body">
              Client <span className="text-state-problem">*</span>
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
            <label className="mb-1 block text-sm font-medium text-ps-body">
              Document Type <span className="text-state-problem">*</span>
            </label>
            <select
              value={docType}
              onChange={(e) => setDocType(e.target.value as DocTypeValue)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-brand"
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
            <label className="mb-1 block text-sm font-medium text-ps-body">
              Financial Year
            </label>
            <YearPicker value={financialYear} onChange={v => setFinancialYear(v as FinancialYear)}
            disabled={uploading} />
          </div>

          {/* File picker */}
          <div>
            <label className="mb-1 block text-sm font-medium text-ps-body">
              File <span className="text-state-problem">*</span>
            </label>
            <div
              onClick={() => !uploading && fileRef.current?.click()}
              className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-6 transition-colors ${
                file
                  ? "border-blue-400 bg-blue-50"
                  : "border-ps-border hover:border-blue-300 hover:bg-ps-bg"
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
                  <p className="text-xs text-ps-label">{formatBytes(file.size)}</p>
                </>
              ) : (
                <>
                  <Upload className="h-6 w-6 text-ps-hint" />
                  <p className="text-sm font-medium text-ps-label">
                    Click to browse or drop a file
                  </p>
                  <p className="text-xs text-ps-hint">PDF, Excel, Word, Images</p>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Modal footer */}
        <div className="flex items-center justify-end gap-3 border-t border-ps-border px-6 py-4">
          <button
            onClick={onClose}
            disabled={uploading}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-ps-body hover:bg-ps-bg disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleUpload}
            disabled={uploading || !file}
            className="flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-50"
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
  // The document whose link is being fetched: one at a time, so a second click does not open a second tab.
  const [downloading, setDownloading] = useState<string | null>(null);

  const { toast } = useToast();

  async function loadData() {
    setLoading(true);
    setPageError(null);
    try {
      const [clientList, listed] = await Promise.all([
        getClients(),
        api.documents.list() as Promise<{ success?: boolean; data?: unknown; error?: string | null }>,
      ]);
      setClients(clientList);

      // Every document the caller may see, newest first: the server reads them in pages of its own (a response is cut
      // at about a thousand rows without a word) and narrows them to the clients the caller is assigned to. A refusal
      // or an unreadable body is an error on this screen, never an empty list of documents.
      if (!listed?.success) throw new Error(listed?.error ?? "Failed to load documents");
      const body = objectWithLists<{ documents: Document[] }>(listed.data, "documents");
      if (!body) throw new Error("The list of documents came back in a shape this screen cannot read.");
      setDocuments(body.documents);
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
    if (!(await confirmDialog({ message: `Delete "${doc.file_name}"?`, danger: true, confirmLabel: "Delete" }))) return;
    setDeleting(doc.id);
    try {
      await api.documents.remove(doc.id);
      setDocuments((prev) => prev.filter((d) => d.id !== doc.id));
    } catch (err) {
      toast({ title: err instanceof Error ? err.message : "Delete failed", variant: "destructive" });
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
        api.documents.remove(doc.id)
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
    setDownloading(doc.id);
    try {
      // A link minted now by the server, after it has checked the document is in the caller's firm and clients.
      const res = (await api.documents.downloadUrl(doc.id)) as { success?: boolean; data?: { download_url?: string | null }; error?: string | null };
      const url = res?.data?.download_url;
      if (!res?.success || !url) throw new Error(res?.error ?? "This document has no file to open.");
      window.open(url, "_blank");
    } catch (err) {
      toast({ title: err instanceof Error ? err.message : "Download failed", variant: "destructive" });
    } finally {
      setDownloading(null);
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
          <FileText size={15} className="shrink-0 text-ps-hint" />
          <span className="max-w-[220px] truncate font-medium text-ps-ink" title={d.file_name}>
            {d.file_name}
          </span>
        </div>
      ),
    },
    {
      key: "client", header: "Client", accessor: (d) => clientName(d),
      searchable: true, sortable: true,
      render: (d) => <span className="text-ps-label">{d.client_id ? (clientMap[d.client_id] ?? "Unknown") : "—"}</span>,
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
      render: (d) => <span className="text-ps-label">{d.financial_year ?? "—"}</span>,
    },
    {
      key: "created_at", header: "Uploaded", accessor: (d) => d.created_at,
      sortable: true,
      render: (d) => <span className="text-ps-label">{formatDate(d.created_at)}</span>,
    },
    {
      key: "file_size", header: "Size", accessor: (d) => d.file_size ?? 0,
      sortable: true, align: "right", defaultHidden: true,
      render: (d) => <span className="text-ps-label">{formatBytes(d.file_size)}</span>,
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
    <div className="p-6 max-w-ps-data mx-auto">
      {/* ── Header ── */}
      <PageHeader
        title="Documents"
        subtitle="Manage client documents and files"
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowUploadModal(true)}
              className="flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-dark"
            >
              <Upload size={16} />
              Upload Document
            </button>
          </div>
        }
        className="mb-6"
      />

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
            <EmptyStateActions>
              <EmptyStateAction requires={["document", "write"]} icon={<Upload size={14} />} label="Upload Document"
                onClick={() => setShowUploadModal(true)} />
            </EmptyStateActions>
          ) : undefined
        }
        rowActions={(doc) => (
          <div className="flex items-center justify-end gap-1">
            <button
              onClick={() => handleDownload(doc)}
              disabled={downloading !== null}
              title="Download"
              className="rounded p-1.5 text-ps-hint hover:bg-ps-muted hover:text-blue-600 disabled:opacity-50"
            >
              <Download size={15} />
            </button>
            <button
              onClick={() => handleDelete(doc)}
              disabled={deleting === doc.id}
              title="Delete"
              className="rounded p-1.5 text-ps-hint hover:bg-state-problem-hover hover:text-red-600 disabled:opacity-40"
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
