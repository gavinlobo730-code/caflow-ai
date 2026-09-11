"use client";

/**
 * THE STATUTORY HANDOFF — the screen a CA works from with the portal open.
 *
 * Track F, phase F3. Between books that are right and an obligation that is
 * closed there are seven steps: compute, emit the artefact, pre-flight, HAND
 * OFF, file, capture the acknowledgement, reconcile. Exactly one of them
 * belongs to the government. Six are ours, and this was the one nothing did.
 *
 * What it cost: settling one client-month meant opening the register for the
 * figures, Setup for the establishment code, Outputs for the file, the EPFO
 * portal, the ESIC portal, the state's own site, and a spreadsheet to remember
 * which of the three were done — then typing numbers from one into another with
 * nowhere to put the challan number that came back.
 *
 * WHAT THIS SCREEN DOES NOT HAVE, AND WILL NOT GET
 *
 *   - no password or username field
 *   - no OTP or EVC field
 *   - no embedded portal frame
 *
 * Not for EPFO, not for ESIC, not for any state. A credential box in this
 * product is a credential-capture surface whatever it is labelled, and an OTP
 * is typed on the portal — never in the software that prepared the return. The
 * same three refusals govern the GST filing demo and the Account Aggregator
 * consent flow, and they are asserted structurally in
 * apps/api/tests/test_the_handoff_says_what_goes_in_which_box.py rather than
 * left as an intention here.
 *
 * ZERO LOGIC. Every sentence on this screen is composed in apps/api
 * (domain/payroll/handoff.py) and rendered verbatim. That is not tidiness:
 * professional tax shows no due date because each state fixes its own, ESI's
 * period is not the wage month, and a blocked EPFO month still offers its file
 * because the file is correct. Rebuilding any of those sentences in the browser
 * would be deciding a statutory question in a place with no tests.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle, Check, Copy, Download, ExternalLink, Info, Link2, Lock,
} from "lucide-react";

import { api, request, type ApiResp, type HandoffObligation,
         type Remittance, type StatutoryHandoff as Handoff,
         type EsicMappedIpCheck, type UnmatchedRemittance } from "@/lib/api";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { todayLocalISO } from "@/lib/dateMath";
import { useToast } from "@/components/ui/use-toast";

type PayrollRun = { id: string; month: string; status: string };

type Note = { kind: "ok" | "warn" | "err"; text: string } | null;

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function fmtMonth(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return m >= 1 && m <= 12 ? `${MONTH_NAMES[m - 1]} ${y}` : month;
}

/** Integer paise to ₹, grouped the Indian way. Display only — every amount on
 *  the wire is paise and stays paise. */
function fmtPaise(paise: number): string {
  const sign = paise < 0 ? "-" : "";
  const abs = Math.abs(paise);
  const rupees = Math.floor(abs / 100);
  const p = abs % 100;
  const grouped = new Intl.NumberFormat("en-IN").format(rupees);
  return `${sign}₹${grouped}.${String(p).padStart(2, "0")}`;
}

/** Whole rupees, for the two files that carry rupees. NOT multiplied into
 *  paise first: the point of the figure is to match what the portal shows. */
function fmtRupees(rupees: number): string {
  return `₹${new Intl.NumberFormat("en-IN").format(rupees)}`;
}

// ─── one copyable identifier ────────────────────────────────────────────────

function IdentityRow({ label, value, note }: {
  label: string; value: string | null; note: string | null;
}) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* a browser that refuses the clipboard still shows the value */ }
  };
  return (
    <div className="flex items-start justify-between gap-3 py-1.5">
      <div className="min-w-0">
        <p className="text-[11px] text-[#64748B]">{label}</p>
        {value ? (
          <p className="text-[13px] font-mono text-[#0F172A] break-all">{value}</p>
        ) : (
          <p className="text-[12px] text-red-600">Not recorded</p>
        )}
        {note && <p className="text-[10px] text-[#94A3B8] mt-0.5">{note}</p>}
      </div>
      {value && (
        <button onClick={copy} title="Copy"
          className="shrink-0 px-2 py-1 border border-[#E2E8F0] rounded-lg text-[11px]
                     text-[#334155] hover:bg-[#F8FAFC] flex items-center gap-1">
          {copied ? <Check size={11} /> : <Copy size={11} />}
          {copied ? "Copied" : "Copy"}
        </button>
      )}
    </div>
  );
}

// ─── recording what the portal gave back ────────────────────────────────────
//
// ONE field for the reference, one for the date, one for the amount. Nothing
// else, because nothing else comes back from a portal that a CA has to keep.

function RecordBack({ obligation, clientId, runId, onDone, onError }: {
  obligation: HandoffObligation;
  clientId: string;
  runId: string;
  onDone: (text: string) => void;
  onError: (text: string) => void;
}) {
  const [reference, setReference] = useState("");
  const [on, setOn] = useState(todayLocalISO());
  const [amount, setAmount] = useState("");
  const [paid, setPaid] = useState(true);
  const [busy, setBusy] = useState(false);

  const isEpf = obligation.scheme === "epf";
  // WHICH RETURN EPFO IS ACTUALLY EXPECTING. The server decides this
  // (domain/payroll/ecr_sequence.decide_returns) from what has already been
  // filed and who joined since — a Regular, a Supplementary, or both. The old
  // form asked from scratch and defaulted to Regular whatever the month needed,
  // and a Supplementary recorded as a Regular leaves the real one outstanding.
  const options = obligation.record_options.length
    ? obligation.record_options : ["regular"];
  const [returnType, setReturnType] = useState(options[0]);

  async function submit() {
    const paise = amount.trim() ? paiseFromRupeeInput(amount) : 0;
    if (paise === null) {
      onError("That amount is not an amount. Type it as ₹ and paise — "
              + "1,25,000 or 125000.50 both work.");
      return;
    }
    setBusy(true);
    try {
      if (isEpf) {
        // EPF has its own record (migration 335) with EPFO's own sequencing —
        // a Regular that is submitted but not approved BLOCKS the next month —
        // so it is not folded into the ESI/PT table.
        const res = (await api.payroll.recordEcrFiled(runId, {
          return_type: returnType,
          status: paid ? "approved" : "submitted",
          submitted_on: on,
          approved_on: paid ? on : undefined,
          trrn: reference.trim() || undefined,
        })) as ApiResp<unknown>;
        if (!res?.success) throw new Error(res?.error ?? "That did not save.");
      } else {
        const res = await api.payroll.recordRemittance(clientId, {
          // Narrowed by `isEpf` above: EPF has its own record and never
          // reaches this branch.
          scheme: obligation.scheme as "esic" | "professional_tax",
          wage_month: obligation.wage_month,
          state: obligation.state,
          status: paid ? "paid" : "submitted",
          submitted_on: on,
          paid_on: paid ? on : null,
          challan_number: reference.trim() || null,
          challan_date: paid ? on : null,
          amount_paise: paise,
          run_id: runId,
        });
        if (!res?.success) throw new Error(res?.error ?? "That did not save.");
      }
      onDone("Recorded. Nothing was transmitted — this only tells PracticeSync "
             + "what you did on the portal.");
    } catch (e) {
      onError(e instanceof Error ? e.message : "That did not save.");
    } finally { setBusy(false); }
  }

  return (
    <div className="mt-3 rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] p-3 space-y-2">
      <p className="text-[11px] font-semibold text-[#1E293B]">
        After you file: record {obligation.record_back}
      </p>
      {isEpf && options.length > 1 && (
        <p className="text-[10px] text-[#94A3B8]">
          This month needs {options.length} returns. Record each one as you
          file it — a Supplementary recorded as a Regular leaves the real
          Regular outstanding, and EPFO will block next month.
        </p>
      )}
      <div className="grid grid-cols-3 gap-2">
        {isEpf && (
          <div className="col-span-3">
            <label className="block text-[10px] text-[#64748B] mb-0.5">
              Return type
            </label>
            <select value={returnType} onChange={(e) => setReturnType(e.target.value)}
              className="w-full border border-[#E2E8F0] rounded-lg px-2 py-1.5 text-[12px]
                         outline-none focus:border-blue-400">
              <option value="regular">
                Regular — every active member for the month
              </option>
              <option value="supplementary">
                Supplementary — members added after the Regular was approved
              </option>
              <option value="revised">
                Revised — figures already submitted, corrected
              </option>
            </select>
          </div>
        )}
        <div>
          <label className="block text-[10px] text-[#64748B] mb-0.5">
            {isEpf ? "TRRN" : "Challan number"}
          </label>
          <input value={reference} onChange={(e) => setReference(e.target.value)}
            placeholder={isEpf ? "as shown on the receipt" : "from the challan"}
            className="w-full border border-[#E2E8F0] rounded-lg px-2 py-1.5 text-[12px]
                       outline-none focus:border-blue-400" />
        </div>
        <div>
          <label className="block text-[10px] text-[#64748B] mb-0.5">Date</label>
          <input type="date" value={on} onChange={(e) => setOn(e.target.value)}
            className="w-full border border-[#E2E8F0] rounded-lg px-2 py-1.5 text-[12px]
                       outline-none focus:border-blue-400" />
        </div>
        {!isEpf && (
          <div>
            <label className="block text-[10px] text-[#64748B] mb-0.5">
              Amount paid (₹)
            </label>
            <input value={amount} onChange={(e) => setAmount(e.target.value)}
              inputMode="decimal" placeholder="what left the bank"
              className="w-full border border-[#E2E8F0] rounded-lg px-2 py-1.5 text-[12px]
                         outline-none focus:border-blue-400" />
          </div>
        )}
      </div>
      {/* The challan's figure, not ours: interest and damages under ESI Act
          s.39(5) can be added at the portal, and a CA reconciling the two needs
          the number that actually left the bank. */}
      {!isEpf && (
        <p className="text-[10px] text-[#94A3B8]">
          Enter what the challan says, not what we computed — interest or
          damages added at the portal are part of what left the bank.
        </p>
      )}
      <label className="flex items-center gap-2 text-[11px] text-[#475569]">
        <input type="checkbox" checked={paid} onChange={(e) => setPaid(e.target.checked)} />
        {isEpf ? "The portal shows this as approved — which is what clears the month"
               : "The money has gone — this is paid, not just filed"}
      </label>
      {isEpf && !paid && (
        <p className="text-[10px] text-[#94A3B8]">
          A Regular that is submitted but not yet approved still BLOCKS the next
          month at EPFO. Come back and mark it approved once the portal does.
        </p>
      )}
      <button onClick={submit} disabled={busy}
        className="px-3 py-1.5 text-[12px] bg-blue-600 text-white rounded-lg
                   hover:bg-blue-700 disabled:opacity-40">
        {busy ? "Saving…" : "Record it"}
      </button>
    </div>
  );
}

// ─── the pre-flight ESIC does and we did not (Track F, phase F1) ────────────
//
// ESIC's own filing manual: "successful transaction only when all the
// Employees' (who are currently mapped in the system) details are entered
// perfectly". The monthly upload is ALL OR NOTHING — a file missing one insured
// person is not partially imported, the WHOLE file is rejected, after the CA
// has assembled it, uploaded it and waited.
//
// So the portal's own mapped list is the authority for who must be in the file,
// and this compares the two before the CA goes anywhere near the upload.
//
// PASTED TEXT, NOT A FILE, and that is a decision rather than a shortcut.
// ESIC forbids uploading any sheet but the portal's own template, which is
// Excel 97-2003; reading one needs xlrd + xlwt + xlutils — two of them without
// a release since 2017, one of them parsing an untrusted upload inside the
// service that holds every client's ledger. A list of insurance numbers is a
// list of numbers.

function MappedIpCheck({ runId }: { runId: string }) {
  const [open, setOpen] = useState(false);
  const [pasted, setPasted] = useState("");
  const [result, setResult] = useState<EsicMappedIpCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function check() {
    setBusy(true); setErr(null);
    try {
      const res = await api.payroll.esicMappedIpCheck(runId, pasted);
      if (!res?.success) throw new Error(res?.error ?? "That did not check.");
      setResult(res.data?.reconciliation ?? null);
    } catch (e) {
      setResult(null);
      setErr(e instanceof Error ? e.message : "That did not check.");
    } finally { setBusy(false); }
  }

  return (
    <div className="border-t border-[#F1F5F9] pt-3">
      {!open ? (
        <button onClick={() => setOpen(true)}
          className="text-[11px] text-blue-700 hover:underline">
          Check against ESIC&rsquo;s mapped list first →
        </button>
      ) : (
        <div className="space-y-2">
          <p className="text-[11px] text-[#475569]">
            Paste the insured persons mapped at ESIC, from the portal&rsquo;s own
            screen. Names alongside the numbers are fine. Nothing is stored —
            this is compared and discarded.
          </p>
          <textarea value={pasted} onChange={(e) => setPasted(e.target.value)}
            rows={4} placeholder={"3113456789 ASHA KUMARI\n3113456790 BIMAL ROY"}
            className="w-full border border-[#E2E8F0] rounded-lg px-2.5 py-2 text-[12px]
                       font-mono outline-none focus:border-blue-400" />
          <div className="flex items-center gap-2">
            <button onClick={check} disabled={busy}
              className="px-3 py-1.5 text-[12px] border border-[#E2E8F0] rounded-lg
                         hover:bg-[#F8FAFC] text-[#334155] disabled:opacity-40">
              {busy ? "Checking…" : "Check"}
            </button>
            <button onClick={() => { setOpen(false); setResult(null); setPasted(""); }}
              className="text-[11px] text-[#94A3B8] hover:text-[#334155]">
              Close
            </button>
          </div>

          {err && (
            <p className="text-[11px] text-red-600 bg-red-50 rounded-lg px-3 py-2">{err}</p>
          )}

          {result && (
            <div className={`rounded-lg px-3 py-2 border text-[11px] ${
              result.would_be_rejected
                ? "bg-red-50 border-red-200 text-red-800"
                : result.not_mapped_at_esic.length
                  ? "bg-amber-50 border-amber-200 text-amber-900"
                  : "bg-green-50 border-green-200 text-green-800"}`}>
              {/* Composed on the server — it carries ESIC's own rule, which a
                  sentence written here would lose. */}
              <p>{result.what_it_means}</p>
              {!!result.missing_from_file.length && (
                <p className="mt-1.5 font-mono text-[10px] break-all">
                  Mapped, not in the file: {result.missing_from_file.join(", ")}
                </p>
              )}
              {!!result.not_mapped_at_esic.length && (
                <p className="mt-1.5 font-mono text-[10px] break-all">
                  In the file, not mapped: {result.not_mapped_at_esic.join(", ")}
                </p>
              )}
              <p className="mt-1.5 text-[10px] opacity-80">
                {result.mapped_count} mapped at ESIC · {result.file_count} in the file
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}


// ─── one obligation ─────────────────────────────────────────────────────────

function ObligationCard({ o, clientId, runId, onChanged }: {
  o: HandoffObligation; clientId: string; runId: string; onChanged: () => void;
}) {
  const [note, setNote] = useState<Note>(null);
  const [busy, setBusy] = useState(false);

  /** The ECR and the ESIC return come back as TEXT with `problems` and
   *  `filable`. The file is downloaded from the endpoint that BUILDS it, not
   *  from anything cached here — there is one builder per return and the
   *  handoff must be looking at the same one. */
  async function download() {
    setBusy(true); setNote(null);
    try {
      const isEcr = o.scheme === "epf";
      const res = (await (isEcr ? api.payroll.runEcr(runId)
                                : api.payroll.runEsic(runId))) as {
        data?: { filename?: string; lines?: string; csv?: string };
      };
      const content = isEcr ? res?.data?.lines : res?.data?.csv;
      if (!content) { setNote({ kind: "err", text: "The server returned an empty file." }); return; }
      // Neither gets a byte-order mark — extra bytes break the parse on upload.
      const blob = new Blob([content],
        { type: isEcr ? "text/plain" : "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = res?.data?.filename ?? (o.artefact.filename ?? "return.txt");
      a.click();
      URL.revokeObjectURL(url);
      setNote({ kind: "ok", text: "Downloaded. Upload it on the portal yourself — "
                                  + "nothing has been transmitted." });
    } catch (e) {
      setNote({ kind: "err", text: e instanceof Error ? e.message : "That did not work." });
    } finally { setBusy(false); }
  }

  const recorded = o.recorded as (Remittance & { trrn?: string; status?: string }) | null;

  return (
    <div className="bg-white rounded-xl border border-[#E2E8F0] p-4 space-y-3">
      {/* ── who, where, by when ─────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <p className="text-[13px] font-semibold text-[#0F172A]">{o.title}</p>
          <p className="text-[11px] text-[#64748B]">
            {o.authority} · {o.period_label}
          </p>
          {o.statute && (
            <p className="text-[10px] text-[#94A3B8] mt-0.5">{o.statute}</p>
          )}
        </div>
        <div className="text-right shrink-0">
          {o.due_date ? (
            <p className="text-[11px] text-[#334155]">
              Due <span className="font-semibold">{o.due_date}</span>
            </p>
          ) : (
            <p className="text-[11px] text-[#94A3B8]">No due date shown</p>
          )}
          <p className="text-[10px] text-[#94A3B8] flex items-center gap-1 justify-end mt-0.5">
            {o.portal_host ? <ExternalLink size={9} /> : null}
            {o.portal_host || o.portal}
          </p>
        </div>
      </div>

      {/* Why there is no date, where there is none. A wrong date in a CA's
          calendar is worse than a missing one, and silence is worse than
          either — it reads as "nothing is due". */}
      {o.due_note && (
        <p className="text-[11px] text-[#475569] bg-[#F1F5F9] rounded-lg px-3 py-2
                      flex items-start gap-2">
          <Info size={12} className="mt-0.5 shrink-0 text-[#64748B]" />
          {o.due_note}
        </p>
      )}

      {/* ── what would be refused at the portal today ───────────────────── */}
      {o.blocking.map((b, i) => (
        <p key={i} className="text-[11px] text-red-700 bg-red-50 border border-red-200
                              rounded-lg px-3 py-2 flex items-start gap-2">
          <Lock size={12} className="mt-0.5 shrink-0" />{b}
        </p>
      ))}

      {/* ── what changes what you do, but does not stop you ─────────────── */}
      {o.warnings.map((w, i) => (
        <p key={i} className="text-[11px] text-amber-900 bg-amber-50 border border-amber-200
                              rounded-lg px-3 py-2 flex items-start gap-2">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />{w}
        </p>
      ))}

      {/* ── 1. the identifiers the portal asks for ──────────────────────── */}
      <div className="border-t border-[#F1F5F9] pt-2">
        <p className="text-[10px] uppercase tracking-wide text-[#94A3B8] mb-1">
          What identifies this filing
        </p>
        {o.identity.map((f) => (
          <IdentityRow key={f.label} label={f.label} value={f.value} note={f.note} />
        ))}
      </div>

      {/* ── 2. the figures the portal will show back ────────────────────── */}
      <div className="border-t border-[#F1F5F9] pt-2">
        <p className="text-[10px] uppercase tracking-wide text-[#94A3B8] mb-1">
          Check these against the portal before you submit
        </p>
        <table className="w-full text-[12px]">
          <tbody>
            {o.confirm.map((f) => (
              <tr key={f.label} className="border-b border-[#F8FAFC] last:border-0">
                <td className="py-1.5 pr-2 text-[#475569] align-top">
                  {f.label}
                  {f.note && (
                    <span className="block text-[10px] text-[#94A3B8]">{f.note}</span>
                  )}
                </td>
                <td className="py-1.5 text-right font-mono text-[#0F172A] align-top
                               whitespace-nowrap">
                  {f.amount_paise !== null ? fmtPaise(f.amount_paise)
                   : f.rupees !== null ? fmtRupees(f.rupees)
                   : f.count !== null ? f.count
                   : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ESIC only: the portal checks the file against its OWN mapped list and
          rejects the whole upload over one missing person. EPF and PT have no
          equivalent — EPFO takes the members from the file itself. */}
      {o.scheme === "esic" && o.artefact.available && <MappedIpCheck runId={runId} />}

      {/* ── 3. the file ─────────────────────────────────────────────────── */}
      <div className="border-t border-[#F1F5F9] pt-3">
        {o.artefact.available ? (
          <button onClick={download} disabled={busy}
            className="px-3 py-1.5 text-[12px] border border-[#E2E8F0] rounded-lg
                       hover:bg-[#F8FAFC] text-[#334155] disabled:opacity-40
                       flex items-center gap-1.5">
            <Download size={12} />
            {busy ? "Building…" : `Download ${o.artefact.filename}`}
          </button>
        ) : (
          <p className="text-[11px] text-[#64748B] bg-[#F8FAFC] rounded-lg px-3 py-2">
            {o.artefact.why_not}
          </p>
        )}
        {note && (
          <p className={`text-[11px] mt-2 px-3 py-2 rounded-lg ${
            note.kind === "ok" ? "bg-green-50 text-green-700"
            : note.kind === "warn" ? "bg-amber-50 text-amber-800"
            : "bg-red-50 text-red-600"}`}>{note.text}</p>
        )}
      </div>

      {/* ── 4. what came back ───────────────────────────────────────────── */}
      {recorded ? (
        <div className="border-t border-[#F1F5F9] pt-3">
          <p className="text-[11px] text-green-800 bg-green-50 border border-green-200
                        rounded-lg px-3 py-2 flex items-start gap-2">
            <Check size={12} className="mt-0.5 shrink-0" />
            <span>
              Recorded as filed
              {recorded.trrn ? ` — TRRN ${recorded.trrn}` : ""}
              {recorded.challan_number ? ` — challan ${recorded.challan_number}` : ""}
              {typeof recorded.amount_paise === "number" && recorded.amount_paise > 0
                ? ` — ${fmtPaise(recorded.amount_paise)}` : ""}
              {recorded.status ? ` (${recorded.status})` : ""}
              {/* The link to the payment entry is what separates "nobody has
                  paid this" from "paid and never matched to its bank line".
                  Both look uncleared on the ledger without it. */}
              {recorded.status === "paid" && !recorded.journal_entry_id
                && o.scheme !== "epf"
                ? " · not yet matched to a bank payment" : ""}
            </span>
          </p>
          {/* A register you can only add to is a register that is wrong the
              first time somebody records a challan against the wrong month.
              RETRACT is a SOFT delete on the server — the challan number, the
              date and the amount that left the bank are held nowhere else, so
              a row that simply vanished would leave no trace that a liability
              had ever been reported settled.

              EPF is deliberately absent: its record is epfo_ecr_filings, which
              carries EPFO's own month-wise sequence, and retracting a month
              there unblocks the next one. That is a different act with a
              different consequence and it has its own path. */}
          {o.scheme !== "epf" && recorded.id && (
            <Retract clientId={clientId} remittanceId={recorded.id}
              onDone={(text) => { setNote({ kind: "ok", text }); onChanged(); }}
              onError={(text) => setNote({ kind: "err", text })} />
          )}
        </div>
      ) : (
        <RecordBack obligation={o} clientId={clientId} runId={runId}
          onDone={(text) => { setNote({ kind: "ok", text }); onChanged(); }}
          onError={(text) => setNote({ kind: "err", text })} />
      )}
    </div>
  );
}

// ─── retract one recorded in error ──────────────────────────────────────────
//
// Two clicks, not one, and the second one says what it destroys. Recording a
// remittance is how PracticeSync learns a statutory liability was settled; the
// wrong month or the wrong scheme leaves a real liability looking paid, which
// is the failure that matters, so undoing it has to be possible. But the
// challan number, the date and the amount are held nowhere else, so the
// confirmation names them rather than asking "are you sure?".

function Retract({ clientId, remittanceId, onDone, onError }: {
  clientId: string; remittanceId: string;
  onDone: (text: string) => void; onError: (text: string) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  async function go() {
    setBusy(true);
    try {
      const res = await api.payroll.retractRemittance(clientId, remittanceId);
      if (!res.success) throw new Error(res.error ?? "That did not work.");
      onDone("Retracted. The return is no longer recorded as filed — nothing "
             + "was transmitted, at the time or now.");
      setConfirming(false);
    } catch (e) {
      onError(e instanceof Error ? e.message : "That did not work.");
    } finally { setBusy(false); }
  }

  if (!confirming) {
    return (
      <button type="button" onClick={() => setConfirming(true)}
        className="mt-2 text-[11px] text-[#64748B] hover:text-red-600 underline
                   underline-offset-2">
        Recorded in error? Retract
      </button>
    );
  }
  return (
    <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2
                    space-y-2">
      <p className="text-[11px] text-amber-900">
        This removes PracticeSync&apos;s record that the return was filed and the
        challan paid. It does not undo anything at the portal, and it does not
        touch the ledger — if a bank entry paid this, that entry stays.
      </p>
      <div className="flex items-center gap-2">
        <button type="button" onClick={go} disabled={busy}
          className="text-[11px] font-semibold text-white bg-red-600 hover:bg-red-700
                     disabled:opacity-50 rounded-md px-3 py-1.5">
          {busy ? "Retracting…" : "Yes, retract it"}
        </button>
        <button type="button" onClick={() => setConfirming(false)} disabled={busy}
          className="text-[11px] text-[#475569] hover:text-[#0F172A] px-2 py-1.5">
          Keep it
        </button>
      </div>
    </div>
  );
}

// ─── what was paid and never tied back (Track F, phase F4) ──────────────────
//
// THE QUESTION, and it is the reason migration 365 carries a journal_entry_id
// at all: on the ledger, a statutory liability NOBODY HAS PAID and one that was
// PAID AND NEVER TIED BACK look identical. Both sit uncleared on ESI Payable at
// year end, and a CA closing the books has to open the bank statement to tell
// them apart, one account at a time.
//
// LINKING IS NOT POSTING. The PATCH behind the button writes a reference and
// nothing else — bank_posting_service.post already wrote Dr <liability> /
// Cr Bank when the CA passed the bank statement line, and a posting from here
// as well would debit the statutory liability twice.
//
// CLIENT-WIDE, not month-wide, deliberately: an unmatched September remittance
// is still unmatched while the CA is working on October, and a list that
// followed the month picker would hide exactly the rows somebody has forgotten.

function UnmatchedRemittances({ clientId, onLinked }: {
  clientId: string; onLinked: () => void;
}) {
  const [rows, setRows] = useState<UnmatchedRemittance[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<Note>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.payroll.remittanceReconciliation(clientId);
      setRows(res?.success ? (res.data?.unmatched ?? []) : []);
    } catch { setRows([]); }
    finally { setLoaded(true); }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function link(remittanceId: string, journalEntryId: string) {
    setBusy(remittanceId); setNote(null);
    try {
      const res = await api.payroll.linkRemittancePayment(
        clientId, remittanceId, journalEntryId);
      if (!res?.success) throw new Error(res?.error ?? "That did not link.");
      setNote({ kind: "ok", text: "Matched. The liability now shows which "
                                  + "entry cleared it." });
      await load();
      onLinked();
    } catch (e) {
      setNote({ kind: "err", text: e instanceof Error ? e.message : "That did not link." });
    } finally { setBusy(null); }
  }

  // Nothing outstanding is the ordinary state, and an empty panel on every
  // screen teaches people to stop reading it.
  if (!loaded || rows.length === 0) return null;

  return (
    <div className="bg-white rounded-xl border border-amber-200 p-4 space-y-3">
      <div>
        <p className="text-[13px] font-semibold text-[#0F172A]">
          Paid, but not yet matched to a bank payment ({rows.length})
        </p>
        <p className="text-[11px] text-[#64748B] mt-0.5">
          On the ledger these look exactly like a liability nobody has paid.
          Matching one records WHICH entry cleared it — it posts nothing, and
          the entry itself is unchanged.
        </p>
      </div>

      {note && (
        <p className={`text-[11px] px-3 py-2 rounded-lg ${
          note.kind === "ok" ? "bg-green-50 text-green-700"
          : "bg-red-50 text-red-600"}`}>{note.text}</p>
      )}

      {rows.map((r) => (
        <div key={r.id} className="border-t border-[#F1F5F9] pt-3">
          <div className="flex items-baseline justify-between gap-3 flex-wrap">
            <p className="text-[12px] text-[#1E293B]">
              <span className="font-semibold">
                {r.scheme === "esic" ? "ESI" : `Professional tax — ${r.state ?? ""}`}
              </span>
              {" · "}{fmtMonth(r.wage_month)}
              {r.challan_number ? ` · challan ${r.challan_number}` : ""}
            </p>
            <p className="text-[12px] font-mono text-[#0F172A]">
              {fmtPaise(r.amount_paise)}
            </p>
          </div>
          <p className="text-[10px] text-[#94A3B8]">
            Paid {r.paid_on ?? "—"}
          </p>

          {r.candidates.length === 0 ? (
            <p className="text-[11px] text-[#64748B] mt-2 bg-[#F8FAFC] rounded-lg px-3 py-2">
              No entry in the books clears this liability around that date. Either
              the bank line has not been passed yet, or the payment went through
              a different account — pass the statement line first, then come back.
            </p>
          ) : (
            <div className="mt-2 space-y-1.5">
              {r.candidates.map((c) => (
                <div key={c.journal_entry_id}
                  className="flex items-start justify-between gap-3 rounded-lg
                             border border-[#E2E8F0] px-3 py-2">
                  <div className="min-w-0">
                    <p className="text-[11px] text-[#1E293B]">
                      <span className={`inline-block px-1.5 py-0.5 rounded mr-1.5
                        text-[9px] font-semibold uppercase tracking-wide ${
                        c.grade === "exact" ? "bg-green-100 text-green-800"
                                            : "bg-slate-100 text-slate-600"}`}>
                        {c.grade}
                      </span>
                      {c.entry_date}
                      {c.reference_no ? ` · ${c.reference_no}` : ""}
                    </p>
                    {/* The sentence is composed on the server. It carries the
                        statutory reasoning — that interest on a late challan
                        rides on the same payment — which a string built here
                        would lose. */}
                    <p className="text-[10px] text-[#64748B] mt-0.5">{c.reason}</p>
                  </div>
                  <button onClick={() => link(r.id, c.journal_entry_id)}
                    disabled={busy !== null}
                    className="shrink-0 px-2.5 py-1 text-[11px] border border-[#E2E8F0]
                               rounded-lg hover:bg-[#F8FAFC] text-[#334155]
                               disabled:opacity-40 flex items-center gap-1">
                    <Link2 size={11} />
                    {busy === r.id ? "Matching…" : "This one"}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}


// ─── the screen ─────────────────────────────────────────────────────────────

export default function StatutoryHandoff({ clientId }: { clientId: string }) {
  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [runId, setRunId] = useState("");
  const [handoff, setHandoff] = useState<Handoff | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const { toast } = useToast();

  useEffect(() => {
    (async () => {
      try {
        const res = await request<ApiResp<PayrollRun[]>>(
          `/api/payroll/runs?client_id=${clientId}`);
        const list = res?.data ?? [];
        setRuns(list);
        // A draft run has nothing to hand off — the returns report
        // contributions actually made — so open on the newest released month
        // rather than on a month the server will refuse.
        setRunId((list.find((r) => r.status === "finalized" || r.status === "paid")
                  ?? list[0])?.id ?? "");
      } catch { /* the empty state below says it */ }
      finally { setLoading(false); }
    })();
  }, [clientId]);

  const load = useCallback(async () => {
    if (!runId) { setHandoff(null); return; }
    setErr(null);
    try {
      const res = await api.payroll.runHandoff(runId);
      if (!res?.success) throw new Error(res?.error ?? "That did not load.");
      setHandoff(res.data);
    } catch (e) {
      setHandoff(null);
      setErr(e instanceof Error ? e.message : "That did not load.");
    }
  }, [runId]);

  useEffect(() => { load(); }, [load]);

  const run = runs.find((r) => r.id === runId);

  if (loading) {
    return <p className="p-5 text-[12px] text-[#94A3B8]">Loading…</p>;
  }
  if (!runs.length) {
    return <p className="p-5 text-center text-sm text-[#94A3B8] py-10">
      No payroll runs yet. Compute one under Register first.
    </p>;
  }

  return (
    <div className="p-5 space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <label className="text-[11px] text-[#64748B]">Month</label>
        <select value={runId} onChange={(e) => setRunId(e.target.value)}
          className="border border-[#E2E8F0] rounded-lg px-3 py-1.5 text-[13px]
                     outline-none focus:border-blue-400">
          {runs.map((r) => (
            <option key={r.id} value={r.id}>{fmtMonth(r.month)} · {r.status}</option>
          ))}
        </select>
      </div>

      {/* The one sentence that has to survive every redesign of this screen. */}
      <p className="text-[11px] text-[#475569] bg-blue-50 border border-blue-200
                    rounded-xl px-3 py-2">
        You file these yourself, on the portals. PracticeSync computes the
        figures, builds the files and remembers what you filed — it transmits
        nothing, and it will never ask you for a portal password or an OTP.
        Those are typed on the portal, never here.
      </p>

      {err && (
        <p className="text-[12px] px-3 py-2 rounded-lg bg-amber-50 text-amber-800">
          {err}
        </p>
      )}

      {/* Client-wide, above the month. See UnmatchedRemittances — it renders
          nothing when there is nothing outstanding. */}
      <UnmatchedRemittances clientId={clientId} onLinked={load} />

      {handoff?.unattributed_pt_paise ? (
        <p className="text-[11px] text-red-700 bg-red-50 border border-red-200
                      rounded-xl px-3 py-2">
          {fmtPaise(handoff.unattributed_pt_paise)} of professional tax was
          withheld from employees with no state recorded, so it belongs to no
          authority on this screen. Set their PT state under Inputs and
          recompute the month.
        </p>
      ) : null}

      {handoff?.obligations.length ? (
        handoff.obligations.map((o) => (
          <ObligationCard key={o.key} o={o} clientId={clientId} runId={runId}
            onChanged={() => { load(); toast({ title: "Recorded" }); }} />
        ))
      ) : !err ? (
        <p className="text-[12px] text-[#94A3B8]">
          {run && run.status !== "finalized" && run.status !== "paid"
            ? "This month is still a draft. The returns report contributions "
              + "actually made, so finalise it under Release first."
            : "Nothing statutory arises from this month."}
        </p>
      ) : null}
    </div>
  );
}
