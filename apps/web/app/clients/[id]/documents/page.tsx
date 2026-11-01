"use client";

import { useEffect, useRef, useState } from "react";
import { Upload, Download, Trash2, FolderOpen, X } from "lucide-react";
import { Card } from "@/components/ui/card";
import { TableSkeleton } from "@/components/ui/skeleton";
import { useClientNav, getCurrentFinancialYear } from "@/lib/workspace/ClientNavContext";
import { api } from "@/lib/api";
import { objectWithLists } from "@/lib/api/shape";
import type { ClientDocumentList } from "@/lib/api";
import { writeTimelineEvent } from "@/lib/services/timeline";
import { Callout } from "@/components/ui/callout";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { formatDate } from "@/lib/dates/format";
import { EmptyState } from "@/components/ui/states";
import { EmptyStateAction, EmptyStateActions } from "@/components/ui/empty-state-action";

interface ClientDocument {
  id: string;
  file_name: string;
  // client_documents as it actually is: migration 023 declares
  // label/storage_path/file_size_bytes, but 014 created the table first and
  // 023 uses CREATE TABLE IF NOT EXISTS, so 023 was a silent no-op. The live
  // columns are description/file_path/file_size.
  description: string | null;
  file_path: string;
  file_size: number | null;
  mime_type: string | null;
  created_at: string;
  version: number | null;
  parent_document_id: string | null;
}

/** The document's display name, and the key version history groups on.
 *
 * `description` holds the user-supplied label — this page's upload form makes
 * it required, so anything uploaded here has one. Rows created elsewhere may
 * not, and a null would crash the .toLowerCase() comparisons below and take the
 * page with it, so the file name is the fallback. */
function docLabel(doc: ClientDocument): string {
  return doc.description ?? doc.file_name;
}

function formatFileSize(bytes: number | null): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function DocumentsPage() {
  // A timeline event records WHEN SOMETHING HAPPENED, so its financial year is
  // the one we are actually in. It used to be whatever year the client header
  // was set to, which meant browsing back to FY 2024-25 and then marking a
  // filing done today stamped the event into 2024-25 and hid it from this
  // year's feed. Nothing on this page is filtered by year, so there is no
  // picker to move here — only a wrong value to stop reading.
  const { clientId } = useClientNav();
  const [documents, setDocuments] = useState<ClientDocument[]>([]);
  const [loading, setLoading] = useState(true);
  // Distinguishes "fetch failed" from "client genuinely has no documents" —
  // a masked failure here reads as an empty document store, which it may not be.
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadLabel, setUploadLabel] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [deletingDocId, setDeletingDocId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  // The server's bound on a file, as it served it with the list; the form states it only once it is known.
  const [maxUploadMb, setMaxUploadMb] = useState<number | null>(null);
  const [versionPromptDoc, setVersionPromptDoc] = useState<ClientDocument | null>(null);
  const [showVersionHistory, setShowVersionHistory] = useState<string | null>(null);
  const [versionHistory, setVersionHistory] = useState<ClientDocument[]>([]);
  // This row's request is in flight. These handlers had no loading state at
  // all, so the button was never disabled and a second click sent it again.
  const [rowBusy, setRowBusy] = useState(false);
  // One action at a time: every button that starts work waits for whichever
  // is already running. Guarding each on its own flag alone let two fire at
  // once, and the second could act on what the first was still changing.
  const actionInFlight = rowBusy || uploading;
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function loadDocuments() {
    setRowBusy(true);
    try {
    if (!clientId) return;
    setLoading(true);
    try {
      // Asked of the server (POST-A-010): it reads every document of the client, newest first, in pages of its own
      // (a response is cut at about a thousand rows without a word), after the Documents permission and the client
      // assignment. A refusal or an unreadable body is an error here, never an empty list of documents.
      const res = await api.clientDocuments.list(clientId);
      if (!res?.success) throw new Error(res?.error ?? "Couldn't load documents.");
      const body = objectWithLists<ClientDocumentList>(res.data, "documents");
      if (!body) throw new Error("The list of documents came back in a shape this screen cannot read.");
      const data = body.documents as ClientDocument[];
      setMaxUploadMb(typeof body.max_upload_bytes === "number" ? Math.floor(body.max_upload_bytes / (1024 * 1024)) : null);
      setDocuments(data);
      setLoadError(null);
    } catch (e) {
      setDocuments([]);
      setLoadError(e instanceof Error ? e.message : "Couldn't load documents.");
    } finally {
      setLoading(false);
    }
  } finally { setRowBusy(false); }
  }

  useEffect(() => {
    if (clientId && clientId !== "_placeholder") loadDocuments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId]);

  async function handleUploadDocument(asNewVersion = false, parentDoc: ClientDocument | null = null) {
    if (!uploadFile || !uploadLabel.trim() || !clientId) return;

    if (!asNewVersion && !parentDoc) {
      const existing = documents.find(
        (d) => docLabel(d).toLowerCase() === uploadLabel.trim().toLowerCase() && !d.parent_document_id
      );
      if (existing) { setVersionPromptDoc(existing); return; }
    }

    setUploading(true);
    setUploadError(null);
    try {
      // The server bounds the file, checks its bytes against its type, names it, stores it under the firm and client and
      // writes the record (or removes the file again); a new version names its parent and the server numbers it.
      const form = new FormData();
      form.append("file", uploadFile);
      form.append("client_id", clientId);
      form.append("description", uploadLabel.trim());
      if (parentDoc) form.append("parent_document_id", parentDoc.id);
      await api.clientDocuments.upload(form);

      setShowUploadModal(false);
      setUploadFile(null);
      setUploadLabel("");
      await loadDocuments();

      // Emit timeline event
      try {
        await writeTimelineEvent({
          client_id: clientId,
          financial_year: getCurrentFinancialYear(),
          category: "document",
          event_type: asNewVersion ? "document_version_uploaded" : "document_uploaded",
          severity: "info",
          title: asNewVersion
            ? `New version uploaded: ${uploadLabel.trim()}`
            : `Document uploaded: ${uploadLabel.trim()}`,
          description: `${uploadFile.name} (${formatFileSize(uploadFile.size)})`,
        });
      } catch { /* timeline is non-blocking */ }
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleDownloadDocument(doc: ClientDocument) {
    setRowBusy(true);
    try {
      // A link minted now by the server, after it has checked the document is in the caller's firm and clients.
      const res = await api.clientDocuments.downloadUrl(doc.id);
      if (res?.data?.download_url) window.open(res.data.download_url, "_blank");
      else setActionError(res?.error ?? "The link to this document could not be made.");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "The link to this document could not be made.");
    } finally { setRowBusy(false); }
  }

  async function handleDeleteDocument(doc: ClientDocument) {
    if (!(await confirmDialog({ message: `Delete "${docLabel(doc)}"? This cannot be undone.`, danger: true, confirmLabel: "Delete" }))) return;
    setDeletingDocId(doc.id);
    setActionError(null);
    try {
      // Asked of the server (POST-A-010): it removes the file and then the record (Partner only) and refuses, with the
      // reason, when something still points at the record. The line leaves the page, and the timeline records the
      // deletion, only after the server has said the record is gone; every refusal arrives as the server's own sentence.
      await api.clientDocuments.remove(doc.id);
      setDocuments((prev) => prev.filter((d) => d.id !== doc.id));

      // Emit timeline event
      try {
        await writeTimelineEvent({
          client_id: clientId,
          financial_year: getCurrentFinancialYear(),
          category: "document",
          event_type: "document_deleted",
          severity: "warning",
          title: `Document deleted: ${docLabel(doc)}`,
        });
      } catch { /* timeline is non-blocking */ }
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "This document was not deleted.");
    } finally {
      setDeletingDocId(null);
    }
  }

  async function handleViewVersionHistory(label: string) {
    const history = documents.filter((d) => docLabel(d).toLowerCase() === label.toLowerCase());
    setVersionHistory(history);
    setShowVersionHistory(label);
  }

  return (
    <div className="p-6 max-w-ps-data mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-ps-body">
          Documents ({loading ? "…" : documents.length})
        </h2>
        <button
          onClick={() => { setShowUploadModal(true); setUploadError(null); }}
          className="flex items-center gap-1.5 text-xs bg-brand text-white px-3 py-1.5 rounded-lg hover:bg-brand-dark"
        >
          <Upload size={13} /> Upload Document
        </button>
      </div>

      {actionError && <Callout tone="problem">{actionError}</Callout>}

      {loading ? (
        <TableSkeleton cols={5} rows={5} />
      ) : loadError ? (
        <div className="bg-white rounded-xl border border-state-problem-border px-5 py-12 text-center space-y-2">
          <p className="text-sm text-red-600 font-medium">{loadError}</p>
          <button disabled={actionInFlight} onClick={loadDocuments} className="text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg text-ps-body">Retry</button>
        </div>
      ) : documents.length === 0 ? (
        <div className="bg-white rounded-xl border border-ps-border">
          <EmptyState
            icon={<FolderOpen size={32} />}
            title="No documents uploaded yet"
            description="Keep this client's returns, notices, Form 16 and other files here, with a label so they can be found again."
            action={
              <EmptyStateActions>
                <EmptyStateAction requires={["document", "write"]} icon={<Upload size={14} />} label="Upload Document"
                  onClick={() => { setShowUploadModal(true); setUploadError(null); }} />
              </EmptyStateActions>
            }
          />
        </div>
      ) : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-ps-border text-xs text-ps-hint">
                  <th className="px-5 py-3 text-left font-semibold">Label</th>
                  <th className="px-3 py-3 text-left font-semibold">File Name</th>
                  <th className="px-3 py-3 text-left font-semibold">Size</th>
                  <th className="px-3 py-3 text-left font-semibold">Uploaded</th>
                  <th className="px-5 py-3 text-left font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ps-border">
                {documents.map((doc) => {
                  const versionCount = documents.filter(
                    (d) => docLabel(d).toLowerCase() === docLabel(doc).toLowerCase()
                  ).length;
                  return (
                    <tr key={doc.id} className="hover:bg-ps-bg">
                      <td className="px-5 py-3 text-sm font-medium text-ps-ink">
                        <div className="flex items-center gap-2">
                          {docLabel(doc)}
                          {(doc.version ?? 1) > 1 && (
                            <span className="text-xs bg-blue-50 text-blue-600 px-1.5 py-0.5 rounded font-mono">
                              v{doc.version}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-3 text-xs text-ps-label font-mono max-w-[200px] truncate">
                        {doc.file_name}
                      </td>
                      <td className="px-3 py-3 text-xs text-ps-label">{formatFileSize(doc.file_size)}</td>
                      <td className="px-3 py-3 text-xs text-ps-label whitespace-nowrap">
                        {formatDate(doc.created_at)}
                      </td>
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-2 flex-wrap">
                          <button disabled={actionInFlight}
                            onClick={() => handleDownloadDocument(doc)}
                            className="flex items-center gap-1 text-xs text-blue-600 hover:underline"
                          >
                            <Download size={12} /> Download
                          </button>
                          {versionCount > 1 && (
                            <button
                              onClick={() => handleViewVersionHistory(docLabel(doc))}
                              className="flex items-center gap-1 text-xs text-blue-600 hover:underline"
                            >
                              History
                            </button>
                          )}
                          <button
                            onClick={() => handleDeleteDocument(doc)}
                            disabled={deletingDocId === doc.id}
                            className="flex items-center gap-1 text-xs text-state-problem hover:underline disabled:opacity-40"
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
        <div className="fixed inset-0 bg-brand-dark/60 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-ps-ink">Upload Document</h3>
              <button
                onClick={() => { setShowUploadModal(false); setUploadFile(null); setUploadLabel(""); }}
                className="text-ps-hint hover:text-ps-label"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-ps-body mb-1">Label *</label>
                <input aria-label="Label"
                  type="text"
                  value={uploadLabel}
                  onChange={(e) => setUploadLabel(e.target.value)}
                  placeholder="e.g. GSTR-9 FY 2024-25, ITR AY 2024-25"
                  className="w-full px-3 py-2 text-sm border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-ps-body mb-1">File *{maxUploadMb ? ` (max ${maxUploadMb} MB)` : ""}</label>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.png,.jpg,.jpeg,.xlsx,.xls,.csv,.doc,.docx,.txt,.zip"
                  onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                  className="w-full text-sm text-ps-label file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:text-xs file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
                />
                {uploadFile && (
                  <p className="text-xs text-ps-hint mt-1">{uploadFile.name} — {formatFileSize(uploadFile.size)}</p>
                )}
              </div>
              {uploadError && <Callout tone="problem">{uploadError}</Callout>}
            </div>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => { setShowUploadModal(false); setUploadFile(null); setUploadLabel(""); }}
                className="text-xs px-4 py-2 border border-ps-border rounded-lg hover:bg-ps-bg"
              >
                Cancel
              </button>
              <button
                onClick={() => handleUploadDocument()}
                disabled={actionInFlight || !uploadFile || !uploadLabel.trim()}
                className="text-xs px-4 py-2 bg-brand text-white rounded-lg hover:bg-brand-dark disabled:opacity-40"
              >
                {uploading ? "Uploading…" : "Upload"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Version Prompt Modal */}
      {versionPromptDoc && (
        <div className="fixed inset-0 bg-brand-dark/60 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4">
            <h3 className="text-sm font-semibold text-ps-ink">Document already exists</h3>
            <p className="text-xs text-ps-label">
              A document with the label <strong>{docLabel(versionPromptDoc)}</strong> already exists (v{versionPromptDoc.version ?? 1}).
              Upload as a new version?
            </p>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setVersionPromptDoc(null)} className="text-xs px-4 py-2 border border-ps-border rounded-lg hover:bg-ps-bg">
                Cancel
              </button>
              <button
                onClick={() => { setVersionPromptDoc(null); handleUploadDocument(false, null); }}
                className="text-xs px-4 py-2 border border-ps-border rounded-lg hover:bg-ps-bg"
              >
                Upload as New
              </button>
              <button
                onClick={() => { const doc = versionPromptDoc; setVersionPromptDoc(null); handleUploadDocument(true, doc); }}
                className="text-xs px-4 py-2 bg-brand text-white rounded-lg hover:bg-brand-dark"
              >
                New Version
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Version History Modal */}
      {showVersionHistory && (
        <div className="fixed inset-0 bg-brand-dark/60 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-lg p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-ps-ink">Version History — {showVersionHistory}</h3>
              <button onClick={() => setShowVersionHistory(null)} className="text-ps-hint hover:text-ps-label">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="space-y-2">
              {versionHistory.map((v) => (
                <div key={v.id} className="flex items-center justify-between py-2 border-b border-ps-border last:border-0">
                  <div>
                    <span className="text-xs bg-blue-50 text-blue-600 px-1.5 py-0.5 rounded font-mono mr-2">v{v.version ?? 1}</span>
                    <span className="text-xs text-ps-label">{v.file_name}</span>
                  </div>
                  <span className="text-xs text-ps-hint">
                    {formatDate(v.created_at)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
