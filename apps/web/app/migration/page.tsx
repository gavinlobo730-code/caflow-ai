"use client";

import { useEffect, useState } from "react";
import { Plus, Loader2, AlertTriangle, Database, CheckCircle, XCircle } from "lucide-react";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
  uploaded: "bg-[#F1F5F9] text-[#64748B]",
  parsing: "bg-amber-100 text-amber-700",
  parsed: "bg-blue-100 text-blue-700",
  validating: "bg-amber-100 text-amber-700",
  previewing: "bg-purple-100 text-purple-700",
  importing: "bg-orange-100 text-orange-700",
  completed: "bg-green-100 text-green-700",
  rolled_back: "bg-red-100 text-red-700",
  error: "bg-red-100 text-red-700",
};

const IMPORT_TYPES = ["ledgers", "journals", "customers", "vendors", "opening_balances", "masters"];
const FY_OPTIONS = ["2025-26", "2024-25", "2023-24"];

interface MigrationJob {
  id: string;
  name: string;
  source_file_name: string;
  target_financial_year: string;
  status: string;
  total_items: number;
  imported_items: number;
  failed_items: number;
  is_dry_run: boolean;
  created_at: string;
}

export default function MigrationPage() {
  const [jobs, setJobs] = useState<MigrationJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<MigrationJob | null>(null);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  // Create form
  const [name, setName] = useState("");
  const [fileName, setFileName] = useState("");
  const [fy, setFy] = useState(FY_OPTIONS[0]);
  const [xmlContent, setXmlContent] = useState("");
  const [selectedTypes, setSelectedTypes] = useState<string[]>(["ledgers", "journals"]);
  const [step, setStep] = useState<"create" | "parse" | "preview" | "import">("create");
  const [jobId, setJobId] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [parseResult, setParseResult] = useState<Record<string, unknown> | null>(null);
  const [importResult, setImportResult] = useState<Record<string, unknown> | null>(null);
  const [isDryRun, setIsDryRun] = useState(true);

  async function load() {
    setLoading(true);
    const res = await apiFetch("/api/tally-migration/jobs");
    setJobs(res.data ?? []);
    setLoading(false);
  }

  useEffect(() => { load(); }, []);

  async function handleCreate() {
    setWorking(true);
    const res = await apiFetch("/api/tally-migration/jobs", {
      method: "POST",
      body: JSON.stringify({
        name,
        source_file_name: fileName,
        target_financial_year: fy,
        import_types: selectedTypes,
      }),
    });
    if (res.success) {
      setJobId(res.data.id);
      setStep("parse");
      await load();
    }
    setWorking(false);
  }

  async function handleParse() {
    if (!jobId) return;
    setWorking(true);
    const res = await apiFetch(`/api/tally-migration/jobs/${jobId}/parse`, {
      method: "POST",
      body: JSON.stringify({ xml_content: xmlContent }),
    });
    if (res.success) {
      setParseResult(res.data);
      setStep("preview");

      const prevRes = await apiFetch(`/api/tally-migration/jobs/${jobId}/preview`);
      setPreview(prevRes.data);
    }
    setWorking(false);
  }

  async function handleImport() {
    if (!jobId) return;
    setWorking(true);
    const res = await apiFetch(`/api/tally-migration/jobs/${jobId}/import`, {
      method: "POST",
      body: JSON.stringify({ is_dry_run: isDryRun }),
    });
    if (res.success) {
      setImportResult(res.data);
      setStep("import");
      await load();
    }
    setWorking(false);
  }

  function toggleType(t: string) {
    setSelectedTypes(prev => prev.includes(t) ? prev.filter(x => x !== t) : [...prev, t]);
  }

  return (
    <div className="p-6 max-w-4xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-[#1E293B]">Migration Center</h2>
          <p className="text-xs text-[#94A3B8] mt-0.5">Import data from Tally — Masters, Ledgers, Journals, Balances</p>
        </div>
        <button onClick={() => { setShowCreate(true); setStep("create"); setJobId(null); setParseResult(null); setImportResult(null); }}
          className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700">
          <Plus size={12} /> New Import
        </button>
      </div>

      <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-xl px-4 py-2.5">
        <AlertTriangle size={13} className="text-amber-600 flex-shrink-0" />
        <p className="text-xs text-amber-800 font-medium">
          Always run dry-run first. Review preview before importing. Rollback available if needed.
        </p>
      </div>

      {/* Wizard */}
      {showCreate && (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 space-y-4">
          {/* Progress */}
          <div className="flex gap-2">
            {["create", "parse", "preview", "import"].map((s, i) => (
              <div key={s} className="flex items-center gap-1 flex-1">
                <div className={`h-1.5 flex-1 rounded-full ${["create","parse","preview","import"].indexOf(step) >= i ? "bg-blue-500" : "bg-[#E2E8F0]"}`} />
              </div>
            ))}
          </div>
          <div className="flex justify-between text-[9px] text-[#94A3B8]">
            {["Create Job", "Parse XML", "Preview", "Import"].map(l => <span key={l}>{l}</span>)}
          </div>

          {step === "create" && (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[10px] text-[#64748B] mb-1 block">Job Name</label>
                  <input value={name} onChange={e => setName(e.target.value)}
                    className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg" placeholder="e.g. Tally FY2025 Import" />
                </div>
                <div>
                  <label className="text-[10px] text-[#64748B] mb-1 block">Source File Name</label>
                  <input value={fileName} onChange={e => setFileName(e.target.value)}
                    className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg" placeholder="export.xml" />
                </div>
              </div>
              <div>
                <label className="text-[10px] text-[#64748B] mb-1 block">Financial Year</label>
                <select value={fy} onChange={e => setFy(e.target.value)}
                  className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg">
                  {FY_OPTIONS.map(f => <option key={f}>{f}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[10px] text-[#64748B] mb-2 block">Import Types</label>
                <div className="flex flex-wrap gap-2">
                  {IMPORT_TYPES.map(t => (
                    <button key={t} onClick={() => toggleType(t)}
                      className={`text-[10px] px-2 py-1 rounded-full border ${selectedTypes.includes(t) ? "bg-blue-600 text-white border-blue-600" : "border-[#E2E8F0] text-[#64748B]"}`}>
                      {t}
                    </button>
                  ))}
                </div>
              </div>
              <button onClick={handleCreate} disabled={working || !name || !fileName}
                className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg disabled:opacity-50 flex items-center gap-1">
                {working && <Loader2 size={10} className="animate-spin" />} Create Job →
              </button>
            </div>
          )}

          {step === "parse" && (
            <div className="space-y-3">
              <p className="text-xs font-medium text-[#334155]">Paste Tally XML Export</p>
              <p className="text-[11px] text-[#64748B]">
                In Tally: Gateway of Tally → Export → XML. Paste the exported XML content below.
              </p>
              <textarea value={xmlContent} onChange={e => setXmlContent(e.target.value)} rows={12}
                className="w-full text-xs px-3 py-2 border border-[#E2E8F0] rounded-lg font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder='<?xml version="1.0"?><ENVELOPE>...</ENVELOPE>' />
              <button onClick={handleParse} disabled={working || !xmlContent.trim()}
                className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg disabled:opacity-50 flex items-center gap-1">
                {working && <Loader2 size={10} className="animate-spin" />} Parse XML →
              </button>
            </div>
          )}

          {step === "preview" && preview && (
            <div className="space-y-3">
              <p className="text-xs font-medium text-[#334155]">Import Preview</p>
              {parseResult && (
                <div className="grid grid-cols-3 gap-3">
                  {Object.entries((parseResult as any).parsed_counts ?? {}).map(([k, v]) => (
                    <div key={k} className="bg-[#F8FAFC] rounded-lg p-3 text-center">
                      <p className="text-sm font-bold text-[#1E293B]">{v as number}</p>
                      <p className="text-[10px] text-[#64748B] capitalize">{k}</p>
                    </div>
                  ))}
                </div>
              )}
              {(preview as any).error_count > 0 && (
                <div className="flex items-center gap-2 bg-red-50 p-3 rounded-lg">
                  <XCircle size={14} className="text-red-500" />
                  <p className="text-xs text-red-700">{(preview as any).error_count} items have errors — fix before importing</p>
                </div>
              )}
              <div className="flex items-center gap-3">
                <label className="flex items-center gap-2 text-xs text-[#334155]">
                  <input type="checkbox" checked={isDryRun} onChange={e => setIsDryRun(e.target.checked)} />
                  Dry Run (validate without importing)
                </label>
              </div>
              {!isDryRun && (
                <div className="flex items-center gap-2 bg-red-50 border border-red-200 p-3 rounded-lg">
                  <AlertTriangle size={13} className="text-red-500" />
                  <p className="text-xs text-red-700 font-medium">Live import — data will be written. Ensure you have reviewed the preview.</p>
                </div>
              )}
              <button onClick={handleImport} disabled={working || ((preview as any).error_count > 0 && !isDryRun)}
                className={`text-xs px-4 py-2 text-white rounded-lg disabled:opacity-50 flex items-center gap-1 ${isDryRun ? "bg-blue-600 hover:bg-blue-700" : "bg-red-600 hover:bg-red-700"}`}>
                {working && <Loader2 size={10} className="animate-spin" />}
                {isDryRun ? "Run Dry Run →" : "Execute Import →"}
              </button>
            </div>
          )}

          {step === "import" && importResult && (
            <div className="space-y-3">
              <div className="flex items-center gap-2 bg-green-50 border border-green-100 rounded-lg p-4">
                <CheckCircle size={16} className="text-green-500" />
                <div>
                  <p className="text-xs font-semibold text-green-800">
                    {(importResult as any).is_dry_run ? "Dry Run Completed" : "Import Completed"}
                  </p>
                  <p className="text-[10px] text-green-600">
                    {(importResult as any).imported ?? 0} imported · {(importResult as any).failed ?? 0} failed · {(importResult as any).skipped ?? 0} skipped
                  </p>
                </div>
              </div>
              {(importResult as any).is_dry_run && (
                <button onClick={() => { setIsDryRun(false); setStep("preview"); }}
                  className="text-xs px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700">
                  Proceed with Live Import →
                </button>
              )}
              <button onClick={() => { setShowCreate(false); load(); }}
                className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg">Done</button>
            </div>
          )}
        </div>
      )}

      {/* Job List */}
      {loading ? (
        <div className="space-y-2">{[...Array(3)].map((_, i) => <div key={i} className="h-14 bg-[#F8FAFC] rounded-xl animate-pulse" />)}</div>
      ) : jobs.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-16 space-y-2">
          <Database size={28} className="text-gray-200 mx-auto" />
          <p className="text-sm text-[#64748B]">No migration jobs yet</p>
          <p className="text-xs text-[#94A3B8]">Click "New Import" to migrate data from Tally.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {jobs.map(j => (
            <div key={j.id} className="bg-white border border-[#F1F5F9] rounded-xl px-4 py-3 flex items-center gap-3">
              <Database size={16} className="text-blue-500 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-[#1E293B]">{j.name}</p>
                <p className="text-[10px] text-[#94A3B8]">
                  FY {j.target_financial_year} · {j.source_file_name} · {j.total_items} items
                  {j.imported_items > 0 && ` · ${j.imported_items} imported`}
                  {j.is_dry_run && " · Dry Run"}
                </p>
              </div>
              <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full flex-shrink-0 ${STATUS_COLOR[j.status]}`}>
                {j.status.replace(/_/g, " ")}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
