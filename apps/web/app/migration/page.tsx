"use client";

import { useEffect, useState } from "react";
import { Plus, Loader2, AlertTriangle, Database, CheckCircle, XCircle } from "lucide-react";
import { TransactionListSkeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/lib/auth/AuthContext";
import { Can } from "@/components/Can";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { financialYearChoicesAround } from "@/lib/dates/periods";
import { YearPicker } from "@/components/ui/year-picker";

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
  uploaded: "bg-ps-muted text-ps-label",
  parsing: "bg-amber-100 text-state-attention",
  parsed: "bg-blue-100 text-blue-700",
  validating: "bg-amber-100 text-state-attention",
  previewing: "bg-purple-100 text-purple-700",
  importing: "bg-orange-100 text-orange-700",
  completed: "bg-green-100 text-green-700",
  rolled_back: "bg-red-100 text-state-problem",
  error: "bg-red-100 text-state-problem",
};

const IMPORT_TYPES = ["ledgers", "journals", "customers", "vendors", "opening_balances", "masters"];
// FROM THE CLOCK, NOT A LITERAL. This list ended at a year that is now in the
// past, so the current financial year could not be selected at all — broken on
// 1 April with nothing saying so. `financialYearChoicesAround` is the one
// helper (lib/dates/periods.ts); see
// scripts/a-financial-year-choice-comes-from-the-clock.test.ts.
const FY_OPTIONS = financialYearChoicesAround(null);

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

interface ParseResult {
  parsed_counts: Record<string, number>;
}

interface WithheldIdentifier {
  item_type: string;
  name: string | null;
  reasons: string[];
}

interface MigrationPreview {
  error_count: number;
  withheld_identifiers?: WithheldIdentifier[];
  [key: string]: unknown;
}

interface ImportResult {
  is_dry_run: boolean;
  imported: number;
  failed: number;
  skipped: number;
}

export default function MigrationPage() {
  const [jobs, setJobs] = useState<MigrationJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [preview, setPreview] = useState<MigrationPreview | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  // tally_migration.py: create/parse are rbac("accounting", "write") (Manager+),
  // while BOTH the dry run and the live import go through /jobs/{id}/import,
  // which is rbac("accounting", "approve") — Partner only. The wizard offered
  // every step to everyone, so a Manager could fill in a whole migration and
  // only discover at the last click that importing was never theirs to do.
  const { can } = usePermissions();
  const canStartImport = can("accounting", "write");

  // Create form
  const [name, setName] = useState("");
  const [fileName, setFileName] = useState("");
  const [fy, setFy] = useState(FY_OPTIONS[0]);
  const [xmlContent, setXmlContent] = useState("");
  const [selectedTypes, setSelectedTypes] = useState<string[]>(["ledgers", "journals"]);
  const [step, setStep] = useState<"create" | "parse" | "preview" | "import">("create");
  const [jobId, setJobId] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  // "The job list could not be loaded" vs "no migrations run yet" — the same
  // empty screen otherwise.
  const [loadFailed, setLoadFailed] = useState(false);
  const [parseResult, setParseResult] = useState<ParseResult | null>(null);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [isDryRun, setIsDryRun] = useState(true);
  /** Which job is rolling back, and what went wrong if it did. Separate from
   *  `loadFailed`, which is about the LIST: a rollback that fails must not
   *  make the jobs look unloadable. */
  const [busyJob, setBusyJob] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      const res = await apiFetch("/api/tally-migration/jobs");
      setJobs(res.data ?? []);
      setLoadFailed(false);
    } catch {
      // Was unguarded, so a failed fetch left this page on its skeleton with
      // no way forward but a reload.
      setJobs([]);
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }

  /** UNDO AN IMPORT (24-09-2026).
   *
   *  `POST /api/tally-migration/jobs/{id}/rollback` has existed since the
   *  module was written and NO SCREEN CALLED IT, so a Tally import that
   *  brought in two thousand wrong customers could only be unpicked by hand,
   *  row by row — which is precisely the situation somebody migrating from
   *  Tally is least equipped for.
   *
   *  It deletes only the `customers` and `vendors` rows THIS job created —
   *  the service holds that set explicitly rather than trusting a
   *  caller-supplied table name — checks the job belongs to this firm before
   *  touching anything, and pages the item read, because an unpaged one
   *  stopped after 1000 deletions and reported done.
   *
   *  Destructive and irreversible, so it is confirmed and it says what it will
   *  remove. It is `rbac("accounting", "approve")` on the server; the button
   *  is offered on an IMPORTED job only, because there is nothing to roll back
   *  before that and nothing left after a previous rollback.
   */
  async function rollback(j: MigrationJob) {
    const ok = await confirmDialog({
      title: `Roll back ${j.name}?`,
      message:
        `This permanently deletes the ${j.imported_items} customer and vendor ` +
        `records this import created. Anything you have since posted against ` +
        `them is not touched and will be left pointing at nothing. It cannot ` +
        `be undone.`,
      confirmLabel: "Roll back import",
      danger: true,
    });
    if (!ok) return;
    setBusyJob(j.id);
    setError(null);
    try {
      const res = await apiFetch(`/api/tally-migration/jobs/${j.id}/rollback`, {
        method: "POST",
      });
      // This router answers a refusal as HTTP 200 with {success: false}; an
      // unchecked call would report a rollback the server declined.
      if (!res?.success) {
        setError(res?.error ?? "Couldn't roll the import back.");
        return;
      }
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't roll the import back.");
    } finally {
      setBusyJob(null);
    }
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
          <h2 className="text-sm font-semibold text-ps-ink">Migration Center</h2>
          <p className="text-xs text-ps-hint mt-0.5">Import data from Tally — Masters, Ledgers, Journals, Balances</p>
        </div>
        {canStartImport && (
          <button onClick={() => { setShowCreate(true); setStep("create"); setJobId(null); setParseResult(null); setImportResult(null); }}
            className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700">
            <Plus size={12} /> New Import
          </button>
        )}
      </div>

      <div className="flex items-center gap-2 bg-state-attention-surface border border-state-attention-border rounded-xl px-4 py-2.5">
        <AlertTriangle size={13} className="text-amber-600 flex-shrink-0" />
        <p className="text-xs text-amber-800 font-medium">
          Always run dry-run first. Review preview before importing. Rollback available if needed.
        </p>
      </div>

      {/* Wizard */}
      {showCreate && (
        <div className="bg-white border border-ps-border rounded-xl p-5 space-y-4">
          {/* Progress */}
          <div className="flex gap-2">
            {["create", "parse", "preview", "import"].map((s, i) => (
              <div key={s} className="flex items-center gap-1 flex-1">
                <div className={`h-1.5 flex-1 rounded-full ${["create","parse","preview","import"].indexOf(step) >= i ? "bg-blue-500" : "bg-ps-border"}`} />
              </div>
            ))}
          </div>
          <div className="flex justify-between text-[9px] text-ps-hint">
            {["Create Job", "Parse XML", "Preview", "Import"].map(l => <span key={l}>{l}</span>)}
          </div>

          {step === "create" && (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-3xs text-ps-label mb-1 block">Job Name</label>
                  <input value={name} onChange={e => setName(e.target.value)}
                    className="w-full text-xs px-3 py-1.5 border border-ps-border rounded-lg" placeholder="e.g. Tally FY2025 Import" />
                </div>
                <div>
                  <label className="text-3xs text-ps-label mb-1 block">Source File Name</label>
                  <input value={fileName} onChange={e => setFileName(e.target.value)}
                    className="w-full text-xs px-3 py-1.5 border border-ps-border rounded-lg" placeholder="export.xml" />
                </div>
              </div>
              <div>
                <label className="text-3xs text-ps-label mb-1 block">Financial Year</label>
                <YearPicker value={fy} onChange={setFy} size="sm" />
              </div>
              <div>
                <label className="text-3xs text-ps-label mb-2 block">Import Types</label>
                <div className="flex flex-wrap gap-2">
                  {IMPORT_TYPES.map(t => (
                    <button key={t} onClick={() => toggleType(t)}
                      className={`text-3xs px-2 py-1 rounded-full border ${selectedTypes.includes(t) ? "bg-blue-600 text-white border-blue-600" : "border-ps-border text-ps-label"}`}>
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
              <p className="text-xs font-medium text-ps-body">Paste Tally XML Export</p>
              <p className="text-2xs text-ps-label">
                In Tally: Gateway of Tally → Export → XML. Paste the exported XML content below.
              </p>
              <textarea value={xmlContent} onChange={e => setXmlContent(e.target.value)} rows={12}
                className="w-full text-xs px-3 py-2 border border-ps-border rounded-lg font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder='<?xml version="1.0"?><ENVELOPE>...</ENVELOPE>' />
              <button onClick={handleParse} disabled={working || !xmlContent.trim()}
                className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg disabled:opacity-50 flex items-center gap-1">
                {working && <Loader2 size={10} className="animate-spin" />} Parse XML →
              </button>
            </div>
          )}

          {step === "preview" && preview && (
            <div className="space-y-3">
              <p className="text-xs font-medium text-ps-body">Import Preview</p>
              {parseResult && (
                <div className="grid grid-cols-3 gap-3">
                  {Object.entries(parseResult.parsed_counts ?? {}).map(([k, v]) => (
                    <div key={k} className="bg-ps-bg rounded-lg p-3 text-center">
                      <p className="text-sm font-bold text-ps-ink">{v as number}</p>
                      <p className="text-3xs text-ps-label capitalize">{k}</p>
                    </div>
                  ))}
                </div>
              )}
              {preview.error_count > 0 && (
                <div className="flex items-center gap-2 bg-state-problem-surface p-3 rounded-lg">
                  <XCircle size={14} className="text-red-500" />
                  <p className="text-xs text-state-problem">{preview.error_count} items have errors — fix before importing</p>
                </div>
              )}
              {/* A customer or vendor whose GSTIN or PAN cannot be read is
                  still imported — the name, address and email are fine, and
                  refusing the job would make a migration impossible for the
                  legacy books that most need one. The identifier is held
                  back, and this is where the CA is told which parties to
                  re-key. The whole list, never a slice: every row is an
                  action. */}
              {(preview.withheld_identifiers ?? []).length > 0 && (
                <div className="bg-state-attention-surface border border-state-attention-border rounded-lg p-3 space-y-2">
                  <div className="flex items-center gap-2">
                    <AlertTriangle size={13} className="text-amber-600 shrink-0" />
                    <p className="text-xs font-medium text-amber-900">
                      {preview.withheld_identifiers!.length} part
                      {preview.withheld_identifiers!.length === 1 ? "y" : "ies"} will
                      be imported without an identifier
                    </p>
                  </div>
                  <ul className="space-y-1.5 max-h-56 overflow-y-auto">
                    {preview.withheld_identifiers!.map((w, i) => (
                      <li key={i} className="text-3xs text-amber-900">
                        <span className="font-medium">{w.name || "(unnamed)"}</span>
                        <span className="text-state-attention"> · {w.item_type}</span>
                        {w.reasons.map((r, j) => (
                          <p key={j} className="text-amber-800 pl-2">{r}</p>
                        ))}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="flex items-center gap-3">
                <label className="flex items-center gap-2 text-xs text-ps-body">
                  <input type="checkbox" checked={isDryRun} onChange={e => setIsDryRun(e.target.checked)} />
                  Dry Run (validate without importing)
                </label>
              </div>
              {!isDryRun && (
                <div className="flex items-center gap-2 bg-state-problem-surface border border-state-problem-border p-3 rounded-lg">
                  <AlertTriangle size={13} className="text-red-500" />
                  <p className="text-xs text-state-problem font-medium">Live import — data will be written. Ensure you have reviewed the preview.</p>
                </div>
              )}
              {/* An explanation rather than a vanished button: this is the last
                  step of a wizard the user has already filled in, so silence
                  here reads as a broken screen. */}
              <Can resource="accounting" action="approve" fallback={
                <p className="text-xs text-ps-label border border-ps-border rounded-lg px-3 py-2">
                  Running an import — including a dry run — requires Partner approval rights.
                  The job is saved; ask a Partner to run it from this screen.
                </p>
              }>
                <button onClick={handleImport} disabled={working || (preview.error_count > 0 && !isDryRun)}
                  className={`text-xs px-4 py-2 text-white rounded-lg disabled:opacity-50 flex items-center gap-1 ${isDryRun ? "bg-blue-600 hover:bg-blue-700" : "bg-red-600 hover:bg-red-700"}`}>
                  {working && <Loader2 size={10} className="animate-spin" />}
                  {isDryRun ? "Run Dry Run →" : "Execute Import →"}
                </button>
              </Can>
            </div>
          )}

          {step === "import" && importResult && (
            <div className="space-y-3">
              <div className="flex items-center gap-2 bg-green-50 border border-green-100 rounded-lg p-4">
                <CheckCircle size={16} className="text-green-500" />
                <div>
                  <p className="text-xs font-semibold text-green-800">
                    {importResult.is_dry_run ? "Dry Run Completed" : "Import Completed"}
                  </p>
                  <p className="text-3xs text-green-600">
                    {importResult.imported ?? 0} imported · {importResult.failed ?? 0} failed · {importResult.skipped ?? 0} skipped
                  </p>
                </div>
              </div>
              {importResult.is_dry_run && (
                <Can resource="accounting" action="approve">
                  <button onClick={() => { setIsDryRun(false); setStep("preview"); }}
                    className="text-xs px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700">
                    Proceed with Live Import →
                  </button>
                </Can>
              )}
              <button onClick={() => { setShowCreate(false); load(); }}
                className="text-xs px-4 py-2 border border-ps-border rounded-lg">Done</button>
            </div>
          )}
        </div>
      )}

      {error && (
        <div role="alert" className="bg-state-problem-surface border border-red-100 rounded-lg px-4 py-3 flex items-start gap-2 text-xs text-red-600">
          <AlertTriangle size={14} className="shrink-0 mt-0.5" />
          <span className="flex-1">{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600">Dismiss</button>
        </div>
      )}

      {/* Job List */}
      {loading ? (
        <TransactionListSkeleton rows={3} />
      ) : loadFailed ? (
        <div className="bg-white rounded-xl border border-red-100 text-center py-16 space-y-2">
          <Database size={28} className="text-red-200 mx-auto" />
          <p className="text-sm text-ps-label">Couldn&apos;t load your migration jobs.</p>
          <button onClick={load} className="text-xs text-blue-600 hover:underline">Try again</button>
        </div>
      ) : jobs.length === 0 ? (
        <div className="bg-white rounded-xl border border-ps-muted text-center py-16 space-y-2">
          <Database size={28} className="text-gray-200 mx-auto" />
          <p className="text-sm text-ps-label">No migration jobs yet</p>
          <p className="text-xs text-ps-hint">Click &quot;New Import&quot; to migrate data from Tally.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {jobs.map(j => (
            <div key={j.id} className="bg-white border border-ps-muted rounded-xl px-4 py-3 flex items-center gap-3">
              <Database size={16} className="text-blue-500 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-ps-ink">{j.name}</p>
                <p className="text-3xs text-ps-hint">
                  FY {j.target_financial_year} · {j.source_file_name} · {j.total_items} items
                  {j.imported_items > 0 && ` · ${j.imported_items} imported`}
                  {j.is_dry_run && " · Dry Run"}
                </p>
              </div>
              <span className={`text-3xs font-medium px-2 py-0.5 rounded-full flex-shrink-0 ${STATUS_COLOR[j.status]}`}>
                {j.status.replace(/_/g, " ")}
              </span>
              {j.status === "imported" && !j.is_dry_run && (
                <button onClick={() => rollback(j)} disabled={busyJob === j.id}
                  className="text-3xs px-2 py-1 rounded-lg border border-ps-border text-red-600 hover:bg-red-50 disabled:opacity-40 flex-shrink-0">
                  {busyJob === j.id ? "Rolling back…" : "Roll back"}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
