"use client";

import { useEffect, useState, useCallback } from "react";
import { Upload, RefreshCw, Loader2, AlertTriangle, CheckCircle, XCircle } from "lucide-react";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const FY_OPTIONS = ["2025-26", "2024-25", "2023-24"];

async function apiFetch(path: string, opts?: RequestInit) {
  const { supabase } = await import("@/lib/supabase/client");
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts?.headers ?? {}),
    },
  });
  return res.json();
}

function paise(v: number) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(v / 100);
}

interface Upload26AS {
  id: string;
  financial_year: string;
  parse_status: string;
  total_records: number;
  uploaded_at: string;
}

interface Reconciliation {
  total_26as_records: number;
  matched_count: number;
  mismatch_count: number;
  missing_in_books_count: number;
  total_tds_26as_paise: number;
  total_tds_books_paise: number;
  variance_paise: number;
  ai_insight_triggered: boolean;
  status: string;
}

export default function Form26ASPage() {
  // Not useParams(): apps/web is a static export and Cloudflare's 200-rewrite
  // serves the pre-rendered "_placeholder" HTML for every real client URL, so
  // useParams().id was the literal string "_placeholder" — the load below bailed
  // on its own guard and the page rendered permanently empty (no upload history,
  // no reconciliation), while Upload & Parse posted "_placeholder" as client_id.
  // useClientNav reads the real UUID out of window.location.
  const { clientId } = useClientNav();

  const [fy, setFy] = useState(FY_OPTIONS[0]);
  const [uploads, setUploads] = useState<Upload26AS[]>([]);
  const [recon, setRecon] = useState<Reconciliation | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [rawText, setRawText] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const [reconciling, setReconciling] = useState(false);
  const [reconError, setReconError] = useState<string | null>(null);

  // Distinguishes "fetch failed" from "nothing uploaded yet" — a masked
  // failure previously rendered the upload history and reconciliation
  // summary as fully empty with no indication of the actual failure.
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    // Plain reads — routed directly to Supabase (RLS: firm_isolation) instead
    // of through the FastAPI backend, which cold-starts. Mirrors list_uploads
    // and get_reconciliation in apps/api/domain/income_tax/form26as_service.py:
    // get_reconciliation is just the last stored reconciliation row (no
    // recompute) — the actual POST /reconcile matching logic stays backend-routed.
    const supabase = getSupabaseClient();
    const [
      { data: uploadsData, error: uploadsErr },
      { data: reconData, error: reconErr },
    ] = await Promise.all([
      supabase
        .from("form_26as_uploads")
        .select("id, financial_year, parse_status, total_records, uploaded_at")
        .eq("client_id", clientId)
        .eq("financial_year", fy)
        .order("uploaded_at", { ascending: false }),
      supabase
        .from("form_26as_reconciliations")
        .select("total_26as_records, matched_count, mismatch_count, missing_in_books_count, total_tds_26as_paise, total_tds_books_paise, variance_paise, ai_insight_triggered, status")
        .eq("client_id", clientId)
        .eq("financial_year", fy)
        .order("created_at", { ascending: false })
        .limit(1)
        .maybeSingle(),
    ]);
    const firstError = uploadsErr ?? reconErr;
    if (firstError) {
      setUploads([]);
      setRecon(null);
      setLoadError(firstError.message || "Couldn't load Form 26AS data.");
      return;
    }
    setUploads((uploadsData as Upload26AS[]) ?? []);
    setRecon((reconData as Reconciliation | null) ?? null);
    setLoadError(null);
  }, [clientId, fy]);

  useEffect(() => { load(); }, [load]);

  async function handleUploadAndParse() {
    setUploading(true);
    setUploadError(null);
    try {
      // Create upload record
      const uploadRes = await apiFetch("/api/form-26as/uploads", {
        method: "POST",
        body: JSON.stringify({ client_id: clientId, financial_year: fy }),
      });
      if (!uploadRes.success) throw new Error(uploadRes.error ?? "Failed to create upload");

      const uploadId = uploadRes.data.id;

      // Parse the text
      const parseRes = await apiFetch(`/api/form-26as/uploads/${uploadId}/parse`, {
        method: "POST",
        body: JSON.stringify({ raw_text: rawText }),
      });
      if (!parseRes.success) throw new Error(parseRes.error ?? "Parse failed");

      setShowUpload(false);
      setRawText("");
      await load();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleReconcile() {
    setReconciling(true);
    setReconError(null);
    try {
      const res = await apiFetch("/api/form-26as/reconcile", {
        method: "POST",
        body: JSON.stringify({ client_id: clientId, financial_year: fy }),
      });
      if (!res.success) throw new Error(res.error ?? "Reconciliation failed");
      setRecon(res.data);
    } catch (err) {
      setReconError(err instanceof Error ? err.message : "Failed");
    } finally {
      setReconciling(false);
    }
  }

  const parsedUploads = uploads.filter(u => u.parse_status === "parsed");

  return (
    <div className="p-6 max-w-3xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-[#1E293B]">Form 26AS Reconciliation</h2>
          <p className="text-xs text-[#94A3B8] mt-0.5">IT Act §203AA — Annual Tax Statement</p>
        </div>
        <select
          value={fy}
          onChange={e => setFy(e.target.value)}
          className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg"
        >
          {FY_OPTIONS.map(f => <option key={f}>{f}</option>)}
        </select>
      </div>

      <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-xl px-4 py-2.5">
        <AlertTriangle size={13} className="text-amber-600 flex-shrink-0" />
        <p className="text-xs text-amber-800 font-medium">
          CA REVIEW REQUIRED — Review reconciliation results before filing ITR.
        </p>
      </div>

      {loadError && (
        <div className="flex items-center justify-between gap-2 bg-red-50 border border-red-200 rounded-xl px-4 py-2.5">
          <p className="text-xs text-red-700 font-medium">{loadError}</p>
          <button onClick={() => load()} className="text-xs px-3 py-1 border border-red-200 rounded hover:bg-red-100 text-red-700 shrink-0">Retry</button>
        </div>
      )}

      {/* Reconciliation Summary */}
      {recon && (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-[#334155]">Reconciliation Summary</p>
            <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
              recon.status === "completed" ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"
            }`}>{recon.status}</span>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div className="bg-green-50 rounded-lg p-3 text-center">
              <p className="text-lg font-bold text-green-700">{recon.matched_count}</p>
              <p className="text-[10px] text-green-600">Matched</p>
            </div>
            <div className={`rounded-lg p-3 text-center ${recon.mismatch_count > 0 ? "bg-red-50" : "bg-[#F8FAFC]"}`}>
              <p className={`text-lg font-bold ${recon.mismatch_count > 0 ? "text-red-700" : "text-[#334155]"}`}>
                {recon.mismatch_count}
              </p>
              <p className={`text-[10px] ${recon.mismatch_count > 0 ? "text-red-600" : "text-[#64748B]"}`}>Mismatched</p>
            </div>
            <div className={`rounded-lg p-3 text-center ${recon.missing_in_books_count > 0 ? "bg-amber-50" : "bg-[#F8FAFC]"}`}>
              <p className={`text-lg font-bold ${recon.missing_in_books_count > 0 ? "text-amber-700" : "text-[#334155]"}`}>
                {recon.missing_in_books_count}
              </p>
              <p className={`text-[10px] ${recon.missing_in_books_count > 0 ? "text-amber-600" : "text-[#64748B]"}`}>Missing in Books</p>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 text-xs">
            <div>
              <p className="text-[#94A3B8]">26AS TDS Total</p>
              <p className="font-semibold text-[#1E293B]">{paise(recon.total_tds_26as_paise)}</p>
            </div>
            <div>
              <p className="text-[#94A3B8]">Books TDS Total</p>
              <p className="font-semibold text-[#1E293B]">{paise(recon.total_tds_books_paise)}</p>
            </div>
            <div>
              <p className="text-[#94A3B8]">Variance</p>
              <p className={`font-semibold ${recon.variance_paise > 0 ? "text-red-600" : "text-green-600"}`}>
                {paise(recon.variance_paise)}
              </p>
            </div>
          </div>

          {recon.ai_insight_triggered && (
            <div className="flex items-center gap-2 bg-red-50 border border-red-100 rounded-lg p-3">
              <XCircle size={14} className="text-red-500" />
              <p className="text-xs text-red-700">
                AI Insight triggered — variance exceeds 1% threshold. Review before filing.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-3">
        <button
          onClick={() => setShowUpload(true)}
          className="flex items-center gap-1.5 text-xs border border-[#E2E8F0] bg-white px-3 py-2 rounded-lg hover:bg-[#F8FAFC]"
        >
          <Upload size={12} /> Upload 26AS Text
        </button>
        {parsedUploads.length > 0 && (
          <button
            onClick={handleReconcile}
            disabled={reconciling}
            className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {reconciling ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
            Run Reconciliation
          </button>
        )}
      </div>

      {reconError && <p className="text-xs text-red-600">{reconError}</p>}

      {/* Upload Form */}
      {showUpload && (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 space-y-3">
          <p className="text-xs font-semibold text-[#334155]">Upload 26AS Text</p>
          <p className="text-[11px] text-[#64748B]">
            Download Form 26AS from the TRACES portal (tdscpc.gov.in) or via the e-filing portal login, convert PDF to text, and paste below.
          </p>
          <textarea
            value={rawText}
            onChange={e => setRawText(e.target.value)}
            rows={10}
            className="w-full text-xs px-3 py-2 border border-[#E2E8F0] rounded-lg font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Paste Form 26AS text here..."
          />
          {uploadError && <p className="text-xs text-red-600">{uploadError}</p>}
          <div className="flex gap-2 justify-end">
            <button onClick={() => { setShowUpload(false); setRawText(""); }}
              className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded">Cancel</button>
            <button
              onClick={handleUploadAndParse}
              disabled={uploading || !rawText.trim()}
              className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded disabled:opacity-50 flex items-center gap-1"
            >
              {uploading && <Loader2 size={10} className="animate-spin" />}
              Upload &amp; Parse
            </button>
          </div>
        </div>
      )}

      {/* Upload History */}
      {uploads.length > 0 && (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 space-y-3">
          <p className="text-xs font-semibold text-[#334155]">Upload History</p>
          <div className="space-y-2">
            {uploads.map(u => (
              <div key={u.id} className="flex items-center justify-between p-3 bg-[#F8FAFC] rounded-lg">
                <div>
                  <p className="text-xs font-medium text-[#1E293B]">FY {u.financial_year}</p>
                  <p className="text-[10px] text-[#94A3B8]">
                    {new Date(u.uploaded_at).toLocaleDateString("en-IN")} · {u.total_records} records
                  </p>
                </div>
                <div className="flex items-center gap-1.5">
                  {u.parse_status === "parsed"
                    ? <CheckCircle size={12} className="text-green-500" />
                    : <Loader2 size={12} className="text-amber-500 animate-spin" />
                  }
                  <span className={`text-[10px] ${u.parse_status === "parsed" ? "text-green-600" : "text-amber-600"}`}>
                    {u.parse_status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
