"use client";

/**
 * The physical verification of a client's fixed assets: the working paper a CA keeps for the audit (POST-A-112, migration 592).
 *
 * A count is made on one day by someone the client names, and it accounts for every asset the client held on that day. The server
 * decides everything here: which assets the count must account for, the four findings and their words, the tally, whether a finding
 * may be recorded and whether the count may close. Its refusals are shown in its own words. This screen shows the counts, opens one,
 * records a finding per asset and closes a count, after which the count is the working paper and nothing changes it.
 *
 * A finding moves nothing in the register: an asset found elsewhere is moved by recording a movement on the Asset Register (591), and
 * the screen says so beside the finding rather than doing it.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ClipboardCheck, Plus } from "lucide-react";
import { request } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { DateInput } from "@/components/ui/date-input";
import { EmptyState } from "@/components/ui/states";
import { EmptyStateAction, EmptyStateActions } from "@/components/ui/empty-state-action";
import { TableSkeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/lib/auth/AuthContext";
import { useDateProblems } from "@/lib/dates/useDateProblems";
import { formatDate, todayIstISO } from "@/lib/dates/format";

type FindingKind = "found" | "found_elsewhere" | "not_found" | "damaged";
const KINDS: FindingKind[] = ["found", "found_elsewhere", "not_found", "damaged"];

interface Tally { found: number; found_elsewhere: number; not_found: number; damaged: number; to_count: number | null }
interface Count {
  id: string;
  verified_on: string;
  counted_by: string;
  note: string | null;
  status: "open" | "closed";
  closed_on: string | null;
  closed_by_name: string | null;
  tally: Tally;
}
interface Line {
  asset_id: string;
  asset_code: string | null;
  asset_name: string | null;
  location: string | null;
  custodian: string | null;
  held_on_the_day: boolean;
  finding: FindingKind | null;
  found_in: string | null;
  register_location: string | null;
  register_custodian: string | null;
  note: string | null;
  recorded_by: string | null;
}
interface Paper { verification: Count; lines: Line[]; findings: Record<FindingKind, string> }
interface Envelope<T> { success: boolean; data: T | null; error?: string | null }
type Read<T> = { state: "loading" } | { state: "ok"; value: T } | { state: "failed"; message: string };

const said = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);

function isCount(v: unknown): v is Count {
  return typeof v === "object" && v !== null && typeof (v as Count).id === "string" && typeof (v as Count).verified_on === "string"
    && typeof (v as Count).tally === "object" && (v as Count).tally !== null;
}

interface Counts { counts: Count[]; findings: Record<FindingKind, string> }

function readCounts(data: unknown): Counts | null {
  if (typeof data !== "object" || data === null) return null;
  const d = data as Counts;
  return Array.isArray(d.counts) && d.counts.every(isCount) && typeof d.findings === "object" && d.findings !== null ? d : null;
}

function readPaper(data: unknown): Paper | null {
  if (typeof data !== "object" || data === null) return null;
  const d = data as Paper;
  if (!isCount(d.verification) || !Array.isArray(d.lines) || typeof d.findings !== "object" || d.findings === null) return null;
  return d;
}

/** The tally in words; a count that is open says how many assets are left, and a closed one does not (its findings are its record). */
function tallyLine(t: Tally, words: Record<FindingKind, string> | null) {
  const parts = KINDS.map((k) => `${words?.[k] ?? k}: ${t[k]}`);
  if (t.to_count !== null) parts.push(`not yet counted: ${t.to_count}`);
  return parts.join(" · ");
}

export function VerificationTab({ clientId }: { clientId: string }) {
  // Opening a count, recording a finding and closing a count are writes of the client's accounts; a member who may only read sees
  // the counts and their findings, and no control that the server would refuse.
  const { can } = usePermissions();
  const canWrite = can("accounting", "write");
  const [counts, setCounts] = useState<Read<Counts>>({ state: "loading" });
  const countsRun = useRef(0);
  const [chosen, setChosen] = useState<string | null>(null);
  /** The count on screen now, so a write that answers after the person chose another count reloads nothing of the old one. */
  const chosenRef = useRef<string | null>(null);
  chosenRef.current = chosen;
  const [paper, setPaper] = useState<Read<Paper>>({ state: "loading" });
  const paperRun = useRef(0);
  const [starting, setStarting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const loadCounts = useCallback(async () => {
    const run = ++countsRun.current;
    try {
      const j = await request<Envelope<unknown>>(`/api/fixed-assets/verifications?client_id=${encodeURIComponent(clientId)}`);
      const list = j.success ? readCounts(j.data) : null;
      if (run !== countsRun.current) return;
      setCounts(list ? { state: "ok", value: list } : { state: "failed", message: j.error || "The counts could not be read." });
    } catch (e) {
      if (run === countsRun.current) setCounts({ state: "failed", message: said(e, "The counts could not be read.") });
    }
  }, [clientId]);

  /** Reads one count's paper. A quiet read keeps the paper on screen until the new one arrives (after a finding is recorded). */
  const loadPaper = useCallback(async (id: string, quiet = false) => {
    const run = ++paperRun.current;
    if (!quiet) setPaper({ state: "loading" });
    try {
      const j = await request<Envelope<unknown>>(`/api/fixed-assets/verifications/${encodeURIComponent(id)}`);
      const p = j.success ? readPaper(j.data) : null;
      if (run !== paperRun.current) return;
      setPaper(p ? { state: "ok", value: p } : { state: "failed", message: j.error || "The count could not be read." });
    } catch (e) {
      if (run === paperRun.current) setPaper({ state: "failed", message: said(e, "The count could not be read.") });
    }
  }, []);

  useEffect(() => { setCounts({ state: "loading" }); setChosen(null); void loadCounts(); }, [loadCounts]);
  useEffect(() => { if (chosen) void loadPaper(chosen); }, [chosen, loadPaper]);

  const openCount = counts.state === "ok" ? counts.value.counts.find((c) => c.status === "open") ?? null : null;

  return (
    <div className="space-y-4" data-testid="asset-verification">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-ps-ink">Physical verification</h2>
          <p className="text-xs text-ps-hint max-w-2xl">
            A count is made on one day and accounts for every asset the client held that day. Record what was found of each, then
            close the count: a closed count is the working paper and does not change. A finding moves nothing in the register; an
            asset found elsewhere is moved by recording a movement on the Asset Register.
          </p>
        </div>
        {canWrite && counts.state === "ok" && !openCount && !starting && counts.value.counts.length > 0 && (
          <button type="button" onClick={() => { setNotice(null); setStarting(true); }}
            className="shrink-0 flex items-center gap-1.5 text-xs px-3 py-1.5 bg-brand text-white rounded-lg">
            <Plus size={14} /> Start a count
          </button>
        )}
      </div>
      <p role="status" className="text-xs text-state-ready">{notice ?? ""}</p>

      {starting && canWrite && (
        <StartCount clientId={clientId} onCancel={() => setStarting(false)}
          onStarted={(id) => { setStarting(false); setNotice("The count is open. Record what was found of each asset."); void loadCounts(); setChosen(id); }} />
      )}

      {counts.state === "loading" && <TableSkeleton cols={4} rows={3} />}
      {counts.state === "failed" && (
        <p role="alert" className="text-xs text-state-problem">
          {counts.message}{" "}
          <button type="button" onClick={() => { setCounts({ state: "loading" }); void loadCounts(); }} className="underline">Try again</button>
        </p>
      )}
      {counts.state === "ok" && counts.value.counts.length === 0 && !starting && (
        <div className="bg-white rounded-xl border border-ps-border">
          <EmptyState
            icon={<ClipboardCheck size={32} />}
            title="No physical count recorded yet"
            description="Start a count on the day the assets are counted, name who counted them, and record what was found of each asset the client held that day."
            action={
              <EmptyStateActions>
                <EmptyStateAction requires={["accounting", "write"]} icon={<Plus size={14} />} label="Start a count"
                  onClick={() => { setNotice(null); setStarting(true); }} />
              </EmptyStateActions>
            }
          />
        </div>
      )}
      {counts.state === "ok" && counts.value.counts.length > 0 && (
        <ul className="bg-white rounded-xl border border-ps-border divide-y divide-ps-border" aria-label="Physical counts">
          {counts.value.counts.map((c) => (
            <li key={c.id}>
              <button type="button" onClick={() => setChosen(c.id)} aria-pressed={chosen === c.id}
                data-testid={`count-${c.id}`}
                className={`w-full text-left px-4 py-3 text-xs hover:bg-ps-bg ${chosen === c.id ? "bg-ps-bg" : ""}`}>
                <span className="font-medium text-ps-ink">{formatDate(c.verified_on)}</span>
                <span className="text-ps-body"> · counted by {c.counted_by}</span>
                <span className={c.status === "open" ? "text-state-attention" : "text-ps-hint"}>
                  {c.status === "open" ? " · open" : ` · closed on ${c.closed_on ? formatDate(c.closed_on) : "a day not recorded"}`}
                </span>
                <span className="block text-2xs text-ps-hint mt-0.5">
                  {tallyLine(c.tally, counts.value.findings)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {chosen && (paper.state === "loading" || (paper.state === "ok" && paper.value.verification.id !== chosen)) && (
        <TableSkeleton cols={6} rows={4} />
      )}
      {chosen && paper.state === "failed" && (
        <p role="alert" className="text-xs text-state-problem">
          {paper.message}{" "}
          <button type="button" onClick={() => void loadPaper(chosen)} className="underline">Try again</button>
        </p>
      )}
      {chosen && paper.state === "ok" && paper.value.verification.id === chosen && (
        <CountPaper paper={paper.value} canWrite={canWrite}
          onChanged={(countId) => {
            // Only the count still on screen is read again: a write that answers after the person chose another count must not
            // replace that count's paper with this one.
            if (chosenRef.current === countId) void loadPaper(countId, true);
            void loadCounts();
          }} />
      )}
    </div>
  );
}

function StartCount({ clientId, onStarted, onCancel }: { clientId: string; onStarted: (id: string) => void; onCancel: () => void }) {
  const [form, setForm] = useState({ verified_on: "", counted_by: "", note: "" });
  const dates = useDateProblems();
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    if (savingRef.current) return;
    if (dates.first) { dates.refuseWith(setError); return; }
    if (!form.verified_on) { setError("Counted on: enter the day the assets were counted."); return; }
    if (!form.counted_by.trim()) { setError("Counted by: name who counted the assets."); return; }
    savingRef.current = true;
    setSaving(true);
    setError(null);
    try {
      const j = await request<Envelope<{ id: string }>>("/api/fixed-assets/verifications", {
        method: "POST",
        body: JSON.stringify({ client_id: clientId, verified_on: form.verified_on, counted_by: form.counted_by, note: form.note || null }),
      });
      if (!j.success || !j.data) { setError(j.error || "The count was not opened."); return; }
      onStarted(j.data.id);
    } catch (e) {
      setError(said(e, "The count was not opened."));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  return (
    <div className="bg-white rounded-xl border border-ps-border p-4 grid grid-cols-3 gap-3 text-xs" data-testid="start-count">
      <label className="flex flex-col gap-1">
        <span className="text-ps-label">Counted on</span>
        <DateInput id="count-verified-on" value={form.verified_on} notAfter={todayIstISO()}
          onChange={(v) => setForm((f) => ({ ...f, verified_on: v }))}
          onStateChange={dates.watch("countedOn", "Counted on", { afterMax: true })} className="w-full" />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-ps-label">Counted by</span>
        <input aria-label="Counted by" maxLength={200} value={form.counted_by}
          onChange={(e) => setForm((f) => ({ ...f, counted_by: e.target.value }))} className="border border-ps-border rounded px-2 py-1" />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-ps-label">Note (optional)</span>
        <input aria-label="Count note" maxLength={500} value={form.note}
          onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))} className="border border-ps-border rounded px-2 py-1" />
      </label>
      {error && <p role="alert" className="col-span-3 text-state-problem">{error}</p>}
      <div className="col-span-3 flex gap-2">
        <Button variant="plain" size="none" onClick={() => start()} disabled={saving}
          className="px-3 py-1.5 bg-brand text-white rounded disabled:opacity-50">{saving ? "Opening…" : "Open the count"}</Button>
        <button type="button" onClick={onCancel} disabled={saving} className="px-3 py-1.5 border rounded disabled:opacity-50">Cancel</button>
      </div>
    </div>
  );
}

function CountPaper({ paper, canWrite, onChanged }: { paper: Paper; canWrite: boolean; onChanged: (countId: string) => void }) {
  const v = paper.verification;
  const open = v.status === "open";
  const [closing, setClosing] = useState(false);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [error, setError] = useState<string | null>(null);

  async function close() {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    try {
      const j = await request<Envelope<Count>>(`/api/fixed-assets/verifications/${encodeURIComponent(v.id)}/close`, { method: "POST" });
      if (!j.success) { setError(j.error || "The count was not closed."); return; }
      setClosing(false);
      onChanged(v.id);
    } catch (e) {
      setError(said(e, "The count was not closed."));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  return (
    <div className="bg-white rounded-xl border border-ps-border overflow-hidden" data-testid={`count-paper-${v.id}`}>
      <div className="px-4 py-3 border-b border-ps-border text-xs flex items-start justify-between gap-4">
        <div>
          <p className="font-semibold text-ps-ink">
            Count of {formatDate(v.verified_on)}, counted by {v.counted_by}
          </p>
          <p className="text-ps-hint">
            {open ? "Open: findings can be recorded and changed until it is closed."
              : `Closed on ${v.closed_on ? formatDate(v.closed_on) : "a day not recorded"} by ${v.closed_by_name ?? "a member no longer with the firm"}. This is the working paper and does not change; an asset added to the register after it was closed is not on it.`}
          </p>
          {v.note && <p className="text-ps-body mt-1">{v.note}</p>}
          <p className="text-2xs text-ps-hint mt-1">{tallyLine(v.tally, paper.findings)}</p>
        </div>
        {open && canWrite && !closing && (
          <button type="button" onClick={() => { setError(null); setClosing(true); }}
            className="shrink-0 text-xs px-3 py-1.5 border border-ps-border rounded-lg">Close the count</button>
        )}
      </div>
      {open && canWrite && closing && (
        <div className="px-4 py-3 border-b border-ps-border text-xs bg-ps-bg flex items-center gap-3">
          <span className="text-ps-body">Close this count? A closed count cannot be reopened, and its findings cannot change.</span>
          <Button variant="plain" size="none" onClick={() => close()} disabled={busy}
            className="px-3 py-1 bg-brand text-white rounded disabled:opacity-50">{busy ? "Closing…" : "Close it"}</Button>
          <button type="button" onClick={() => setClosing(false)} disabled={busy} className="px-3 py-1 border rounded disabled:opacity-50">Keep it open</button>
        </div>
      )}
      {error && <p role="alert" className="px-4 py-2 text-xs text-state-problem">{error}</p>}
      {paper.lines.length === 0 ? (
        <EmptyState title="Nothing to count on this day"
          description={open ? "The client held no asset on the day counted, so the count can be closed as it is."
            : "This count recorded no finding."} />
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-ps-border text-ps-hint">
              <th className="px-4 py-2 text-left font-semibold">Asset</th>
              <th className="px-3 py-2 text-left font-semibold">The register, on the day counted</th>
              <th className="px-3 py-2 text-left font-semibold">Finding</th>
            </tr>
          </thead>
          <tbody>
            {paper.lines.map((line) => (
              <tr key={line.asset_id} className="border-b border-ps-border align-top" data-testid={`count-line-${line.asset_id}`}>
                <td className="px-4 py-2">
                  <span className="font-medium text-ps-ink">{line.asset_code ?? "No code"}</span>
                  <span className="text-ps-body"> · {line.asset_name ?? "An asset no longer in the register"}</span>
                  {!line.held_on_the_day && open && (
                    <span className="block text-2xs text-state-attention">
                      Since deleted, disposed of, or given a later purchase date, so not held on the day counted; its finding stands.
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-ps-body">
                  {open ? <>at {line.location ?? "no place recorded"}, kept by {line.custodian ?? "nobody named"}</>
                    : <>at {line.register_location ?? "no place recorded"}, kept by {line.register_custodian ?? "nobody named"}</>}
                </td>
                <td className="px-3 py-2">
                  {open && canWrite && line.held_on_the_day
                    ? <FindingEditor countId={v.id} line={line} words={paper.findings} onRecorded={() => onChanged(v.id)} />
                    : <FindingWords line={line} words={paper.findings} />}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function FindingWords({ line, words }: { line: Line; words: Record<FindingKind, string> }) {
  if (!line.finding) return <span className="text-ps-hint">Not counted</span>;
  return (
    <span className="text-ps-body">
      {words[line.finding] ?? line.finding}
      {line.finding === "found_elsewhere" && line.found_in && <> · found in {line.found_in}</>}
      {line.note && <> · {line.note}</>}
      <span className="text-ps-hint"> · recorded by {line.recorded_by ?? "a member no longer with the firm"}</span>
    </span>
  );
}

function FindingEditor({ countId, line, words, onRecorded }: {
  countId: string; line: Line; words: Record<FindingKind, string>; onRecorded: () => void;
}) {
  const [finding, setFinding] = useState<FindingKind | "">(line.finding ?? "");
  const [foundIn, setFoundIn] = useState(line.found_in ?? "");
  const [note, setNote] = useState(line.note ?? "");
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const [error, setError] = useState<string | null>(null);

  async function record() {
    if (savingRef.current) return;
    if (!finding) { setError("Finding: choose what the count found of this asset."); return; }
    savingRef.current = true;
    setSaving(true);
    setError(null);
    try {
      const j = await request<Envelope<unknown>>(
        `/api/fixed-assets/verifications/${encodeURIComponent(countId)}/findings/${encodeURIComponent(line.asset_id)}`,
        { method: "PUT", body: JSON.stringify({ finding, found_in: finding === "found_elsewhere" ? foundIn : null, note: note || null }) },
      );
      if (!j.success) { setError(j.error || "The finding was not recorded."); return; }
      onRecorded();
    } catch (e) {
      setError(said(e, "The finding was not recorded."));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  return (
    <div className="space-y-1">
      {line.finding && <FindingWords line={line} words={words} />}
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label={`Finding for ${line.asset_code ?? line.asset_name ?? "this asset"}`} value={finding}
          onChange={(e) => setFinding(e.target.value as FindingKind | "")} className="border border-ps-border rounded px-2 py-1">
          <option value="">Choose a finding</option>
          {KINDS.map((k) => <option key={k} value={k}>{words[k] ?? k}</option>)}
        </select>
        {finding === "found_elsewhere" && (
          <input aria-label={`Found in for ${line.asset_code ?? line.asset_name ?? "this asset"}`} placeholder="Where it was found"
            maxLength={200} value={foundIn} onChange={(e) => setFoundIn(e.target.value)} className="border border-ps-border rounded px-2 py-1" />
        )}
        <input aria-label={`Note for ${line.asset_code ?? line.asset_name ?? "this asset"}`} placeholder="Note (optional)" maxLength={500}
          value={note} onChange={(e) => setNote(e.target.value)} className="border border-ps-border rounded px-2 py-1" />
        <Button variant="plain" size="none" onClick={() => record()} disabled={saving}
          className="px-3 py-1 bg-brand text-white rounded disabled:opacity-50">{saving ? "Recording…" : line.finding ? "Change" : "Record"}</Button>
      </div>
      {finding === "found_elsewhere" && (
        <p className="text-2xs text-ps-hint">
          The register had it at {line.location ?? "no place recorded"} on the day counted. If it has moved, record the movement on the Asset Register.
        </p>
      )}
      {error && <p role="alert" className="text-2xs text-state-problem">{error}</p>}
    </div>
  );
}
