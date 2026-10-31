"use client";

/**
 * Client Document Vault — Organized per-client document storage
 * The server stores each file under {firm_id}/{client_id}/ in the private `Documents` bucket, writes its record and signs
 * its links (/api/client-documents); this page holds neither the bucket nor the table (POST-A-010).
 * Expiry alerts for certificates expiring within 60 days
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { Upload, Download, Trash2, AlertTriangle, X, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { objectWithLists } from "@/lib/api/shape";
import type { ClientDocumentList } from "@/lib/api";
import { getClients } from "@/lib/data/clients";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { CardGridSkeleton } from "@/components/ui/skeleton";
import type { Client } from "@/lib/types";

import { todayLocalISO, daysBetweenLocalISO } from "@/lib/dateMath";
import { formatDate } from "@/lib/dates/format";
import { Callout } from "@/components/ui/callout";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { PageHeader } from "@/components/ui/page-header";
type DocCategory = "Identity" | "GST" | "Income Tax" | "MCA" | "Financials" | "Other";

const CATEGORIES: DocCategory[] = ["Identity", "GST", "Income Tax", "MCA", "Financials", "Other"];

const CATEGORY_DESC: Record<DocCategory, string> = {
  "Identity": "PAN, Aadhaar, Photo",
  "GST": "Registration, Returns",
  "Income Tax": "ITRs, Form 26AS, AIS",
  "MCA": "COI, MOA, AOA, Board Resolutions",
  "Financials": "Audited accounts, Bank statements",
  "Other": "Miscellaneous documents",
};

// client_documents as it actually is (migration 014). Migration 023 declares a
// different shape and is a silent no-op — CREATE TABLE IF NOT EXISTS on a table
// 014 already created. The user-supplied name lives in `description`, and the
// category in `doc_type`.
interface ClientDocument {
  id: string;
  client_id: string;
  file_name: string;
  description: string | null;
  doc_type: DocCategory;
  file_path: string;
  file_size: number;
  expiry_date: string | null;
  uploaded_by: string | null;
  created_at: string;
  download_url?: string;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

// Whole days from today to the document's expiry, both anchored to local
// midnight. `new Date(expiryDate)` parses a date-only string as UTC midnight
// while `new Date()` is a live instant, so in IST this read one day too many
// between 00:00 and 05:30 — on the figure that decides whether a client's
// identity document is flagged as expiring.
function daysUntilExpiry(expiryDate: string): number {
  return daysBetweenLocalISO(todayLocalISO(), String(expiryDate).slice(0, 10)) ?? 0;
}

interface UploadModalProps {
  onClose: () => void;
  onUploaded: () => void;
  clientId: string;
}

function UploadModal({ onClose, onUploaded, clientId }: UploadModalProps) {
  const [docName, setDocName] = useState("");
  const [category, setCategory] = useState<DocCategory>("Identity");
  const [expiryDate, setExpiryDate] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleUpload() {
    if (!file || !docName) { setError("Enter document name and select a file"); return; }
    setUploading(true);
    try {
      // The server bounds the file, checks its bytes against its type, names and stores it under the firm and client,
      // and writes the record with the signed-in person as the uploader (their internal id, never the sign-in id).
      const form = new FormData();
      form.append("file", file);
      form.append("client_id", clientId);
      form.append("description", docName);
      form.append("doc_type", category);
      if (expiryDate) form.append("expiry_date", expiryDate);
      await api.clientDocuments.upload(form);
      onUploaded();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-brand-dark/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-ps-ink">Upload Document</h3>
          <button aria-label="Close" onClick={onClose} className="text-ps-hint hover:text-ps-label"><X size={16} /></button>
        </div>
        {error && <Callout tone="problem">{error}</Callout>}
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-ps-body block mb-1">Document Name</label>
            <input type="text" value={docName} onChange={e => setDocName(e.target.value)}
              placeholder="e.g. PAN Card"
              className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm outline-none focus:border-brand" />
          </div>
          <div>
            <label className="text-xs font-medium text-ps-body block mb-1">Category</label>
            <select aria-label="Category" value={category} onChange={e => setCategory(e.target.value as DocCategory)}
              className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm outline-none focus:border-brand">
              {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-ps-body block mb-1">Expiry Date (optional)</label>
            <input type="date" value={expiryDate} onChange={e => setExpiryDate(e.target.value)}
              className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm outline-none focus:border-brand" />
          </div>
          <div>
            <label className="text-xs font-medium text-ps-body block mb-1">File</label>
            <div onClick={() => fileRef.current?.click()}
              className="border-2 border-dashed border-ps-border rounded-lg px-4 py-6 text-center cursor-pointer hover:border-blue-400 transition-colors">
              {file ? (
                <p className="text-sm text-ps-body">{file.name} ({formatBytes(file.size)})</p>
              ) : (
                <p className="text-sm text-ps-hint">Click to select file</p>
              )}
            </div>
            <input ref={fileRef} type="file" className="hidden"
              accept=".pdf,.png,.jpg,.jpeg,.xlsx,.xls,.csv,.doc,.docx,.txt,.zip"
              onChange={e => { if (e.target.files?.[0]) setFile(e.target.files[0]); }} />
          </div>
        </div>
        <div className="flex gap-2 pt-1">
          <button onClick={onClose}
            className="flex-1 border border-ps-border text-ps-body rounded-lg py-2 text-sm hover:bg-ps-bg">
            Cancel
          </button>
          <button onClick={handleUpload} disabled={uploading}
            className="flex-1 bg-brand text-white rounded-lg py-2 text-sm hover:bg-brand-dark disabled:opacity-60">
            {uploading ? "Uploading…" : "Upload"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function ClientDocumentsPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState("");
  const [activeCategory, setActiveCategory] = useState<DocCategory>("Identity");
  const [documents, setDocuments] = useState<ClientDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  // A delete is in flight: one at a time, so a second click cannot send the same delete twice.
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    getClients().then(c => { setClients(c); if (c.length > 0) setClientId(c[0].id); }).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    setError(null);
    try {
      // Asked of the server (POST-A-010): every document of the client, newest first, read in pages of its own (a
      // response is cut at about a thousand rows without a word), with a signed link for each in one request (the
      // bucket is private, so a "public" url is a link that 400s). A refusal or an unreadable body is an error here.
      const res = await api.clientDocuments.list(clientId, true);
      if (!res?.success) throw new Error(res?.error ?? "Failed to load");
      const body = objectWithLists<ClientDocumentList>(res.data, "documents");
      if (!body) throw new Error("The list of documents came back in a shape this screen cannot read.");
      const docs: ClientDocument[] = body.documents.map(d => ({
        ...d,
        doc_type: d.doc_type as DocCategory,
        file_size: d.file_size ?? 0,
        download_url: d.download_url ?? undefined,
      }));
      setDocuments(docs);
      // A document whose link could not be made would show a working-looking button that goes nowhere: say so.
      if (body.without_link > 0) {
        setError(`${body.without_link} of ${body.returned} documents could not be given a link to open; reload to try again.`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function handleDelete(doc: ClientDocument) {
    if (!(await confirmDialog({ message: `Delete "${doc.description ?? doc.file_name}"?`, danger: true, confirmLabel: "Delete" }))) return;
    setDeleting(true);
    try {
      // Asked of the server (POST-A-010): it removes the file and then the record (Partner only) and refuses, with the
      // reason, when something still points at the record; the line leaves the page only after it has said the
      // record is gone.
      await api.clientDocuments.remove(doc.id);
      setDocuments(prev => prev.filter(d => d.id !== doc.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeleting(false);
    }
  }

  const today = todayLocalISO();
  const expiringDocs = documents.filter(d => {
    if (!d.expiry_date) return false;
    return daysUntilExpiry(d.expiry_date) <= 60 && d.expiry_date >= today;
  });

  const categoryDocs = documents.filter(d => d.doc_type === activeCategory);

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-5">
      <PageHeader
        back={{ href: "/clients", label: "Clients" }}
        title="Document Vault"
        subtitle="Organized client document storage"
        actions={
          <>
            <button aria-label="Refresh" onClick={load} className="p-2 rounded-lg border border-ps-border hover:bg-ps-bg text-ps-label">
              <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
            </button>
            <button onClick={() => setShowUpload(true)}
              className="flex items-center gap-2 px-4 py-2 bg-brand text-white text-sm rounded-lg hover:bg-brand-dark">
              <Upload size={15} /> Upload Document
            </button>
          </>
        }
      />

      {/* Client selector */}
      <ClientLookup
        clients={clients}
        value={clientId}
        onChange={setClientId}
        ariaLabel="Client"
        placeholder="Select client…"
      />

      {/* Expiry alert banner */}
      {expiringDocs.length > 0 && (
        <div className="flex items-start gap-3 bg-state-attention-surface border border-state-attention-border rounded-xl px-4 py-3">
          <AlertTriangle size={16} className="text-amber-600 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-amber-800">
              {expiringDocs.length} document{expiringDocs.length > 1 ? "s" : ""} expiring within 60 days
            </p>
            <p className="text-xs text-amber-600 mt-0.5">
              {expiringDocs.map(d => `${d.description ?? d.file_name} (${formatDate(d.expiry_date)})`).join(", ")}
            </p>
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-lg bg-state-attention-surface border border-state-attention-border px-4 py-3 text-sm text-amber-800">{error}</div>
      )}

      {/* Category tabs */}
      <div className="flex gap-1 border-b border-ps-border overflow-x-auto">
        {CATEGORIES.map(cat => {
          const count = documents.filter(d => d.doc_type === cat).length;
          return (
            <button key={cat} onClick={() => setActiveCategory(cat)}
              className={`px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${
                activeCategory === cat ? "border-brand text-blue-600" : "border-transparent text-ps-label hover:text-ps-body"
              }`}>
              {cat} {count > 0 && <span className="ml-1 text-xs text-ps-hint">({count})</span>}
            </button>
          );
        })}
      </div>

      <p className="text-xs text-ps-hint">{CATEGORY_DESC[activeCategory]}</p>

      {loading && <CardGridSkeleton count={3} />}

      {!loading && categoryDocs.length === 0 && (
        <div className="text-center py-12 text-ps-hint">
          <p className="text-sm">No documents in {activeCategory} category</p>
          <button onClick={() => setShowUpload(true)}
            className="mt-3 text-xs text-blue-600 hover:underline">Upload one now</button>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {!loading && categoryDocs.map(doc => {
          const daysLeft = doc.expiry_date ? daysUntilExpiry(doc.expiry_date) : null;
          const isExpiringSoon = daysLeft !== null && daysLeft <= 60 && daysLeft >= 0;
          const isExpired = daysLeft !== null && daysLeft < 0;

          return (
            <div key={doc.id}
              className={`bg-white rounded-xl border p-4 space-y-3 ${isExpired ? "border-state-problem-border" : isExpiringSoon ? "border-state-attention-border" : "border-ps-border"}`}>
              <div className="flex items-start justify-between">
                <div className="min-w-0">
                  <p className="font-medium text-ps-ink text-sm truncate">{doc.description ?? doc.file_name}</p>
                  <p className="text-xs text-ps-hint mt-0.5">{formatBytes(doc.file_size)}</p>
                </div>
                {(isExpiringSoon || isExpired) && (
                  <AlertTriangle size={14} className={isExpired ? "text-state-problem" : "text-amber-500"} />
                )}
              </div>

              <div className="text-xs text-ps-label space-y-1">
                <div>Uploaded: {formatDate(doc.created_at)}</div>
                {doc.expiry_date && (
                  <div className={isExpired ? "text-red-600 font-medium" : isExpiringSoon ? "text-amber-600 font-medium" : ""}>
                    Expires: {formatDate(doc.expiry_date)}
                    {daysLeft !== null && daysLeft >= 0 && ` (${daysLeft} days)`}
                    {isExpired && " (EXPIRED)"}
                  </div>
                )}
              </div>

              <div className="flex gap-2">
                {doc.download_url && (
                  <a href={doc.download_url} target="_blank" rel="noopener noreferrer" download
                    className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 border border-ps-border rounded-lg text-xs text-ps-label hover:bg-ps-bg">
                    <Download size={12} /> Download
                  </a>
                )}
                <button onClick={() => handleDelete(doc)} disabled={deleting}
                  className="flex items-center justify-center gap-1 px-3 py-1.5 border border-red-100 rounded-lg text-xs text-red-600 hover:bg-state-problem-hover disabled:opacity-50">
                  <Trash2 size={12} /> Delete
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {showUpload && clientId && (
        <UploadModal
          clientId={clientId}
          onClose={() => setShowUpload(false)}
          onUploaded={() => { setShowUpload(false); load(); }}
        />
      )}
    </div>
  );
}
