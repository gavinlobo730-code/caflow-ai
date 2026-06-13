"use client";

import { useEffect, useRef, useState } from "react";
import { Upload, Download, Trash2, FolderOpen, X } from "lucide-react";
import { Card } from "@/components/ui/card";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { writeTimelineEvent } from "@/lib/services/timeline";

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

function formatFileSize(bytes: number | null): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function DocumentsPage() {
  const { clientId, financialYear } = useClientNav();
  const [documents, setDocuments] = useState<ClientDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadLabel, setUploadLabel] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [deletingDocId, setDeletingDocId] = useState<string | null>(null);
  const [versionPromptDoc, setVersionPromptDoc] = useState<ClientDocument | null>(null);
  const [showVersionHistory, setShowVersionHistory] = useState<string | null>(null);
  const [versionHistory, setVersionHistory] = useState<ClientDocument[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function loadDocuments() {
    if (!clientId) return;
    setLoading(true);
    try {
      const supabase = getSupabaseClient();
      const { data } = await supabase
        .from("client_documents")
        .select("id, file_name, label, storage_path, file_size_bytes, mime_type, created_at, version, parent_document_id")
        .eq("client_id", clientId)
        .order("created_at", { ascending: false });
      setDocuments(data ?? []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (clientId && clientId !== "_placeholder") loadDocuments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId]);

  async function handleUploadDocument(asNewVersion = false, parentDoc: ClientDocument | null = null) {
    if (!uploadFile || !uploadLabel.trim() || !clientId) return;
    if (uploadFile.size > 50 * 1024 * 1024) { setUploadError("File must be under 50 MB"); return; }

    if (!asNewVersion && !parentDoc) {
      const existing = documents.find(
        (d) => d.label.toLowerCase() === uploadLabel.trim().toLowerCase() && !d.parent_document_id
      );
      if (existing) { setVersionPromptDoc(existing); return; }
    }

    setUploading(true);
    setUploadError(null);
    try {
      const supabase = getSupabaseClient();
      const firmId = await getFirmId();
      const sanitized = uploadFile.name.replace(/[^a-zA-Z0-9._-]/g, "_");
      const uuid = crypto.randomUUID();
      const storagePath = `${firmId}/${clientId}/${uuid}-${sanitized}`;

      const { error: storageErr } = await supabase.storage
        .from("Documents")
        .upload(storagePath, uploadFile, { contentType: uploadFile.type, upsert: false });
      if (storageErr) throw new Error(storageErr.message);

      const versionNum = parentDoc ? (parentDoc.version ?? 1) + 1 : 1;
      const { error: dbErr } = await supabase.from("client_documents").insert({
        firm_id: firmId,
        client_id: clientId,
        file_name: uploadFile.name,
        label: uploadLabel.trim(),
        storage_path: storagePath,
        file_size_bytes: uploadFile.size,
        mime_type: uploadFile.type || null,
        version: versionNum,
        parent_document_id: parentDoc?.id ?? null,
      });
      if (dbErr) {
        await supabase.storage.from("Documents").remove([storagePath]);
        throw new Error(dbErr.message);
      }

      setShowUploadModal(false);
      setUploadFile(null);
      setUploadLabel("");
      await loadDocuments();

      // Emit timeline event
      try {
        await writeTimelineEvent({
          client_id: clientId,
          firm_id: firmId,
          financial_year: financialYear,
          category: "document",
          event_type: asNewVersion ? "document_version_uploaded" : "document_uploaded",
          severity: "info",
          title: asNewVersion
            ? `New version uploaded: ${uploadLabel.trim()}`
            : `Document uploaded: ${uploadLabel.trim()}`,
          description: `${uploadFile.name} (${formatFileSize(uploadFile.size)})`,
          actor_type: "user",
        });
      } catch { /* timeline is non-blocking */ }
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleDownloadDocument(doc: ClientDocument) {
    const supabase = getSupabaseClient();
    const { data } = await supabase.storage.from("Documents").createSignedUrl(doc.storage_path, 60);
    if (data?.signedUrl) window.open(data.signedUrl, "_blank");
  }

  async function handleDeleteDocument(doc: ClientDocument) {
    if (!confirm(`Delete "${doc.label}"? This cannot be undone.`)) return;
    setDeletingDocId(doc.id);
    try {
      const supabase = getSupabaseClient();
      await supabase.storage.from("Documents").remove([doc.storage_path]);
      await supabase.from("client_documents").delete().eq("id", doc.id);
      setDocuments((prev) => prev.filter((d) => d.id !== doc.id));

      // Emit timeline event
      try {
        const firmId = await getFirmId();
        await writeTimelineEvent({
          client_id: clientId,
          firm_id: firmId,
          financial_year: financialYear,
          category: "document",
          event_type: "document_deleted",
          severity: "warning",
          title: `Document deleted: ${doc.label}`,
          actor_type: "user",
        });
      } catch { /* timeline is non-blocking */ }
    } finally {
      setDeletingDocId(null);
    }
  }

  async function handleViewVersionHistory(label: string) {
    const history = documents.filter((d) => d.label.toLowerCase() === label.toLowerCase());
    setVersionHistory(history);
    setShowVersionHistory(label);
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-[#334155]">
          Documents ({loading ? "…" : documents.length})
        </h2>
        <button
          onClick={() => { setShowUploadModal(true); setUploadError(null); }}
          className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"
        >
          <Upload size={13} /> Upload Document
        </button>
      </div>

      {loading ? (
        <div className="h-32 animate-pulse bg-[#F8FAFC] rounded-xl" />
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
                {documents.map((doc) => {
                  const versionCount = documents.filter(
                    (d) => d.label.toLowerCase() === doc.label.toLowerCase()
                  ).length;
                  return (
                    <tr key={doc.id} className="hover:bg-[#F8FAFC]">
                      <td className="px-5 py-3 text-sm font-medium text-[#0F172A]">
                        <div className="flex items-center gap-2">
                          {doc.label}
                          {(doc.version ?? 1) > 1 && (
                            <span className="text-xs bg-blue-50 text-blue-600 px-1.5 py-0.5 rounded font-mono">
                              v{doc.version}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-3 text-xs text-[#64748B] font-mono max-w-[200px] truncate">
                        {doc.file_name}
                      </td>
                      <td className="px-3 py-3 text-xs text-[#64748B]">{formatFileSize(doc.file_size_bytes)}</td>
                      <td className="px-3 py-3 text-xs text-[#64748B] whitespace-nowrap">
                        {new Date(doc.created_at).toLocaleDateString("en-IN", {
                          day: "numeric", month: "short", year: "numeric",
                        })}
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
        <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-[#0F172A]">Upload Document</h3>
              <button
                onClick={() => { setShowUploadModal(false); setUploadFile(null); setUploadLabel(""); }}
                className="text-[#94A3B8] hover:text-[#475569]"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1">Label *</label>
                <input
                  type="text"
                  value={uploadLabel}
                  onChange={(e) => setUploadLabel(e.target.value)}
                  placeholder="e.g. GSTR-9 FY 2024-25, ITR AY 2024-25"
                  className="w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1">File * (max 50 MB)</label>
                <input
                  ref={fileInputRef}
                  type="file"
                  onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                  className="w-full text-sm text-[#475569] file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:text-xs file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
                />
                {uploadFile && (
                  <p className="text-xs text-[#94A3B8] mt-1">{uploadFile.name} — {formatFileSize(uploadFile.size)}</p>
                )}
              </div>
              {uploadError && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{uploadError}</p>}
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
        <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4">
            <h3 className="text-sm font-semibold text-[#0F172A]">Document already exists</h3>
            <p className="text-xs text-[#475569]">
              A document with the label <strong>{versionPromptDoc.label}</strong> already exists (v{versionPromptDoc.version ?? 1}).
              Upload as a new version?
            </p>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setVersionPromptDoc(null)} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">
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
        <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-lg p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-[#0F172A]">Version History — {showVersionHistory}</h3>
              <button onClick={() => setShowVersionHistory(null)} className="text-[#94A3B8] hover:text-[#475569]">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="space-y-2">
              {versionHistory.map((v) => (
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
  );
}
