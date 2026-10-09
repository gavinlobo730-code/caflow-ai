"use client";

/**
 * GSTR-2B FOR MANY CLIENTS AT ONCE — drop the month's files, each goes to the
 * client whose GSTIN is inside it (gst-10).
 *
 * A practice with sixty clients downloads sixty 2B files in one sitting. They
 * used to be reconciled from sixty client tabs, the CA choosing the client
 * BEFORE the file, although every file already says whose it is. This takes the
 * drop, sends each file to the server, and lists one result per file.
 *
 * NOTHING IS DECIDED HERE. Whose a file is, which month it is for, whether the
 * caller may see that client and what the reconciliation found are all the
 * server's (`domain/gst/gstr2b_routing`, `gstr2b_intake`,
 * `services/gst_2b_bulk_service`). This sends the file and nothing else — no
 * client and no month, because there is no box here to type either — and shows
 * the server's status and sentence for each. A file the browser cannot read as
 * JSON never leaves it; its row is made here, in the reader's own words.
 *
 * ONE FILE PER REQUEST, IN TURN. `lib/api` aborts a request at 45 seconds and
 * never retries it, and a month's 2B for a busy client is several megabytes
 * reconciled across a Singapore-to-Mumbai link. So each request is bounded, a
 * failure costs one file and the rest carry on, and there is no background job
 * to lose on a restart. Stopping is honoured BETWEEN files: a request already
 * sent is not unsent, and the rows that were not started say so.
 *
 * AN ABSENT ROW IS NOT A CLEAN ONE. A file that was not reconciled is listed
 * with why, and nothing about it was stored; a reconciliation that replaced an
 * earlier one says so, so an older download dropped among sixty cannot
 * overwrite a newer one without a word.
 *
 * Nothing is sent to any portal.
 */

import { useRef, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Gstr2bBulkResult, Gstr2bBulkStatus } from "@/lib/api";
import { objectWithLists } from "@/lib/api/shape";
import type { Gstr2bBulkAnswer } from "@/lib/api";
import { readGstr2bText } from "@/lib/gst/gstr2bFile";
import { gstPeriodLabel } from "@/lib/gst/period";
import { formatIstLabelled } from "@/lib/dates/formatIst";
import { formatPaise } from "@/lib/money/format";

type RowState = "waiting" | "reading" | "reconciling" | "done" | "skipped";

interface Row {
  id: number;
  name: string;
  state: RowState;
  result: Gstr2bBulkResult | null;
}

/** What a status is called. Presentation only: the SERVER chose the status. */
const STATUS: Record<Gstr2bBulkStatus, { label: string; tone: string }> = {
  reconciled: { label: "Reconciled", tone: "text-state-ready" },
  unmatched_gstin: { label: "No client holds this GSTIN", tone: "text-state-problem" },
  ambiguous_gstin: { label: "More than one client holds it", tone: "text-state-problem" },
  refused: { label: "Not reconciled", tone: "text-state-problem" },
  unreadable: { label: "Unreadable", tone: "text-state-problem" },
  failed: { label: "Failed", tone: "text-state-problem" },
};

const WAITING_LABEL: Record<Exclude<RowState, "done">, string> = {
  waiting: "Waiting",
  reading: "Reading the file…",
  reconciling: "Reconciling…",
  skipped: "Not started — stopped",
};

/** A row for a file the BROWSER could not read: the reader's own sentence, and
 *  the same shape the server answers, so the table renders one kind of row. */
function unreadable(name: string, reason: string): Gstr2bBulkResult {
  return {
    name, status: "unreadable", reason, gstin: "", period: null, client_id: null,
    client_name: null, needs_attention: false, summary: null, problems: [],
    registration_caveat: null, replaced_earlier: null,
  };
}

function failed(name: string, reason: string): Gstr2bBulkResult {
  return { ...unreadable(name, reason), status: "failed" };
}

export function BulkGstr2bPanel() {
  const fileRef = useRef<HTMLInputElement | null>(null);
  const stopRef = useRef(false);
  const [rows, setRows] = useState<Row[]>([]);
  const [running, setRunning] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  function patch(id: number, change: Partial<Row>) {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...change } : r)));
  }

  async function run(files: File[]) {
    if (running || files.length === 0) return;
    stopRef.current = false;
    setRunning(true);
    // The flag comes down in a `finally`: a throw anywhere below must not leave
    // the drop disabled until the page is reloaded.
    try {
      setRows(files.map((f, i) => ({
        id: i, name: f.name, state: "waiting" as const, result: null,
      })));

      for (let i = 0; i < files.length; i++) {
        if (stopRef.current) {
          for (let j = i; j < files.length; j++) patch(j, { state: "skipped" });
          break;
        }
        const file = files[i];
        patch(i, { state: "reading" });
        let result: Gstr2bBulkResult;
        try {
          let text: string;
          try {
            text = await file.text();
          } catch {
            patch(i, { state: "done", result: unreadable(file.name, "That file could not be read.") });
            continue;
          }
          const read = readGstr2bText(text);
          if (!read.ok) {
            patch(i, { state: "done", result: unreadable(file.name, read.error) });
            continue;
          }
          patch(i, { state: "reconciling" });
          const resp = await api.gstWorkspace.reconcileGstr2bFiles([
            { name: file.name, raw_data: read.raw },
          ]);
          const answer = resp.success
            ? objectWithLists<Gstr2bBulkAnswer>(resp.data, "results") : null;
          result = answer?.results[0]
            ?? failed(file.name, resp.error ?? "The server gave no answer for this file.");
        } catch (e) {
          result = failed(file.name,
            e instanceof Error ? e.message : "This file could not be reconciled.");
        }
        patch(i, { state: "done", result });
      }
    } finally {
      setRunning(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const done = rows.filter((r) => r.result);
  const count = (s: Gstr2bBulkStatus) => done.filter((r) => r.result?.status === s).length;
  const attention = done.filter((r) => r.result?.needs_attention).length;

  return (
    <div className="bg-white rounded-xl border border-ps-border p-4 space-y-3"
      data-testid="bulk-gstr2b">
      <div>
        <h2 className="text-sm font-semibold text-ps-ink">GSTR-2B for many clients</h2>
        <p className="text-xs text-ps-hint mt-0.5">
          Drop the .json files exactly as downloaded from the portal. Each one
          is matched to the client whose GSTIN it names, and the month is read
          from the file — there is nothing to choose or type. A file that
          belongs to no client of yours is listed and not stored.
        </p>
      </div>

      <div
        data-testid="bulk-gstr2b-dropzone"
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          void run(Array.from(e.dataTransfer.files ?? []));
        }}
        className={`border-2 border-dashed rounded-xl p-5 text-center transition-colors ${
          dragOver ? "border-blue-400 bg-blue-50/30" : "border-ps-border-strong"}`}>
        <p className="text-sm font-medium text-ps-body">
          Drop the month&apos;s GSTR-2B files here
        </p>
        <label className="inline-block mt-2 px-3 py-1.5 border rounded text-sm cursor-pointer hover:bg-ps-bg focus-within:ring-2 focus-within:ring-blue-400">
          Choose files
          <input ref={fileRef} type="file" multiple accept=".json,application/json"
            aria-label="GSTR-2B JSON files" className="sr-only" disabled={running}
            onChange={(e) => { void run(Array.from(e.target.files ?? [])); }} />
        </label>
      </div>

      {rows.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-ps-label" data-testid="bulk-gstr2b-totals" aria-live="polite">
              {done.length} of {rows.length} file(s) done
              {" · "}{count("reconciled")} reconciled
              {attention > 0 ? ` (${attention} need a look)` : ""}
              {count("unmatched_gstin") + count("ambiguous_gstin") > 0
                ? ` · ${count("unmatched_gstin") + count("ambiguous_gstin")} matched no single client`
                : ""}
              {count("unreadable") + count("refused") + count("failed") > 0
                ? ` · ${count("unreadable") + count("refused") + count("failed")} not reconciled`
                : ""}
            </p>
            {running && (
              <button type="button" onClick={() => { stopRef.current = true; }}
                className="px-2 py-1 border rounded text-xs hover:bg-ps-bg">
                Stop after this file
              </button>
            )}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-ps-hint border-b">
                <tr>
                  <th className="text-left py-1.5 pr-3 font-medium">File</th>
                  <th className="text-left py-1.5 pr-3 font-medium">Client</th>
                  <th className="text-left py-1.5 pr-3 font-medium">Month</th>
                  <th className="text-left py-1.5 pr-3 font-medium">Result</th>
                  <th className="text-left py-1.5 font-medium">What it found</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <ResultRow key={r.id} row={r} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function ResultRow({ row }: { row: Row }) {
  const res = row.result;
  if (!res) {
    return (
      <tr className="border-b last:border-0">
        <td className="py-1.5 pr-3">{row.name}</td>
        <td className="py-1.5 pr-3 text-ps-hint">—</td>
        <td className="py-1.5 pr-3 text-ps-hint">—</td>
        <td className="py-1.5 pr-3 text-ps-label" colSpan={2}>
          {WAITING_LABEL[row.state as Exclude<RowState, "done">]}
        </td>
      </tr>
    );
  }
  const s = res.summary;
  const tone = STATUS[res.status] ?? STATUS.failed;
  return (
    <tr className="border-b last:border-0 align-top" data-status={res.status}>
      <td className="py-1.5 pr-3">
        {res.name}
        {res.gstin && <span className="block text-3xs text-ps-hint">{res.gstin}</span>}
      </td>
      <td className="py-1.5 pr-3">
        {res.client_id ? (
          <Link href={`/clients/${res.client_id}/compliance/gst`} className="underline">
            {res.client_name || "Open client"}
          </Link>
        ) : <span className="text-ps-hint">—</span>}
      </td>
      <td className="py-1.5 pr-3">
        {res.period ? gstPeriodLabel(res.period) : <span className="text-ps-hint">—</span>}
      </td>
      <td className={`py-1.5 pr-3 font-medium ${tone.tone}`}>
        {tone.label}
        {res.status === "reconciled" && res.needs_attention && (
          <span className="block text-3xs font-normal text-state-attention">Needs a look</span>
        )}
      </td>
      <td className="py-1.5 space-y-0.5">
        {res.reason && <p className="text-state-problem">{res.reason}</p>}
        {s && (
          <p className="text-ps-body">
            {s.matched_count} matched · {s.amount_mismatch_count} amount mismatch ·{" "}
            {s.missing_in_2b_count} not filed by supplier · {s.missing_in_books_count} with no bill
            {s.itc_at_risk_paise > 0 && (
              <> · <span className="text-state-problem">{formatPaise(s.itc_at_risk_paise)} credit at risk</span></>
            )}
            {s.probable_match_count > 0 && ` · ${s.probable_match_count} probable match(es) to check`}
          </p>
        )}
        {res.replaced_earlier && (
          <p className={res.replaced_earlier.relation === "same" || res.replaced_earlier.relation === "newer"
              ? "text-ps-label" : "text-state-attention"}>
            Replaced the reconciliation of{" "}
            {formatIstLabelled(res.replaced_earlier.reconciled_at, "an earlier date")}
            {res.replaced_earlier.generated_on
              ? ` (download generated ${res.replaced_earlier.generated_on})` : ""}
            . {res.replaced_earlier.note ?? "Check this is the newer file."}
          </p>
        )}
        {res.problems.map((p, i) => (
          <p key={i} className="text-state-attention">{p}</p>
        ))}
      </td>
    </tr>
  );
}
