"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { Plus, Loader2, AlertTriangle, CheckCircle, XCircle, Code } from "lucide-react";
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

const STATUS_COLOR: Record<string, string> = {
  draft: "bg-[#F1F5F9] text-[#64748B]",
  validation_pending: "bg-amber-100 text-amber-700",
  validation_failed: "bg-red-100 text-red-700",
  validated: "bg-blue-100 text-blue-700",
  reviewed: "bg-green-100 text-green-700",
  filed: "bg-purple-100 text-purple-700",
};

interface XBRLPackage {
  id: string;
  financial_year: string;
  taxonomy_version: string;
  status: string;
  version: number;
  validation_errors: string[];
  missing_tags: string[];
  created_at: string;
}

export default function XBRLPage() {
  const params = useParams<{ id: string }>();
  const clientId = params.id;

  const [packages, setPackages] = useState<XBRLPackage[]>([]);
  const [loading, setLoading] = useState(true);
  // Distinguishes "fetch failed" from "no XBRL packages yet" — the
  // Supabase query's error field used to be destructured away entirely.
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<XBRLPackage | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [fy, setFy] = useState(FY_OPTIONS[0]);
  const [creating, setCreating] = useState(false);
  const [validating, setValidating] = useState(false);

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    // Plain filtered select (xbrl_packages, RLS-scoped to the firm) — no
    // server-side computation, so read directly instead of round-tripping
    // through the FastAPI backend. Mirrors
    // domain/income_tax/xbrl_service.py::list_xbrl_packages (same table,
    // client_id filter, created_at-desc ordering).
    const supabase = getSupabaseClient();
    const { data, error } = await supabase
      .from("xbrl_packages")
      .select("*")
      .eq("client_id", clientId)
      .order("created_at", { ascending: false });
    if (error) {
      setPackages([]);
      setLoadError(error.message || "Couldn't load XBRL packages.");
      setLoading(false);
      return;
    }
    setPackages((data as XBRLPackage[]) ?? []);
    setLoadError(null);
    setLoading(false);
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function handleCreate() {
    setCreating(true);
    const res = await apiFetch("/api/xbrl/packages", {
      method: "POST",
      body: JSON.stringify({ client_id: clientId, financial_year: fy }),
    });
    if (res.success) {
      setShowCreate(false);
      await load();
    }
    setCreating(false);
  }

  async function handleValidate(pkg: XBRLPackage) {
    setValidating(true);
    const res = await apiFetch(`/api/xbrl/packages/${pkg.id}/validate`, { method: "POST" });
    if (res.success) {
      setSelected(res.data);
      await load();
    }
    setValidating(false);
  }

  return (
    <div className="p-6 max-w-3xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-[#1E293B]">XBRL Engine</h2>
          <p className="text-xs text-[#94A3B8] mt-0.5">Companies Act 2013, Schedule III — MCA_2023 taxonomy</p>
        </div>
        <button onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700">
          <Plus size={12} /> New Package
        </button>
      </div>

      <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-xl px-4 py-2.5">
        <AlertTriangle size={13} className="text-red-500 flex-shrink-0" />
        <p className="text-xs font-medium text-red-800">
          CA REVIEW REQUIRED — DO NOT AUTO-FILE XBRL to MCA portal. Partner review mandatory.
        </p>
      </div>

      {showCreate && (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 space-y-3">
          <p className="text-xs font-semibold text-[#334155]">New XBRL Package</p>
          <div>
            <label className="text-[10px] text-[#64748B] mb-1 block">Financial Year</label>
            <select value={fy} onChange={e => setFy(e.target.value)}
              className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg">
              {FY_OPTIONS.map(f => <option key={f}>{f}</option>)}
            </select>
          </div>
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowCreate(false)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded">Cancel</button>
            <button onClick={handleCreate} disabled={creating}
              className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded disabled:opacity-50 flex items-center gap-1">
              {creating && <Loader2 size={10} className="animate-spin" />} Create
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="space-y-2">{[...Array(2)].map((_, i) => <div key={i} className="h-14 bg-[#F8FAFC] rounded-xl animate-pulse" />)}</div>
      ) : loadError ? (
        <div className="bg-white rounded-xl border border-red-200 px-5 py-12 text-center space-y-2">
          <p className="text-sm text-red-600 font-medium">{loadError}</p>
          <button onClick={load} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
        </div>
      ) : packages.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-16 space-y-2">
          <Code size={28} className="text-gray-200 mx-auto" />
          <p className="text-sm text-[#64748B]">No XBRL packages yet</p>
          <p className="text-xs text-[#94A3B8]">Create a package to start XBRL generation.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {packages.map(pkg => (
            <button key={pkg.id}
              onClick={() => setSelected(pkg)}
              className={`w-full bg-white rounded-xl border px-4 py-3 flex items-center gap-3 hover:bg-[#F8FAFC] text-left ${
                selected?.id === pkg.id ? "border-blue-200" : "border-[#F1F5F9]"
              }`}>
              <Code size={16} className="text-blue-500 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-[#1E293B]">FY {pkg.financial_year} — {pkg.taxonomy_version}</p>
                <p className="text-[10px] text-[#94A3B8]">v{pkg.version} · {new Date(pkg.created_at).toLocaleDateString("en-IN")}</p>
              </div>
              <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full flex-shrink-0 ${STATUS_COLOR[pkg.status]}`}>
                {pkg.status.replace(/_/g, " ")}
              </span>
            </button>
          ))}
        </div>
      )}

      {selected && (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-[#334155]">FY {selected.financial_year} Package</p>
            <button onClick={() => setSelected(null)} className="text-[10px] text-[#94A3B8]">Close</button>
          </div>

          {selected.validation_errors.length > 0 && (
            <div className="space-y-1">
              <p className="text-[10px] font-semibold text-red-600">Validation Errors</p>
              {selected.validation_errors.map((e, i) => (
                <div key={i} className="flex items-start gap-1.5">
                  <XCircle size={10} className="text-red-500 mt-0.5 flex-shrink-0" />
                  <p className="text-[10px] text-red-700">{e}</p>
                </div>
              ))}
            </div>
          )}

          {selected.missing_tags.length > 0 && (
            <div className="space-y-1">
              <p className="text-[10px] font-semibold text-amber-600">Missing Mandatory Tags ({selected.missing_tags.length})</p>
              {selected.missing_tags.slice(0, 5).map((t, i) => (
                <div key={i} className="flex items-start gap-1.5">
                  <AlertTriangle size={10} className="text-amber-500 mt-0.5 flex-shrink-0" />
                  <p className="text-[10px] text-amber-700 font-mono">{t}</p>
                </div>
              ))}
              {selected.missing_tags.length > 5 && (
                <p className="text-[10px] text-[#94A3B8]">+{selected.missing_tags.length - 5} more missing tags</p>
              )}
            </div>
          )}

          {selected.status === "validated" && selected.validation_errors.length === 0 && (
            <div className="flex items-center gap-2 bg-green-50 border border-green-100 rounded-lg p-3">
              <CheckCircle size={14} className="text-green-500" />
              <p className="text-xs text-green-700">Package validated — ready for review</p>
            </div>
          )}

          <div className="flex gap-2">
            <button
              onClick={() => handleValidate(selected)}
              disabled={validating}
              className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded-lg disabled:opacity-50 flex items-center gap-1 hover:bg-blue-700"
            >
              {validating && <Loader2 size={10} className="animate-spin" />}
              Run Validation
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
