"use client";

/**
 * Client Document Vault — Organized per-client document storage
 * Files uploaded to Supabase storage: documents/{firm_id}/{client_id}/{filename}
 * Expiry alerts for certificates expiring within 60 days
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { Upload, Download, Trash2, AlertTriangle, ArrowLeft, X, RefreshCw } from "lucide-react";
import Link from "next/link";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { getClients } from "@/lib/data/clients";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import type { Client } from "@/lib/types";

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

interface ClientDocument {
  id: string;
  firm_id: string;
  client_id: string;
  document_name: string;
  category: DocCategory;
  file_path: string;
  file_size: number;
  expiry_date: string | null;
  uploaded_by: string | null;
  created_at: string;
  public_url?: string;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function fmtDate(d: string | null): string {
  if (!d) return "—";
  const [y, m, dd] = d.split("-");
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${dd} ${months[parseInt(m) - 1]} ${y}`;
}

function daysUntilExpiry(expiryDate: string): number {
  const today = new Date();
  const exp = new Date(expiryDate);
  return Math.ceil((exp.getTime() - today.getTime()) / 86400000);
}

interface UploadModalProps {
  onClose: () => void;
  onUploaded: () => void;
  clientId: string;
  firmId: string;
}

function UploadModal({ onClose, onUploaded, clientId, firmId }: UploadModalProps) {
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
      const sb = getSupabaseClient();

      // Get current user for uploaded_by
      const { data: sessionData } = await sb.auth.getSession();
      const userId = sessionData?.session?.user?.id ?? null;

      const filePath = `documents/${firmId}/${clientId}/${Date.now()}_${file.name}`;

      const { error: uploadErr } = await sb.storage
        .from("documents")
        .upload(filePath, file, { upsert: false });

      if (uploadErr) {
        if (uploadErr.message.includes("bucket") || uploadErr.message.includes("not found")) {
          throw new Error("Storage bucket 'documents' not configured. Please contact support.");
        }
        throw new Error(uploadErr.message);
      }

      const { error: insertErr } = await sb.from("client_documents").insert({
        firm_id: firmId,
        client_id: clientId,
        document_name: docName,
        category,
        file_path: filePath,
        file_size: file.size,
        expiry_date: expiryDate || null,
        uploaded_by: userId,
      });

      if (insertErr) throw new Error(insertErr.message);
      onUploaded();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[#0F172A]">Upload Document</h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
        </div>
        {error && <div className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</div>}
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">Document Name</label>
            <input type="text" value={docName} onChange={e => setDocName(e.target.value)}
              placeholder="e.g. PAN Card"
              className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500" />
          </div>
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">Category</label>
            <select value={category} onChange={e => setCategory(e.target.value as DocCategory)}
              className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500">
              {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">Expiry Date (optional)</label>
            <input type="date" value={expiryDate} onChange={e => setExpiryDate(e.target.value)}
              className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500" />
          </div>
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">File</label>
            <div onClick={() => fileRef.current?.click()}
              className="border-2 border-dashed border-[#E2E8F0] rounded-lg px-4 py-6 text-center cursor-pointer hover:border-blue-400 transition-colors">
              {file ? (
                <p className="text-sm text-[#334155]">{file.name} ({formatBytes(file.size)})</p>
              ) : (
                <p className="text-sm text-[#94A3B8]">Click to select file</p>
              )}
            </div>
            <input ref={fileRef} type="file" className="hidden"
              accept=".pdf,.png,.jpg,.jpeg,.xlsx,.xls,.csv,.doc,.docx,.txt,.zip"
              onChange={e => { if (e.target.files?.[0]) setFile(e.target.files[0]); }} />
          </div>
        </div>
        <div className="flex gap-2 pt-1">
          <button onClick={onClose}
            className="flex-1 border border-[#E2E8F0] text-[#334155] rounded-lg py-2 text-sm hover:bg-[#F8FAFC]">
            Cancel
          </button>
          <button onClick={handleUpload} disabled={uploading}
            className="flex-1 bg-blue-600 text-white rounded-lg py-2 text-sm hover:bg-blue-700 disabled:opacity-60">
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
  const [firmId, setFirmId] = useState("");

  useEffect(() => {
    getClients().then(c => { setClients(c); if (c.length > 0) setClientId(c[0].id); }).catch(() => {});
    getFirmId().then(setFirmId).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    if (!clientId || !firmId) return;
    setLoading(true);
    setError(null);
    try {
      const sb = getSupabaseClient();
      const { data, error: err } = await sb.from("client_documents")
        .select("*")
        .eq("firm_id", firmId)
        .eq("client_id", clientId)
        .order("created_at", { ascending: false });

      if (err) {
        if (err.message.includes("does not exist") || err.message.includes("relation")) {
          setError("Document vault not yet set up. Please run database migrations.");
          setDocuments([]);
          return;
        }
        throw new Error(err.message);
      }

      // Get public URLs
      const docs: ClientDocument[] = await Promise.all(
        (data ?? []).map(async (d: ClientDocument) => {
          const { data: urlData } = sb.storage.from("documents").getPublicUrl(d.file_path);
          return { ...d, public_url: urlData?.publicUrl };
        })
      );

      setDocuments(docs);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [clientId, firmId]);

  useEffect(() => { load(); }, [load]);

  async function handleDelete(doc: ClientDocument) {
    if (!confirm(`Delete "${doc.document_name}"?`)) return;
    try {
      const sb = getSupabaseClient();
      await sb.storage.from("documents").remove([doc.file_path]);
      await sb.from("client_documents").delete().eq("id", doc.id);
      setDocuments(prev => prev.filter(d => d.id !== doc.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  }

  const today = new Date().toISOString().split("T")[0];
  const expiringDocs = documents.filter(d => {
    if (!d.expiry_date) return false;
    return daysUntilExpiry(d.expiry_date) <= 60 && d.expiry_date >= today;
  });

  const categoryDocs = documents.filter(d => d.category === activeCategory);

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/clients" className="p-2 rounded-lg border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]">
            <ArrowLeft size={15} />
          </Link>
          <div>
            <h1 className="text-lg md:text-xl font-semibold text-[#0F172A]">Document Vault</h1>
            <p className="text-sm text-[#64748B] mt-0.5">Organized client document storage</p>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={load} className="p-2 rounded-lg border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]">
            <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
          </button>
          <button onClick={() => setShowUpload(true)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">
            <Upload size={15} /> Upload Document
          </button>
        </div>
      </div>

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
        <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
          <AlertTriangle size={16} className="text-amber-600 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-amber-800">
              {expiringDocs.length} document{expiringDocs.length > 1 ? "s" : ""} expiring within 60 days
            </p>
            <p className="text-xs text-amber-600 mt-0.5">
              {expiringDocs.map(d => `${d.document_name} (${fmtDate(d.expiry_date)})`).join(", ")}
            </p>
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800">{error}</div>
      )}

      {/* Category tabs */}
      <div className="flex gap-1 border-b border-[#E2E8F0] overflow-x-auto">
        {CATEGORIES.map(cat => {
          const count = documents.filter(d => d.category === cat).length;
          return (
            <button key={cat} onClick={() => setActiveCategory(cat)}
              className={`px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${
                activeCategory === cat ? "border-blue-600 text-blue-600" : "border-transparent text-[#64748B] hover:text-[#334155]"
              }`}>
              {cat} {count > 0 && <span className="ml-1 text-xs text-[#94A3B8]">({count})</span>}
            </button>
          );
        })}
      </div>

      <p className="text-xs text-[#94A3B8]">{CATEGORY_DESC[activeCategory]}</p>

      {loading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="bg-white rounded-xl border border-[#E2E8F0] p-4 animate-pulse h-32" />
          ))}
        </div>
      )}

      {!loading && categoryDocs.length === 0 && (
        <div className="text-center py-12 text-[#94A3B8]">
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
              className={`bg-white rounded-xl border p-4 space-y-3 ${isExpired ? "border-red-200" : isExpiringSoon ? "border-amber-200" : "border-[#E2E8F0]"}`}>
              <div className="flex items-start justify-between">
                <div className="min-w-0">
                  <p className="font-medium text-[#0F172A] text-sm truncate">{doc.document_name}</p>
                  <p className="text-xs text-[#94A3B8] mt-0.5">{formatBytes(doc.file_size)}</p>
                </div>
                {(isExpiringSoon || isExpired) && (
                  <AlertTriangle size={14} className={isExpired ? "text-red-500" : "text-amber-500"} />
                )}
              </div>

              <div className="text-xs text-[#64748B] space-y-1">
                <div>Uploaded: {fmtDate(doc.created_at.split("T")[0])}</div>
                {doc.expiry_date && (
                  <div className={isExpired ? "text-red-600 font-medium" : isExpiringSoon ? "text-amber-600 font-medium" : ""}>
                    Expires: {fmtDate(doc.expiry_date)}
                    {daysLeft !== null && daysLeft >= 0 && ` (${daysLeft} days)`}
                    {isExpired && " (EXPIRED)"}
                  </div>
                )}
              </div>

              <div className="flex gap-2">
                {doc.public_url && (
                  <a href={doc.public_url} target="_blank" rel="noopener noreferrer" download
                    className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 border border-[#E2E8F0] rounded-lg text-xs text-[#475569] hover:bg-[#F8FAFC]">
                    <Download size={12} /> Download
                  </a>
                )}
                <button onClick={() => handleDelete(doc)}
                  className="flex items-center justify-center gap-1 px-3 py-1.5 border border-red-100 rounded-lg text-xs text-red-600 hover:bg-red-50">
                  <Trash2 size={12} /> Delete
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {showUpload && firmId && clientId && (
        <UploadModal
          clientId={clientId}
          firmId={firmId}
          onClose={() => setShowUpload(false)}
          onUploaded={() => { setShowUpload(false); load(); }}
        />
      )}
    </div>
  );
}
