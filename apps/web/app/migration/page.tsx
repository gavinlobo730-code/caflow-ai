"use client";

import { useEffect, useRef, useState } from "react";
import { Plus, Loader2, AlertTriangle, Database, CheckCircle, XCircle } from "lucide-react";
import { TransactionListSkeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/lib/auth/AuthContext";
import { Can } from "@/components/Can";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { financialYearChoicesAround } from "@/lib/dates/periods";
import { YearPicker } from "@/components/ui/year-picker";
import { api, request } from "@/lib/api";
import { arrayOrEmpty, objectOrNull, objectWithLists } from "@/lib/api/shape";
import {
  ALL_IMPORT_TYPES, importTypeNote, migrationSubtitle, noClientOptionLabel,
} from "@/lib/migration/writtenTypes";

/**
 * ONE CALL, ANSWERED AS DATA OR AS THE SERVER'S SENTENCE.
 *
 * This page used to carry its own `apiFetch` that returned `res.json()` with
 * no status check, and every step then did `if (res.success) {...}` with NO
 * else. So when a live import answered 500 — every live import did, on a
 * TypeError in the router — the button stopped spinning and nothing else
 * happened: no banner, no toast, the job still `previewing`. A network failure
 * was worse: the rejection escaped the handler and the spinner never stopped.
 *
 * A refusal reaches this screen two ways and both become a thrown Error
 * carrying the server's own words: a non-2xx, which `request` already turns
 * into the `detail`/`error` sentence, and HTTP 200 with `success: false`,
 * which this router also uses.
 */
async function call(path: string, opts?: RequestInit): Promise<unknown> {
  const res = objectOrNull<{ success?: boolean; data?: unknown; error?: string | null }>(
    await request<unknown>(path, opts),
  );
  if (!res || res.success === false) {
    throw new Error(res?.error || "The server declined the request.");
  }
  return res.data ?? null;
}

function sentenceOf(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

/** A category the Tally export carried that the job's own Import Types did
 *  not select (sweep-clients-admin-06). `validate_migration_data` only
 *  builds items for the selected types, so a Sundry Creditors ledger parsed
 *  while only "ledgers" and "journals" were picked is never queued or saved
 *  — and the preview grid must not show it as though it will be imported.
 *  `parsedCounts` is keyed by the same plural names as `selectedTypes`
 *  ("customers", "ledgers", …), so no translation is needed. */
function notSelectedForImport(
  parsedCounts: Record<string, number> | undefined,
  selectedTypes: string[],
): Array<{ type: string; count: number }> {
  return Object.entries(parsedCounts ?? {})
    .filter(([type, count]) => count > 0 && !selectedTypes.includes(type))
    .map(([type, count]) => ({ type, count }));
}

/** A job the server has finished with, one way or the other. `importing` and
 *  `previewing` are not: the live import runs in the background after the
 *  request returns, so the first look at the job may still say `previewing`. */
const SETTLED = new Set(["completed", "error", "rolled_back"]);
/** DELETE /api/tally-migration/jobs/{id} refuses these two — the mirror of
 *  domain/tally/migration_service._NOT_DISCARDABLE. 'completed' already wrote
 *  real customer/vendor rows (Roll back undoes those, not Discard) and
 *  'importing' is being written to by the server right now. */
const NOT_DISCARDABLE = new Set(["completed", "importing"]);
const FOLLOW_EVERY_MS = 2_000;
/** How long this screen watches. The import itself does not stop when the
 *  screen does — it runs on the server — so this only decides when to hand
 *  over to the job list. */
const FOLLOW_FOR_MS = 10 * 60_000;
/** One failed poll is a blip, not the import failing. */
const FOLLOW_FAILURES_ALLOWED = 3;

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

const STATUS_COLOR: Record<string, string> = {
  uploaded: "bg-ps-muted text-ps-label",
  parsing: "bg-state-attention-surface text-state-attention",
  parsed: "bg-state-working-surface text-state-working",
  validating: "bg-state-attention-surface text-state-attention",
  previewing: "bg-state-working-surface text-state-working",
  importing: "bg-state-working-surface text-state-working",
  completed: "bg-state-ready-surface text-state-ready",
  rolled_back: "bg-state-problem-surface text-state-problem",
  error: "bg-state-problem-surface text-state-problem",
};

const IMPORT_TYPES: readonly string[] = ALL_IMPORT_TYPES;
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
  /** The server's sentence about the last run: why it failed, or what it did
   *  not write. Composed on the server, rendered as given. */
  run_message?: string | null;
}

interface ParseResult {
  parsed_counts: Record<string, number>;
}

interface ClientOption {
  id: string;
  client_name?: string;
}

interface WithheldIdentifier {
  item_type: string;
  name: string | null;
  reasons: string[];
}

interface MigrationPreviewCount {
  count: number;
}

interface MigrationPreview {
  error_count: number;
  /** What will actually be SAVED and imported, per item type — built from the
   *  validated items (`get_migration_preview`'s own `by_type`), never from a
   *  parse-time count of every category the export happened to contain. */
  by_type?: Record<string, MigrationPreviewCount>;
  withheld_identifiers?: WithheldIdentifier[];
  [key: string]: unknown;
}

interface ImportResult {
  is_dry_run: boolean;
  imported: number;
  failed: number;
  /** Present on a dry run's report; a live run is read back off the JOB,
   *  which records imported and failed and nothing else — so no count is
   *  derived here for it. */
  skipped?: number;
  /** The job's final status on a live run (`completed` or `error`). */
  status?: string;
  message?: string | null;
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
  /** The job as last read while a live import runs in the background. */
  const [progress, setProgress] = useState<MigrationJob | null>(null);
  /** Customers and vendors are a CLIENT's masters, so an import of them has to
   *  name the client — and this form had no way to, so every customer and
   *  vendor item failed at the very end with "this job has no target client".
   *  Which import types need one is the server's rule; it refuses the job
   *  with its own sentence, which is shown as given. */
  const [clients, setClients] = useState<ClientOption[]>([]);
  const [clientId, setClientId] = useState("");
  /** Stops a follow loop once the screen is gone. */
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    let live = true;
    api.clients
      .list()
      .then((res) => {
        if (!live) return;
        const rows = objectOrNull<{ clients?: unknown }>(
          objectOrNull<{ data?: unknown }>(res)?.data,
        )?.clients;
        setClients(arrayOrEmpty<ClientOption>(rows));
      })
      // The picker degrades to "no client", which is what a firm-level ledger
      // import needs anyway; a failed list must not blank the wizard.
      .catch(() => live && setClients([]));
    return () => { live = false; };
  }, []);

  async function load() {
    setLoading(true);
    try {
      setJobs(arrayOrEmpty<MigrationJob>(await call("/api/tally-migration/jobs")));
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
      // `call` throws on a 200 {success: false} as well as on a non-2xx, so a
      // rollback the server declined is never reported as done.
      await call(`/api/tally-migration/jobs/${j.id}/rollback`, { method: "POST" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't roll the import back.");
    } finally {
      setBusyJob(null);
    }
  }

  /** DISCARD AN UNFINISHED JOB (sweep-clients-admin-04).
   *
   *  Once a CA left the New Import wizard, a job's id lived only in this
   *  page's own React state — there was no DELETE on the server to wire a
   *  button to, and no way back into the job either (see resumeJob below).
   *  The server refuses this once the job is `completed` or `importing`
   *  (NOT_DISCARDABLE), so the button is offered only where it would be
   *  honoured; destructive otherwise, so it is confirmed. */
  async function discard(j: MigrationJob) {
    const ok = await confirmDialog({
      title: `Discard ${j.name}?`,
      message:
        "This deletes the job and everything staged for it. Nothing from " +
        "it has been imported, so nothing else is affected. It cannot be undone.",
      confirmLabel: "Discard job",
      danger: true,
    });
    if (!ok) return;
    setBusyJob(j.id);
    setError(null);
    try {
      await call(`/api/tally-migration/jobs/${j.id}`, { method: "DELETE" });
      if (jobId === j.id) {
        setShowCreate(false);
        setJobId(null);
      }
      await load();
    } catch (e) {
      setError(sentenceOf(e, "Couldn't discard the job."));
    } finally {
      setBusyJob(null);
    }
  }

  /** RESUME A JOB FROM THE LIST (sweep-clients-admin-04).
   *
   *  jobId, parseResult and preview lived only in this component's state, so
   *  leaving the wizard — closing the tab, navigating away, or just this
   *  page's own "Done" button — stranded the job: the list showed it, but
   *  clicking it did nothing, and the only doors back in
   *  (GET /jobs/{id} and GET /jobs/{id}/preview) already existed on the
   *  server with nothing on this screen calling them for a job already in
   *  flight. Which step to reopen on comes from the job's own status: a
   *  `previewing` job has items already saved, so its preview is fetched
   *  and shown directly rather than asking the CA to re-paste the export;
   *  an `importing` job resumes the same follow-loop handleImport starts; a
   *  SETTLED job (completed/error/rolled_back) shows the report built from
   *  the job row itself, the same shape followImport builds it in; anything
   *  earlier (uploaded/parsing/parsed/mapping/validating) has no preview to
   *  show yet, so it reopens at the parse step. */
  async function resumeJob(j: MigrationJob) {
    setError(null);
    setJobId(j.id);
    setShowCreate(true);
    setIsDryRun(j.is_dry_run);
    setParseResult(null);
    setPreview(null);
    setImportResult(null);
    setProgress(null);

    if (j.status === "previewing") {
      setStep("preview");
      setWorking(true);
      try {
        setPreview(objectWithLists<MigrationPreview>(
          await call(`/api/tally-migration/jobs/${j.id}/preview`),
          "withheld_identifiers",
        ));
      } catch (e) {
        setError(sentenceOf(e, "Couldn't load the saved preview."));
      } finally {
        setWorking(false);
      }
      return;
    }

    if (j.status === "importing") {
      setStep("import");
      setWorking(true);
      try {
        await followImport(j.id);
      } catch (e) {
        setError(sentenceOf(e, "Couldn't follow the import."));
      } finally {
        setWorking(false);
      }
      await load();
      return;
    }

    if (SETTLED.has(j.status)) {
      setStep("import");
      setImportResult({
        is_dry_run: j.is_dry_run,
        status: j.status,
        imported: j.imported_items ?? 0,
        failed: j.failed_items ?? 0,
        message: j.run_message ?? null,
      });
      return;
    }

    // uploaded / parsing / parsed / mapping / validating — nothing saved to
    // preview yet.
    setStep("parse");
  }

  useEffect(() => { load(); }, []);

  async function handleCreate() {
    setWorking(true);
    setError(null);
    try {
      const job = objectOrNull<MigrationJob>(await call("/api/tally-migration/jobs", {
        method: "POST",
        body: JSON.stringify({
          name,
          source_file_name: fileName,
          target_financial_year: fy,
          import_types: selectedTypes,
          // Omitted rather than sent empty: an empty string is not a client.
          ...(clientId ? { client_id: clientId } : {}),
        }),
      }));
      if (!job?.id) throw new Error("The server did not return the new job.");
      setJobId(job.id);
      setStep("parse");
      await load();
    } catch (e) {
      setError(sentenceOf(e, "Couldn't create the migration job."));
    } finally {
      setWorking(false);
    }
  }

  async function handleParse() {
    if (!jobId) return;
    setWorking(true);
    setError(null);
    try {
      setParseResult(objectOrNull<ParseResult>(await call(`/api/tally-migration/jobs/${jobId}/parse`, {
        method: "POST",
        body: JSON.stringify({ xml_content: xmlContent }),
      })));
      setPreview(objectWithLists<MigrationPreview>(
        await call(`/api/tally-migration/jobs/${jobId}/preview`),
        "withheld_identifiers",
      ));
      setStep("preview");
      // save_migration_items just updated the job's own total_items — reload
      // so the card in the list below stops showing the 0 it was created
      // with (sweep-clients-admin-06).
      await load();
    } catch (e) {
      setError(sentenceOf(e, "Couldn't read the Tally export."));
    } finally {
      setWorking(false);
    }
  }

  /** Watch a LIVE import until the server has finished with it.
   *
   *  The live import is not done when its request returns — the server queues
   *  it and answers `importing` at once, because a real practice's export
   *  outlives an HTTP request. Rendering that answer as "Import Completed ·
   *  0 imported" is what the screen would otherwise do. So the JOB is read
   *  until it settles, and what it settles on — including the server's
   *  sentence when it failed — is what is shown. */
  async function followImport(id: string): Promise<void> {
    const started = Date.now();
    let failures = 0;
    while (mounted.current) {
      await sleep(FOLLOW_EVERY_MS);
      if (!mounted.current) return;
      let job: MigrationJob | null;
      try {
        job = objectOrNull<MigrationJob>(await call(`/api/tally-migration/jobs/${id}`));
        failures = 0;
      } catch (e) {
        failures += 1;
        if (failures >= FOLLOW_FAILURES_ALLOWED) {
          throw new Error(
            `Couldn't read the import's progress (${sentenceOf(e, "no answer")}). ` +
            "It carries on on the server — its status in the list below updates as it goes.");
        }
        continue;
      }
      if (!job) continue;
      setProgress(job);
      if (SETTLED.has(job.status)) {
        setImportResult({
          is_dry_run: false,
          status: job.status,
          imported: job.imported_items ?? 0,
          failed: job.failed_items ?? 0,
          message: job.run_message ?? null,
        });
        return;
      }
      if (Date.now() - started > FOLLOW_FOR_MS) {
        setError(
          "The import is still running. It carries on on the server without this " +
          "screen — its status in the list below updates as it goes.");
        return;
      }
    }
  }

  async function handleImport() {
    if (!jobId) return;
    setWorking(true);
    setError(null);
    setImportResult(null);
    setProgress(null);
    try {
      const report = objectOrNull<ImportResult>(await call(`/api/tally-migration/jobs/${jobId}/import`, {
        method: "POST",
        body: JSON.stringify({ is_dry_run: isDryRun }),
      }));
      if (!report) throw new Error("The server did not report on the import.");
      setStep("import");
      if (report.is_dry_run) {
        setImportResult(report);
      } else {
        await followImport(jobId);
      }
      await load();
    } catch (e) {
      setError(sentenceOf(e, "The import could not be started."));
    } finally {
      setWorking(false);
    }
  }

  function toggleType(t: string) {
    setSelectedTypes(prev => prev.includes(t) ? prev.filter(x => x !== t) : [...prev, t]);
  }

  // What will actually be imported — the SAVED, VALIDATED items
  // (`preview.by_type`), never `parseResult.parsed_counts`, which counts
  // every category the parser found whether or not this job selected it
  // (sweep-clients-admin-06).
  const previewByType = objectOrNull<Record<string, MigrationPreviewCount>>(preview?.by_type) ?? {};
  const notImportedCategories = notSelectedForImport(parseResult?.parsed_counts, selectedTypes);

  return (
    <div className="p-6 max-w-4xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-ps-ink">Migration Center</h2>
          <p className="text-xs text-ps-hint mt-0.5">{migrationSubtitle()}</p>
        </div>
        {canStartImport && (
          <button onClick={() => { setShowCreate(true); setStep("create"); setJobId(null); setParseResult(null); setImportResult(null); setProgress(null); setClientId(""); setError(null); }}
            className="flex items-center gap-1.5 text-xs bg-brand text-white px-3 py-1.5 rounded-lg hover:bg-brand-dark">
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
                <div className={`h-1.5 flex-1 rounded-full ${["create","parse","preview","import"].indexOf(step) >= i ? "bg-brand" : "bg-ps-border"}`} />
              </div>
            ))}
          </div>
          <div className="flex justify-between text-3xs text-ps-hint">
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
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-3xs text-ps-label mb-1 block">Financial Year</label>
                  <YearPicker value={fy} onChange={setFy} size="sm" />
                </div>
                <div>
                  <label className="text-3xs text-ps-label mb-1 block">
                    Client — needed to import customers or vendors
                  </label>
                  <select value={clientId} onChange={e => setClientId(e.target.value)}
                    className="w-full text-xs px-3 py-1.5 border border-ps-border rounded-lg bg-white">
                    <option value="">{noClientOptionLabel()}</option>
                    {clients.map(c => (
                      <option key={c.id} value={c.id}>{c.client_name ?? c.id}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <label className="text-3xs text-ps-label mb-2 block">Import Types</label>
                <div className="flex flex-wrap gap-2">
                  {IMPORT_TYPES.map(t => (
                    <button key={t} onClick={() => toggleType(t)}
                      className={`text-3xs px-2 py-1 rounded-full border ${selectedTypes.includes(t) ? "bg-brand text-white border-brand" : "border-ps-border text-ps-label"}`}>
                      {t}
                      {importTypeNote(t) && (
                        <span className="opacity-70"> · {importTypeNote(t)}</span>
                      )}
                    </button>
                  ))}
                </div>
              </div>
              <button onClick={handleCreate} disabled={working || !name || !fileName}
                className="text-xs px-4 py-2 bg-brand text-white rounded-lg disabled:opacity-50 flex items-center gap-1">
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
                className="w-full text-xs px-3 py-2 border border-ps-border rounded-lg font-mono focus:outline-none focus:ring-2 focus:ring-brand"
                placeholder='<?xml version="1.0"?><ENVELOPE>...</ENVELOPE>' />
              <button onClick={handleParse} disabled={working || !xmlContent.trim()}
                className="text-xs px-4 py-2 bg-brand text-white rounded-lg disabled:opacity-50 flex items-center gap-1">
                {working && <Loader2 size={10} className="animate-spin" />} Parse XML →
              </button>
            </div>
          )}

          {step === "preview" && preview && (
            <div className="space-y-3">
              <p className="text-xs font-medium text-ps-body">Import Preview</p>
              {/* What will be imported — the saved, validated items, never
                  the parser's raw per-category count (sweep-clients-admin-06):
                  a category the job did not select never reaches here. */}
              {Object.keys(previewByType).length > 0 && (
                <div className="grid grid-cols-3 gap-3">
                  {Object.entries(previewByType).map(([k, v]) => (
                    <div key={k} className="bg-ps-bg rounded-lg p-3 text-center">
                      <p className="text-sm font-bold text-ps-ink">{v.count}</p>
                      <p className="text-3xs text-ps-label capitalize">{k.replace(/_/g, " ")}</p>
                    </div>
                  ))}
                </div>
              )}
              {/* Named rather than left to look imported: the export carried
                  these, but this job's own Import Types did not select them,
                  so they were never queued or saved. */}
              {notImportedCategories.length > 0 && (
                <div className="space-y-0.5">
                  {notImportedCategories.map(({ type, count }) => (
                    <p key={type} className="text-3xs text-ps-hint">
                      {count} {type.replace(/_/g, " ")} found — not selected for import
                    </p>
                  ))}
                </div>
              )}
              {preview.error_count > 0 && (
                <div className="flex items-center gap-2 bg-state-problem-surface p-3 rounded-lg">
                  <XCircle size={14} className="text-state-problem" />
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
                  <AlertTriangle size={13} className="text-state-problem" />
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
                  className={`text-xs px-4 py-2 text-white rounded-lg disabled:opacity-50 flex items-center gap-1 ${isDryRun ? "bg-brand hover:bg-brand-dark" : "bg-red-600 hover:bg-red-700"}`}>
                  {working && <Loader2 size={10} className="animate-spin" />}
                  {isDryRun ? "Run Dry Run →" : "Execute Import →"}
                </button>
              </Can>
            </div>
          )}

          {step === "import" && !importResult && working && (
            <div className="flex items-center gap-2 bg-state-working-surface border border-ps-border rounded-lg p-4">
              <Loader2 size={14} className="animate-spin text-state-working" />
              <p className="text-xs text-state-working">
                Importing on the server
                {progress && ` — ${progress.imported_items ?? 0} imported · ${progress.failed_items ?? 0} failed of ${progress.total_items ?? 0}`}
                . You can leave this screen; the import carries on.
              </p>
            </div>
          )}

          {step === "import" && importResult && (
            <div className="space-y-3">
              {importResult.status === "error" ? (
                <div role="alert" className="flex items-start gap-2 bg-state-problem-surface border border-state-problem-border rounded-lg p-4">
                  <XCircle size={16} className="text-state-problem shrink-0 mt-0.5" />
                  <div>
                    <p className="text-xs font-semibold text-state-problem">Import failed</p>
                    <p className="text-3xs text-state-problem">
                      {importResult.imported ?? 0} imported · {importResult.failed ?? 0} failed
                    </p>
                  </div>
                </div>
              ) : (
                <div className="flex items-center gap-2 bg-green-50 border border-green-100 rounded-lg p-4">
                  <CheckCircle size={16} className="text-green-500" />
                  <div>
                    <p className="text-xs font-semibold text-green-800">
                      {importResult.is_dry_run ? "Dry Run Completed" : "Import Completed"}
                    </p>
                    <p className="text-3xs text-green-600">
                      {importResult.imported ?? 0} imported · {importResult.failed ?? 0} failed
                      {importResult.skipped !== undefined && ` · ${importResult.skipped} skipped`}
                    </p>
                  </div>
                </div>
              )}
              {/* The server's own sentence: why the run failed, which items
                  could not be written, or what this importer does not write at
                  all. Rendered as given — the screen composes none of it. */}
              {importResult.message && (
                <p className={`text-xs rounded-lg px-3 py-2 border ${importResult.status === "error"
                  ? "text-state-problem bg-state-problem-surface border-state-problem-border"
                  : "text-state-attention bg-state-attention-surface border-state-attention-border"}`}>
                  {importResult.message}
                </p>
              )}
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
        <div role="alert" className="bg-state-problem-surface border border-state-problem-border rounded-lg px-4 py-3 flex items-start gap-2 text-xs text-state-problem">
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
        <div className="bg-white rounded-xl border border-ps-border text-center py-16 space-y-2">
          <Database size={28} className="text-gray-200 mx-auto" />
          <p className="text-sm text-ps-label">No migration jobs yet</p>
          <p className="text-xs text-ps-hint">Click &quot;New Import&quot; to migrate data from Tally.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {jobs.map(j => (
            <div key={j.id} role="button" tabIndex={0}
              onClick={() => resumeJob(j)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); resumeJob(j); } }}
              className="bg-white border border-ps-border rounded-xl px-4 py-3 flex items-center gap-3 cursor-pointer hover:border-brand/40 focus:outline-none focus:ring-2 focus:ring-brand">
              <Database size={16} className="text-blue-500 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-ps-ink">{j.name}</p>
                <p className="text-3xs text-ps-hint">
                  FY {j.target_financial_year} · {j.source_file_name} · {j.total_items} items
                  {j.imported_items > 0 && ` · ${j.imported_items} imported`}
                  {j.is_dry_run && " · Dry Run"}
                </p>
                {/* Why the last run failed, or what it did not write — the
                    server's sentence. A job that says `error` and nothing else
                    sends somebody to logs they cannot read. */}
                {j.run_message && (
                  <p className={`text-3xs mt-0.5 ${j.status === "error" ? "text-state-problem" : "text-state-attention"}`}>
                    {j.run_message}
                  </p>
                )}
              </div>
              <span className={`text-3xs font-medium px-2 py-0.5 rounded-full flex-shrink-0 ${STATUS_COLOR[j.status]}`}>
                {j.status.replace(/_/g, " ")}
              </span>
              {/* `completed`, not `imported`: `imported` is an ITEM status and
                  no job ever carries it (the job CHECK has no such value), so
                  this button was never shown and the rollback it wraps could
                  not be reached. */}
              {j.status === "completed" && !j.is_dry_run && j.imported_items > 0 && (
                <button onClick={(e) => { e.stopPropagation(); rollback(j); }} disabled={busyJob === j.id}
                  className="text-3xs px-2 py-1 rounded-lg border border-ps-border text-red-600 hover:bg-red-50 disabled:opacity-40 flex-shrink-0">
                  {busyJob === j.id ? "Rolling back…" : "Roll back"}
                </button>
              )}
              {/* Offered wherever the server would honour it — the mirror of
                  DELETE /jobs/{id}'s own refusal (NOT_DISCARDABLE). A
                  'completed' job already has real rows to roll back instead;
                  an 'importing' one is being written to right now. */}
              {canStartImport && !NOT_DISCARDABLE.has(j.status) && (
                <button onClick={(e) => { e.stopPropagation(); discard(j); }} disabled={busyJob === j.id}
                  className="text-3xs px-2 py-1 rounded-lg border border-ps-border text-ps-label hover:bg-ps-bg disabled:opacity-40 flex-shrink-0">
                  {busyJob === j.id ? "Discarding…" : "Discard"}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
