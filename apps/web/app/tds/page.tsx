"use client";

/**
 * TDS Module — Tax Deducted at Source
 * IT Act Chapter XVII-B: Deduction and Collection of Tax at Source
 * Section 192: TDS on Salary
 * Section 194A: TDS on Interest (the limit depends on who pays, who is paid and the financial year; the engine holds it)
 * Section 194C: TDS on Contractor Payments
 * Section 194D: TDS on Insurance Commission
 * Section 194H: TDS on Commission/Brokerage
 * Section 194I: TDS on Rent
 * Section 194J: TDS on Professional/Technical Fees
 * Section 194Q: TDS on Purchase of Goods
 *
 * NO RATES IN THIS LIST. Two of the ones it carried were a Finance Act behind
 * — §194D and §194H both read "(5%)" when the registry has both at 2% — and a
 * rate cannot honestly sit beside a section anyway: §194C is 1% or 2% by payee
 * type, every rate is floored at 20% by §206AA with no PAN, and below the
 * threshold it is nil. domain/tds/section_rates.py is the one rate table.
 * NO THRESHOLDS EITHER, for the same reason: they are versioned by financial
 * year per section, and §194A alone has three (who pays and who is paid decide
 * which). This header carried the pre-Finance-Act-2025 §194A figures after the
 * registry had moved on; the registry is the authority, not this comment.
 * Section 200: TDS deposit and return filing obligations
 * Section 203: Issuance of TDS certificates
 */

import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { useState, useEffect, useMemo, useRef } from "react";
import Link from "next/link";
import {
  IndianRupee, Calendar, AlertCircle, Plus, X, FileText, Award, Upload, ArrowRight,
} from "lucide-react";
import CsvImportModal from "@/components/LazyCsvImportModal";
import type { ImportRow } from "@/components/CsvImportModal";
import { DataTable } from "@/components/ui/data-table";
import type { Column, FilterDef } from "@/lib/table/types";

// THREE COLUMNS WERE REQUIRED AND THEN DISCARDED (12 September probe pass §2.4).
//
// `tds_rate`, `fy` and `quarter` were all `required: true`, so the import
// refused a file that omitted any of them — and none of the three reached the
// payload: `createTdsDeduction` has no field for any of them, and never had.
// The server derives all three, from better sources than a spreadsheet:
//
//   * the RATE comes from the engine (`domain/tds/section_rates.py`), with
//     the section's threshold, the year's aggregate and the §206AA floor
//     applied. Taking it from a spreadsheet column is the defect
//     `scripts/tds-is-computed-by-the-engine-not-the-browser.test.ts` already
//     forbids in the row parser; offering the column invited it back at the
//     mapping step;
//   * the FY and the QUARTER come from `transaction_date`. A CA who typed a
//     quarter contradicting their own date got the date's, silently.
//
// So a CA was made to fill three columns to be allowed to import, and then
// told nothing when their values were ignored. Removed rather than made
// optional: an optional column that is still discarded is the same lie in a
// quieter voice.
const TDS_IMPORT_COLUMNS = [
  { key: "party_name",      label: "Party Name",       required: true,  hint: "Name of deductee e.g. ABC Consulting" },
  { key: "party_pan",       label: "Party PAN",        required: true,  hint: "e.g. AABCU9603R" },
  { key: "section",         label: "TDS Section",      required: true,  hint: "e.g. 194C | 194J | 194A — the rate, threshold and §206AA floor are applied by the engine, not read from the file" },
  { key: "gross_amount_rs", label: "Gross Amount (₹)", required: true,  hint: "e.g. 100000 (in rupees)" },
  { key: "payment_date",    label: "Payment Date",     required: true,  hint: "YYYY-MM-DD e.g. 2025-05-15 — the financial year and the quarter are taken from this date" },
  { key: "challan_no",      label: "Challan No",       required: false, hint: "A note only: it is stored with the deduction, shown nowhere on this screen and matched to nothing. Record the deposit itself as a challan on the Challans tab" },
];

// PAN — IT Act §139A, through `lib/identifiers/pan.panProblem`. A DEDUCTEE
// PAN decides §206AA's 20% floor, so refusing a good one here sends the CA
// back to the spreadsheet rather than letting them import the quarter.
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { useClientPicker } from "@/lib/workspace/useClientPicker";
import { formatPaise } from "@/lib/services/formatting";
import { formatDate } from "@/lib/dates/format";
import { useToast } from "@/components/ui/use-toast";
import { usePermissions } from "@/lib/auth/AuthContext";
import { RetractChallanModal } from "@/components/tds/RetractChallanModal";
import { MatchChallanToLedgerModal } from "@/components/tds/MatchChallanToLedgerModal";
import { Button } from "@/components/ui/button";
// The engine, reached through the API. Rates, thresholds, the
// individual-vs-company split, §206AA and the year's aggregate are all
// resolved server-side — CLAUDE.md: zero business logic in the frontend.
import {
  listTdsSections, listTdsDeductions, listTdsChallans, listTdsReturns, listTdsCertificates, previewTdsDeduction, createTdsDeduction,
  createTdsChallan, retractTdsChallan, fetchDepositDue, fetchTdsDepositState, currentFinancialYear, type DepositDueWorksheet, type TdsDepositState,
  type CalendarAnswer, type TdsDeductionTotals, type TdsReturnCounts, type TdsCertificateCounts,
  fetchChallanLedgerCandidates, linkChallanPayment, unlinkChallanPayment, type ChallanLedgerCandidates,
} from "@/lib/data/tds";
import { NO_SECTIONS, sectionChoices, sectionOptionText, type SectionChoices } from "@/lib/tds/sectionChoices";
import { MINOR_HEAD_LABEL, minorHeadLabel } from "@/lib/tds/minorHead";
import { ListWindowNotice } from "@/components/lists/ListWindowNotice";
import { YearPicker } from "@/components/ui/year-picker";
import { Callout } from "@/components/ui/callout";
import { panProblem } from "@/lib/identifiers/pan";
import { PageHeader } from "@/components/ui/page-header";
import { DateInput } from "@/components/ui/date-input";
import { useDateProblems } from "@/lib/dates/useDateProblems";
import { EmptyState } from "@/components/ui/states";
import { EmptyStateAction, EmptyStateActions } from "@/components/ui/empty-state-action";

// ─── TDS section names ───────────────────────────────────────────────────────
//
// The sections this screen offers, and their plain-English names, are the server's (`GET /api/tds/sections`, read once by the page
// into `lib/tds/sectionChoices`). What used to be here was a copy of fifteen of them, first of rates that were wrong in eight ways
// (s.194C flat at the company rate, s.194D at 5%, a s.194H rate the Finance (No. 2) Act 2024 cut, s.194Q charged on the whole sum,
// s.194IA offered although the engine does not hold it, s.192 leaving the previous rate in the box, no threshold on anything and no
// FY aggregate) and then of names, and the copy held neither s.194T nor s.195, so a challan under either could not be recorded here
// (POST-A-278). No rate, threshold or name is held in this file.

// What a list shows in the place of its rows while it is being read, or when the read was refused: an empty list is "none recorded"
// only when the read succeeded, and a CA must not be told "No challans added yet" about a list nobody has read.
function ListNotRead({ loading, error, what }: { loading: boolean; error: string | null; what: string }) {
  return (
    <div role="status" className="px-4 py-10 text-center text-sm text-ps-hint">
      {loading ? `Reading this client's ${what}…` : `This client's ${what} could not be read: ${error}`}
    </div>
  );
}

// The VALUE stored is the bare quarter — tds_challans.quarter and
// tds_returns.quarter both CHECK ('Q1','Q2','Q3','Q4'), and migration 347 puts
// tds_deductions on the same vocabulary. The months are a LABEL and belong
// beside it, not inside it: "Q1 (Apr-Jun)" written to the column matched no
// reader on either side.
const QUARTERS = ["Q1", "Q2", "Q3", "Q4"] as const;
const QUARTER_LABEL: Record<string, string> = {
  Q1: "Q1 (Apr-Jun)", Q2: "Q2 (Jul-Sep)", Q3: "Q3 (Oct-Dec)", Q4: "Q4 (Jan-Mar)",
};
// FROM THE CLOCK, NOT A LITERAL. This list ended at a year that is now in the
// past, so the current financial year could not be selected at all — broken on
// 1 April with nothing saying so. `financialYearChoicesAround` is the one
// helper (lib/dates/periods.ts); see
// scripts/a-financial-year-choice-comes-from-the-clock.test.ts.

// Keyed by the values the CHECK constraints actually store (migration 037),
// lower case. The capitalised keys this held were unreachable: nothing in the
// database can equal "Pending", so every badge rendered with no class at all.
const STATUS_STYLE: Record<string, string> = {
  // tds_certificates
  pending:    "bg-state-attention-surface text-state-attention",
  generated:  "bg-state-working-surface text-state-working",
  issued:     "bg-state-ready-surface text-state-ready",
  downloaded: "bg-state-ready-surface text-state-ready",
  // tds_returns
  prepared:    "bg-state-working-surface text-state-working",
  ca_approved: "bg-state-working-surface text-state-working",
  filed:       "bg-state-ready-surface text-state-ready",
  revised:     "bg-state-attention-surface text-state-attention",
  // tds_challans
  deposited: "bg-state-ready-surface text-state-ready",
  matched:   "bg-state-ready-surface text-state-ready",
  unmatched: "bg-state-problem-surface text-state-problem",
};

const STATUS_LABEL: Record<string, string> = {
  pending: "Pending", generated: "Generated", issued: "Issued",
  downloaded: "Downloaded", prepared: "Prepared", ca_approved: "CA approved",
  filed: "Filed", revised: "Revised", deposited: "Deposited",
  matched: "Matched", unmatched: "Unmatched",
};

// ─── Types ───────────────────────────────────────────────────────────────────

// tds_deductions as it actually is. The page previously used a different name
// for almost every field (party_name, gross_amount_paise, tds_rate,
// tds_amount_paise, payment_date, fy), so every read filtered on a column that
// did not exist and every write was rejected. financial_year is new in
// migration 263 — the backend's tds_repository already filtered by it.
interface TDSDeduction {
  id: string;
  firm_id: string;
  client_id: string;          // NOT NULL — a deduction belongs to a client
  deductee_name: string;
  deductee_pan: string | null;
  section: string;
  payment_amount_paise: number;
  tds_rate_pct: number;
  tds_paise: number;
  transaction_date: string;
  challan_no: string | null;
  financial_year: string | null;
  quarter: string | null;
  created_at: string;
}

// The three below are migration 037's tables as they ACTUALLY are. Every one
// of them was declared here with invented column names and a capitalised
// status vocabulary the CHECK constraints forbid (TDS-15), so the Challans tab
// saved nothing, the Certificates tab rendered `undefined` in two columns, and
// the Returns counters read 0/0/0 for ever.

interface TDSChallan {
  id: string;
  bsr_code: string;
  challan_no: string;          // not challan_serial_no
  payment_date: string;        // not challan_date
  total_paise: number;         // not amount_paise
  tds_paise: number;
  financial_year: string;      // not fy
  quarter: string;             // 'Q1'..'Q4' — not "Q1 (Apr-Jun)"
  section: string | null;
  /** Challan 281's minor head ("200" or "400"); the column defaults to "200". */
  minor_head?: string | null;
  status: "deposited" | "matched" | "unmatched";
  /** The ledger entry that paid this challan, when a person has tied one (POST-A-272). A link only; null = not tied. */
  journal_entry_id?: string | null;
  /** The server's reading of the entry the challan is tied to (present only on a tied challan). */
  ledger_link?: { state: string; label: string; note: string | null } | null;
  /** Only on the answer to recording one: what became of the monthly deposit obligations on the compliance calendar. */
  compliance_obligations?: CalendarAnswer[];
}

interface TDSCertificate {
  id: string;
  deductee_name: string;
  deductee_pan: string;
  certificate_type: string;
  certificate_form?: string;   // the FY's own name for it — the server derives it
  financial_year: string;      // not period
  quarter: string | null;      // NULL for Form 16, which is annual
  tds_deducted_paise: number;  // not amount_paise
  issued_at: string | null;
  status: "pending" | "generated" | "issued" | "downloaded";
}

const TABS = ["Deductions", "Challans", "Returns", "Certificates"];

// TDS returns (IT Act §200(3)) and certificates (Form 16/16A) are loaded from the
// firm's real data; empty until the firm records them (no fictional seed data).

// ─── Add Deduction Modal ─────────────────────────────────────────────────────

function AddDeductionModal({ clientId, choices, onClose, onAdded }: {
  // No firmId. The server takes the firm from the caller's own token, which is
  // the point of routing this through the API — a firm_id the browser supplies
  // is a firm_id the browser could get wrong.
  //
  // tds_deductions.client_id is NOT NULL. This page used to insert null, so
  // every deduction ever entered on this form was rejected by the database.
  clientId: string;
  /** The sections and their names, from the server (`lib/tds/sectionChoices`); empty until it has answered. */
  choices: SectionChoices;
  onClose: () => void;
  onAdded: () => void;
}) {
  const { toast } = useToast();
  const [partyName, setPartyName] = useState("");
  const [partyPan, setPartyPan] = useState("");
  const [section, setSection] = useState("194J");
  const [grossRupees, setGrossRupees] = useState("");
  const [paymentDate, setPaymentDate] = useState("");
  const [challanNo, setChallanNo] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // The sections a deduction may be recorded under are the server's (`choices.deductible`): it leaves out s.192, which
  // section_rates.py holds as a sentinel because salary is slab-based, so resolve_tds answers nil for it and a deduction recorded
  // under s.192 here would save with zero tax and say nothing about it (payroll computes s.192), and s.206C, which is collected and
  // not deducted. A CHALLAN under either is a different matter and is still offered in the Add Challan form: a salary TDS deposit
  // is a real ITNS 281 payment.
  // What the SERVER says this deduction comes to. There is no local answer to
  // fall back on — that was the bug.
  const [quote, setQuote] = useState<Awaited<ReturnType<typeof previewTdsDeduction>> | null>(null);
  const [quoting, setQuoting] = useState(false);
  const [quoteErr, setQuoteErr] = useState<string | null>(null);
  // Text that is not a date reads as blank to the form (frontend_ux-19).
  const dates = useDateProblems();

  // The FY the PAYMENT falls in decides which year's rates apply and which
  // quarter the row belongs to, and the server derives both from the date.
  // There is no FY or Quarter control any more: letting a CA pick a quarter
  // that contradicts the payment date is how this column ended up with three
  // vocabularies, none of which the return preparer matched.
  // Read as integer paise rather than multiplied into them. null means the box
  // does not hold an amount.
  const grossPaise = grossRupees ? paiseFromRupeeInput(grossRupees) : null;

  // THE FIGURE COMES FROM THE SERVER, through the same function the save uses,
  // so what a CA approves is what lands. Debounced because it is a request per
  // keystroke otherwise.
  useEffect(() => {
    if (!clientId || !paymentDate || grossPaise === null || grossPaise <= 0) {
      setQuote(null); setQuoteErr(null); return;
    }
    let alive = true;
    setQuoting(true);
    const t = setTimeout(() => {
      previewTdsDeduction({
        client_id: clientId,
        deductee_name: partyName.trim() || "—",
        deductee_pan: partyPan.trim().toUpperCase() || null,
        section,
        payment_amount_paise: grossPaise,
        transaction_date: paymentDate,
      })
        .then((q) => { if (alive) { setQuote(q); setQuoteErr(null); } })
        .catch((e) => { if (alive) { setQuote(null); setQuoteErr(e instanceof Error ? e.message : "Could not compute"); } })
        .finally(() => { if (alive) setQuoting(false); });
    }, 350);
    return () => { alive = false; clearTimeout(t); };
  }, [clientId, section, grossPaise, paymentDate, partyPan, partyName]);

  async function handleSubmit() {
    if (dates.first) { setErr(dates.first); return; }
    if (!partyName.trim() || !paymentDate) {
      setErr("Party name and payment date are required.");
      return;
    }
    if (grossPaise === null || grossPaise <= 0) {
      setErr("Enter the payment amount.");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. This records the firm's own
      // register; nothing reaches TRACES.
      //
      // No rate and no tax amount are sent. Both are the engine's answers
      // (IT Act Chapter XVII-B) — the threshold, the individual-vs-company
      // split off the PAN, the s.206AA floor and the year's aggregate with its
      // s.200 credit. This used to be an insert straight into tds_deductions
      // over PostgREST, carrying a figure computed here from a stale table,
      // where rbac() never ran.
      await createTdsDeduction({
        client_id: clientId,
        deductee_name: partyName.trim(),
        deductee_pan: partyPan.trim().toUpperCase() || null,
        section,
        payment_amount_paise: grossPaise,
        transaction_date: paymentDate,
        challan_no: challanNo.trim() || null,
      });
      onAdded();
      toast({ title: "TDS deduction recorded" });
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-brand-dark/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-ps-ink">Add TDS Deduction</h3>
          <button onClick={onClose} className="text-ps-hint hover:text-ps-label"><X className="w-4 h-4" /></button>
        </div>
        {err && <Callout tone="problem">{err}</Callout>}

        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="text-xs font-medium text-ps-body block mb-1">Party / Vendor Name</label>
            <input aria-label="Party / Vendor Name" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={partyName} onChange={e => setPartyName(e.target.value)} placeholder="Vendor name" />
          </div>
          <div>
            <label className="text-xs font-medium text-ps-body block mb-1">PAN of Party</label>
            <input aria-label="PAN of Party" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm font-mono uppercase focus:outline-none focus:ring-2 focus:ring-brand" value={partyPan} onChange={e => setPartyPan(e.target.value.toUpperCase())} placeholder="ABCDE1234F" maxLength={10} />
          </div>
          <div>
            <label className="text-xs font-medium text-ps-body block mb-1">TDS Section</label>
            <select aria-label="TDS Section" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={section} onChange={e => setSection(e.target.value)}>
              {choices.deductible.length === 0 && <option value={section}>{section}</option>}
              {choices.deductible.map(k => (
                <option key={k} value={k}>{sectionOptionText(k, choices.labels)}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-ps-body block mb-1">Gross Payment (₹)</label>
            <input aria-label="Gross Payment (₹)" type="number" min="0" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={grossRupees} onChange={e => setGrossRupees(e.target.value)} placeholder="0.00" />
          </div>
          {/* No TDS Rate input. The rate is not the CA's to type: it depends on
              the section, on whether the payee is an individual or a company
              (read off the PAN's 4th character), on whether a PAN is on file at
              all (s.206AA floors it at 20%), and on the year's running total.
              A box here invited a number that the server would then ignore. */}
          <div className="col-span-2 bg-blue-50 rounded-lg px-3 py-2 space-y-1">
            <div className="flex justify-between items-center">
              <span className="text-xs text-blue-700 font-medium">
                TDS {quote && quote.explain.applies ? `§${section} @ ${quote.tds_rate_pct}%` : "on this payment"}
              </span>
              <span className="text-sm font-semibold text-blue-900">
                {quoting ? "…" : quote ? formatPaise(quote.tds_paise) : "—"}
              </span>
            </div>
            {quote && !quote.explain.applies && (
              <p className="text-2xs text-blue-800">
                Nothing is deducted — this payment is below §{section}&apos;s threshold, and
                the year&apos;s total for this payee has not reached it either.
              </p>
            )}
            {quote?.explain.rate_basis && (
              <p className="text-2xs text-blue-800">{quote.explain.rate_basis}</p>
            )}
            {quote && quote.explain.fy_prior_tds_paise > 0 && (
              <p className="text-2xs text-blue-800">
                Charged on the year&apos;s aggregate for this payee, crediting the{" "}
                {formatPaise(quote.explain.fy_prior_tds_paise)} already withheld (IT Act §200).
              </p>
            )}
            {quote && quote.quarter && (
              <p className="text-3xs text-blue-700">
                Recorded in {quote.quarter}, derived from the payment date.
              </p>
            )}
            {quote?.explain.gap_messages.map((m) => (
              <p key={m} className="text-2xs text-state-attention bg-state-attention-surface rounded px-2 py-1">{m}</p>
            ))}
            {quoteErr && <p className="text-2xs text-red-600">{quoteErr}</p>}
          </div>
          <div>
            <label htmlFor="tds-payment-date" className="text-xs font-medium text-ps-body block mb-1">Payment Date</label>
            <DateInput id="tds-payment-date" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={paymentDate} onChange={setPaymentDate} onStateChange={dates.watch("paymentDate", "Payment date")} />
          </div>
          <div>
            <label className="text-xs font-medium text-ps-body block mb-1">Challan No. (a note only)</label>
            <input aria-label="Challan No. (a note only)" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={challanNo} onChange={e => setChallanNo(e.target.value)} placeholder="Optional" />
          </div>
        </div>

        <div className="flex gap-2 pt-1">
          <button onClick={onClose} className="flex-1 border border-ps-border text-ps-label text-sm py-2 rounded-lg hover:bg-ps-bg">Cancel</button>
          {/* The shared button, not a `disabled={saving}` flag: state reaches the page a render after the click, so two clicks made back
              to back both ran this and recorded the deduction twice (found by driving the form in a browser, PRE-A-015). */}
          <Button type="button" variant="plain" size="none" onClick={handleSubmit} disabled={saving}
            className="flex-1 bg-brand text-white text-sm py-2 rounded-lg hover:bg-brand-dark disabled:opacity-50">
            {saving ? "Saving…" : "Add Deduction"}
          </Button>
        </div>
        <p className="text-3xs text-amber-600 bg-state-attention-surface rounded px-2 py-1.5">
          {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
          Deposit TDS to the government account via e-Pay Tax on incometax.gov.in (challan ITNS 281). PracticeSync does not auto-submit.
        </p>
      </div>
    </div>
  );
}

// ─── What is due for deposit ─────────────────────────────────────────────────
//
// TDS-30. On the 5th of the month the CA has to work out, per client and per
// section, how much tax was deducted last month and is due by the 7th. Every
// deduction was already a row in tds_deductions and nothing added them up, so
// they exported to Excel — the workflow this product exists to replace.
//
// Every figure here is the server's. The month is the only input, and the
// month defaults to the LAST COMPLETED one because that is the month whose
// deposit is coming due; picking the current month on the 5th would show a
// liability that is not payable until the 7th of NEXT month.

function lastCompletedMonth(): string {
  // Derived from the clock, never listed. IST is not needed for a month
  // boundary the user can change with one click, and the server stamps the
  // as-at date it actually computed against.
  const now = new Date();
  const y = now.getMonth() === 0 ? now.getFullYear() - 1 : now.getFullYear();
  const m = now.getMonth() === 0 ? 12 : now.getMonth();  // getMonth() is 0-based
  return `${y}-${String(m).padStart(2, "0")}`;
}

function DepositDuePanel({ clientId }: { clientId: string }) {
  const [month, setMonth] = useState(lastCompletedMonth());
  const [state, setState] = useState<
    | { phase: "idle" }
    | { phase: "loading" }
    | { phase: "error"; message: string }
    | { phase: "ok"; sheet: DepositDueWorksheet }
  >({ phase: "idle" });

  useEffect(() => {
    if (!clientId) { setState({ phase: "idle" }); return; }
    let live = true;
    setState({ phase: "loading" });
    fetchDepositDue(clientId, month)
      .then(sheet => { if (live) setState({ phase: "ok", sheet }); })
      .catch(e => {
        // An empty worksheet and a failed one must not look the same: a CA who
        // reads "nothing due" off a request that never landed does not pay.
        if (live) setState({ phase: "error", message: e instanceof Error ? e.message : "Could not work out what is due." });
      });
    return () => { live = false; };
  }, [clientId, month]);

  return (
    <div className="bg-white rounded-xl border border-ps-border overflow-hidden">
      <div className="px-5 py-4 border-b border-ps-border flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-sm font-semibold text-ps-ink">Due for deposit</h2>
          <p className="text-xs text-ps-hint mt-0.5">
            Rule 30(2) — the 7th of the following month, except March, which is 30 April
          </p>
        </div>
        <label className="text-xs text-ps-label flex items-center gap-2">
          Deduction month
          <input type="month" value={month} onChange={e => setMonth(e.target.value)}
            className="border border-ps-border rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-brand" />
        </label>
      </div>

      {state.phase === "loading" && (
        <p className="px-5 py-8 text-center text-xs text-ps-hint">Working it out…</p>
      )}
      {state.phase === "idle" && (
        <p className="px-5 py-8 text-center text-xs text-ps-hint">Pick a client to see what is due.</p>
      )}
      {state.phase === "error" && (
        <p className="mx-5 my-4 text-xs text-red-600 bg-state-problem-surface border border-state-problem-border rounded-lg px-3 py-2">
          {state.message} — this is a failed check, not a clear month.
        </p>
      )}

      {state.phase === "ok" && (
        <>
          <div className="px-5 py-3 border-b border-ps-border flex flex-wrap gap-x-6 gap-y-1 text-xs text-ps-label">
            <span>Due <span className="font-medium text-ps-ink">{formatDate(state.sheet.due_date)}</span></span>
            <span>Computed as at {formatDate(state.sheet.as_at)}</span>
          </div>
          {state.sheet.sections.length === 0 ? (
            <p className="px-5 py-8 text-center text-xs text-ps-hint">
              No deductions recorded for {state.sheet.month}. {state.sheet.covers}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-ps-border">
                    {["Section", "Deductees", "Tax deducted", "Deposited", "Still to deposit", "s.201(1A) interest", "Payable now"].map(h => (
                      <th key={h} className="text-left text-xs font-medium text-ps-hint px-4 py-3">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-ps-border">
                  {state.sheet.sections.map(row => (
                    <tr key={row.section} className="hover:bg-ps-bg/50">
                      <td className="px-4 py-3 text-xs font-mono text-blue-700">{row.section}</td>
                      <td className="px-4 py-3 text-xs text-ps-label">{row.deductee_count}</td>
                      <td className="px-4 py-3 text-xs text-ps-ink">{formatPaise(row.tax_paise)}</td>
                      <td className="px-4 py-3 text-xs text-ps-label">{formatPaise(row.deposited_paise)}</td>
                      <td className="px-4 py-3 text-xs font-medium text-ps-ink">{formatPaise(row.outstanding_paise)}</td>
                      <td className="px-4 py-3 text-xs">
                        {row.interest_paise > 0
                          ? <span className="text-state-problem font-medium">{formatPaise(row.interest_paise)}</span>
                          : <span className="text-ps-hint">—</span>}
                      </td>
                      <td className="px-4 py-3 text-sm font-semibold text-ps-ink">{formatPaise(row.payable_paise)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t border-ps-border bg-ps-bg">
                    <td className="px-4 py-3 text-xs font-medium text-ps-ink">Total</td>
                    <td className="px-4 py-3 text-xs text-ps-label">{state.sheet.totals.deductee_count}</td>
                    <td className="px-4 py-3 text-xs text-ps-ink">{formatPaise(state.sheet.totals.tax_paise)}</td>
                    <td className="px-4 py-3 text-xs text-ps-label">{formatPaise(state.sheet.totals.deposited_paise)}</td>
                    <td className="px-4 py-3 text-xs font-medium text-ps-ink">{formatPaise(state.sheet.totals.outstanding_paise)}</td>
                    <td className="px-4 py-3 text-xs font-medium text-state-problem">{formatPaise(state.sheet.totals.interest_paise)}</td>
                    <td className="px-4 py-3 text-sm font-semibold text-ps-ink">{formatPaise(state.sheet.totals.payable_paise)}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}

          {state.sheet.totals.late_row_count > 0 && (
            <p className="mx-5 my-3 text-xs text-amber-800 bg-state-attention-surface border border-amber-100 rounded-lg px-3 py-2">
              {state.sheet.totals.late_row_count} deduction{state.sheet.totals.late_row_count === 1 ? " is" : "s are"} past
              the Rule 30(2) date. IT Act s.201(1A)(ii) charges 1.5% for every month or part of a month
              <strong> from the date of deduction</strong>, not from the due date — so a deposit one day late
              across a month boundary carries two months of interest. Pay the interest on the same challan,
              under its own head.
            </p>
          )}

          {/* The scope note is on EVERY worksheet, not only an empty one: a
              total that looks like "the month's TDS" and is only part of it is
              the thing this panel must not be read as. */}
          <p className="mx-5 mb-4 text-2xs text-ps-hint">{state.sheet.covers}</p>

          {state.sheet.statutory_gaps.map(g => (
            <p key={g.kind} className="mx-5 mb-3 text-xs text-amber-800 bg-state-attention-surface border border-amber-100 rounded-lg px-3 py-2">
              {g.message}
              {g.deductees.length > 0 && <span className="block mt-1 text-2xs text-state-attention">{g.deductees.join(", ")}</span>}
            </p>
          ))}
        </>
      )}
    </div>
  );
}


// ─── Add Challan Modal ───────────────────────────────────────────────────────

function AddChallanModal({ clientId, choices, onClose, onAdded }: {
  // A challan is a client's deposit — tds_challans.client_id is NOT NULL.
  clientId: string;
  /** The sections a challan may be recorded under, and their names, from the server; empty until it has answered. */
  choices: SectionChoices;
  onClose: () => void;
  onAdded: (c: TDSChallan) => void;
}) {
  const [bsrCode, setBsrCode] = useState("");
  const [challanDate, setChallanDate] = useState("");
  const [serialNo, setSerialNo] = useState("");
  const [amtRupees, setAmtRupees] = useState("");
  const [period, setPeriod] = useState("Q1");
  const [section, setSection] = useState("194J");
  // From the clock, not a year typed into the source: a challan recorded under the wrong financial year is not counted for the
  // quarter it paid (the register is judged per year and quarter), and this screen opened on a year already past.
  const [fy, setFy] = useState(currentFinancialYear());
  // THE SPLIT (TDS-08/TDS-30). A challan that pays s.201(1A) interest or a
  // s.234E fee is not all tax, and until these fields existed the whole amount
  // was booked as TDS — so the section read as over-deposited and the deductee
  // annexure could not foot. Blank means zero, which is the old behaviour, so
  // a CA who has nothing extra to record types nothing extra.
  const [surchargeRupees, setSurchargeRupees] = useState("");
  const [interestRupees, setInterestRupees] = useState("");
  const [penaltyRupees, setPenaltyRupees] = useState("");
  const [minorHead, setMinorHead] = useState<"200" | "400">("200");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Text that is not a date reads as blank to the form (frontend_ux-19).
  const dates = useDateProblems();

  async function handleAdd() {
    if (dates.first) { setError(dates.first); return; }
    // Convert to paise — integer arithmetic, never float
    const amtPaise = paiseFromRupeeInput(amtRupees || "0");
    if (amtPaise === null) {
      setError("Amount must be in rupees, e.g. 125000 or 125000.50 — without commas.");
      return;
    }
    const surchargePaise = paiseFromRupeeInput(surchargeRupees || "0");
    const interestPaise = paiseFromRupeeInput(interestRupees || "0");
    const penaltyPaise = paiseFromRupeeInput(penaltyRupees || "0");
    if (surchargePaise === null || interestPaise === null || penaltyPaise === null) {
      setError("Surcharge, interest and penalty must be rupee amounts — e.g. 3600 or 3600.50, without commas.");
      return;
    }
    // The server refuses this too, with the arithmetic spelled out. Saying it
    // here as well is not a second rule: it is the same rule said before the
    // round trip, so the CA sees which figure to change while it is still on
    // the screen.
    if (surchargePaise + interestPaise + penaltyPaise > amtPaise) {
      setError("Surcharge, interest and penalty together come to more than the total. The Amount is what left the bank — tax plus those three — not the tax on its own.");
      return;
    }
    // IT WRITES SOMETHING NOW. This modal used to call onAdded() with a row
    // keyed on Date.now() and nothing else: the challan lived in React state
    // until the next render, was never sent anywhere, and the working endpoint
    // POST /api/tds-workspace/challans had no caller at all (TDS-15). A CA
    // recorded a deposit, saw it in the table, and it was gone on reload.
    //
    // Through the API rather than PostgREST because the server validates the
    // posting date against a locked period, writes the audit-log entry and
    // logs the client timeline event — none of which a browser write does.
    setSaving(true); setError(null);
    try {
      const saved = await createTdsChallan({
        client_id: clientId,
        bsr_code: bsrCode,
        challan_date: challanDate,
        amount_paise: amtPaise,
        challan_no: serialNo,
        section,
        financial_year: fy,
        quarter: period,
        surcharge_paise: surchargePaise,
        interest_paise: interestPaise,
        penalty_paise: penaltyPaise,
        minor_head: minorHead,
      });
      onAdded(saved);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not record the challan.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-brand-dark/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-ps-ink">Add Challan 281</h3>
          <button onClick={onClose}><X className="w-4 h-4 text-ps-hint" /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-ps-body block mb-1">BSR Code</label>
            <input aria-label="BSR Code" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand" value={bsrCode} onChange={e => setBsrCode(e.target.value)} placeholder="7-digit BSR code" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="tds-challan-date" className="text-xs font-medium text-ps-body block mb-1">Challan Date</label>
              <DateInput id="tds-challan-date" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={challanDate} onChange={setChallanDate} onStateChange={dates.watch("challanDate", "Challan date")} />
            </div>
            <div>
              <label className="text-xs font-medium text-ps-body block mb-1">Serial No.</label>
              <input aria-label="Serial No." className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand" value={serialNo} onChange={e => setSerialNo(e.target.value)} placeholder="00001" />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-ps-body block mb-1">Amount (₹)</label>
            <input aria-label="Amount (₹)" type="number" min="0" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={amtRupees} onChange={e => { setAmtRupees(e.target.value); setError(null); }} />
            <p className="text-3xs text-ps-hint mt-1">
              The TOTAL that left the bank. Tax is whatever is left after the three below.
            </p>
          </div>
          {/* THE HEADS THE CHALLAN ACTUALLY HAS. Migration 037 gave
              tds_challans a surcharge, interest and penalty column in 2025 and
              nothing ever wrote to any of them, so every deposit was recorded
              as pure tax. */}
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className="text-xs font-medium text-ps-body block mb-1">Surcharge (₹)</label>
              <input aria-label="Surcharge (₹)" type="number" min="0" className="w-full border border-ps-border rounded-lg px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={surchargeRupees} onChange={e => { setSurchargeRupees(e.target.value); setError(null); }} placeholder="0" />
            </div>
            <div>
              <label className="text-xs font-medium text-ps-body block mb-1" title="IT Act s.201(1A)">Interest (₹)</label>
              <input aria-label="Interest (₹)" type="number" min="0" className="w-full border border-ps-border rounded-lg px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={interestRupees} onChange={e => { setInterestRupees(e.target.value); setError(null); }} placeholder="0" />
            </div>
            <div>
              <label className="text-xs font-medium text-ps-body block mb-1" title="IT Act s.234E / s.271H">Fee (₹)</label>
              <input aria-label="Fee (₹)" type="number" min="0" className="w-full border border-ps-border rounded-lg px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={penaltyRupees} onChange={e => { setPenaltyRupees(e.target.value); setError(null); }} placeholder="0" />
            </div>
          </div>
          <p className="text-3xs text-ps-hint -mt-1">
            Interest is IT Act s.201(1A); fee is the s.234E ₹200-a-day late-filing
            charge. Leave them blank if the deposit is only tax. The Deposit Due
            panel works both out for you.
          </p>
          <div>
            <label className="text-xs font-medium text-ps-body block mb-1">Minor Head</label>
            {/* 200 vs 400 is who initiated the payment, NOT company vs
                non-company — that is the challan's major head (0020/0021) and
                migration 037's inline comment had it the other way round. */}
            <select aria-label="Minor Head" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={minorHead} onChange={e => setMinorHead(e.target.value === "400" ? "400" : "200")}>
              {(["200", "400"] as const).map(h => <option key={h} value={h}>{MINOR_HEAD_LABEL[h]}</option>)}
            </select>
          </div>
          {/* Without this the refusal above would be silent, which is worse
              than the coercion it replaced: the CA would press Add and nothing
              would happen. */}
          {error && <Callout tone="problem">{error}</Callout>}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-ps-body block mb-1">Period</label>
              <select aria-label="Period" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={period} onChange={e => setPeriod(e.target.value)}>
                {QUARTERS.map(q => <option key={q} value={q}>{QUARTER_LABEL[q]}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-ps-body block mb-1">FY</label>
              <YearPicker value={fy} onChange={setFy} />
            </div>
          </div>
          <p className="text-xs text-ps-hint">
            A challan is matched to the deductions of the quarter and financial year it is recorded for. Record it for the quarter the
            tax was deducted in, even if it was paid in the next one.
          </p>
          <div>
            <label className="text-xs font-medium text-ps-body block mb-1">Section</label>
            {/* s.192 IS offered here and only here. A challan is a DEPOSIT, and
                salary TDS is deposited on an ITNS 281 like any other — Payroll
                computes it, and the CA records the challan. The deduction form
                above deliberately excludes it. */}
            <select aria-label="Section" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={section} onChange={e => setSection(e.target.value)}>
              {choices.challan.length === 0 && <option value={section}>{section}</option>}
              {choices.challan.map(c => <option key={c.section} value={c.section}>{sectionOptionText(c.section, choices.labels)}</option>)}
            </select>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 border border-ps-border text-ps-label text-sm py-2 rounded-lg">Cancel</button>
          {/* The shared button, for the reason given on Add Deduction: a challan recorded twice doubles what the register says was deposited. */}
          <Button type="button" variant="plain" size="none" onClick={handleAdd} disabled={saving}
            className="flex-1 bg-brand text-white text-sm py-2 rounded-lg hover:bg-brand-dark disabled:opacity-50">
            {saving ? "Saving…" : "Add"}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function TDSPage() {
  // A TDS deduction belongs to one client — tds_deductions.client_id is NOT
  // NULL, and the backend's tds_repository scopes every read by firm + client.
  const { clients, clientId: selectedClientId, setClientId: setSelectedClientId } = useClientPicker();
  const [activeTab, setActiveTab] = useState(0);
  const [deductions, setDeductions] = useState<TDSDeduction[]>([]);
  const [challans, setChallans] = useState<TDSChallan[]>([]);
  // The financial year the deductions are listed for; "" is every year, as before. A client whose register passes the server's ceiling
  // is cut to its latest rows, and this is how the older years are reached (POST-A-294). It starts at "every year" for each client:
  // narrowing it to the current year by default would hide a back-dated deduction just recorded, and the cards beside the table
  // (the deposit position) are over every year.
  const [yearFilter, setYearFilter] = useState("");
  // What the server counts over ALL of the client's rows, not over the windows above: the footer under the deductions table, the
  // Returns tab's Not filed / Filed / Overdue and the Certificates Pending card. null until read (a dash, never a zero).
  const [deductionTotals, setDeductionTotals] = useState<TdsDeductionTotals | null>(null);
  const [returnCounts, setReturnCounts] = useState<TdsReturnCounts | null>(null);
  const [certificateCounts, setCertificateCounts] = useState<TdsCertificateCounts | null>(null);
  // Whether the server stopped a list at its ceiling ("Showing the latest 2000 …"), by list.
  const [cut, setCut] = useState<{ deductions: boolean; challans: boolean; certificates: boolean }>({ deductions: false, challans: false, certificates: false });
  const [certificates, setCertificates] = useState<TDSCertificate[]>([]);
  // The sections and their names, from the server, once for the page.
  const [choices, setChoices] = useState<SectionChoices>(NO_SECTIONS);
  const [choicesError, setChoicesError] = useState<string | null>(null);
  // What the challan register says became of this client's deductions (GET /deposit-state): the "not yet deposited" card and each
  // row's Deposit column. The server computes all of it; null means it has not been read, and `depositStateError` says why not.
  const [depositState, setDepositState] = useState<TdsDepositState | null>(null);
  const [depositStateError, setDepositStateError] = useState<string | null>(null);
  // What recording a challan did to the monthly deposit obligations on the compliance calendar, in the server's words.
  const [calendarAnswers, setCalendarAnswers] = useState<CalendarAnswer[] | null>(null);
  // Taking a challan out of the register (POST-A-362): the one being retracted, whether the request is out, the server's refusal if it
  // gave one, and the server's sentences about what it did not change (a month on the calendar that still reads filed, a TDS statement
  // already recorded as filed).
  const { can } = usePermissions();
  const canRetract = can("tds", "write");                 // Manager and above: the tier the server asks, and it asks again
  const { toast } = useToast();
  const [retracting, setRetracting] = useState<TDSChallan | null>(null);
  const [retractBusy, setRetractBusy] = useState(false);
  const [retractError, setRetractError] = useState<string | null>(null);
  const [retractionNotes, setRetractionNotes] = useState<string[]>([]);
  // Tying a challan to the ledger entry that paid it (POST-A-272): the challan being matched, what the server found in the ledger for
  // it, whether a read or a write is out, and the server's refusal. The tier of editing a register row (Executive and above, as for
  // recording a challan); retracting one is a tier higher. The server asks again.
  const canTie = can("tds", "compute");
  const [matching, setMatching] = useState<TDSChallan | null>(null);
  const [matchAnswer, setMatchAnswer] = useState<ChallanLedgerCandidates | null>(null);
  const [matchLoading, setMatchLoading] = useState(false);
  const [matchLoadError, setMatchLoadError] = useState<string | null>(null);
  const [matchBusy, setMatchBusy] = useState(false);
  const [matchError, setMatchError] = useState<string | null>(null);
  // Each read of the deposit state takes a number, and only the latest is allowed to land: an answer for the client open a moment
  // ago, or an earlier refresh for this one that finished late, must not replace what is on screen now.
  const depositSeq = useRef(0);
  // The client open now. A modal's answer, or an import, that finishes after the CA switched client must not take the open client's
  // read away (it would bump the counter, and the answer it lands is for a client that is no longer open).
  const openClient = useRef("");
  const [loading, setLoading] = useState(true);
  const [showAddDeduction, setShowAddDeduction] = useState(false);
  const [showAddChallan, setShowAddChallan] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [tableError, setTableError] = useState(false);
  // Why each list could not be read, if it could not: an empty list is "none recorded" only when its read succeeded, so an empty tab
  // says which of the two it is (the banner above names the first failure; this says it where the list would have been).
  const [listErrors, setListErrors] = useState<{ deductions: string | null; challans: string | null; certificates: string | null }>(
    { deductions: null, challans: null, certificates: null });
  // The real Postgres error message, distinct from tableError's narrower
  // "the tds_deductions table itself is missing" case — without this, a
  // failed firm-id lookup or tds_returns/tds_certificates query silently
  // left "Pending Returns"/"Pending Certificates" at their initial empty
  // state with no indication anything went wrong.
  const [loadErrorMessage, setLoadErrorMessage] = useState<string | null>(null);

  // `afterWrite`: the figures on screen no longer describe the books, so they are taken down until the new answer lands (a card
  // saying what it said before the challan was recorded, beside a note saying the challan was recorded, is two answers at once).
  async function refreshDepositState(clientId: string, afterWrite = false) {
    if (clientId !== openClient.current) return;
    const seq = ++depositSeq.current;
    if (afterWrite) { setDepositState(null); setDepositStateError(null); }
    try {
      const got = await fetchTdsDepositState(clientId);
      if (seq !== depositSeq.current) return;
      setDepositState(got); setDepositStateError(null);
    } catch (e) {
      if (seq !== depositSeq.current) return;
      setDepositState(null);
      setDepositStateError(e instanceof Error ? e.message : "Could not read the deposit position.");
    }
  }

  // The four lists, through the API (`rbac("tds", "read")` and the caller's client assignment run there; they never ran on the
  // direct reads this replaced), each a window the server orders, cuts and counts. The footer, the two cards and the Returns tab's
  // split are the server's counts over ALL of the client's rows. Called on a client switch and again after anything that writes, so
  // that a figure is never the browser's sum of a list it prepended to.
  const listSeq = useRef(0);
  async function loadLists(clientId: string, fresh: boolean, year: string = yearFilter) {
    // A modal's or an import's answer that lands after the CA switched client asks for a client that is no longer open: it must not
    // take a number, because that would throw away the read of the client that is.
    if (clientId !== openClient.current) return;
    const seq = ++listSeq.current;
    if (fresh) {
      setDeductions([]); setChallans([]); setCertificates([]);
      setDeductionTotals(null); setReturnCounts(null); setCertificateCounts(null);
      setCut({ deductions: false, challans: false, certificates: false });
      setListErrors({ deductions: null, challans: null, certificates: null });
      setTableError(false); setLoadErrorMessage(null);
    }
    setLoading(true);
    try {
      const [ded, chal, ret, cert] = await Promise.allSettled([
        listTdsDeductions(clientId, year || null), listTdsChallans(clientId), listTdsReturns(clientId), listTdsCertificates(clientId),
      ]);
      if (seq !== listSeq.current) return;
      const failures: string[] = [];
      const why = (r: PromiseRejectedResult) => (r.reason instanceof Error ? r.reason.message : "Could not be read.");
      if (ded.status === "fulfilled") {
        setDeductions(ded.value.rows as unknown as TDSDeduction[]); setDeductionTotals(ded.value.figures);
      } else { failures.push(why(ded)); setDeductionTotals(null); }
      if (chal.status === "fulfilled") setChallans(chal.value.rows as unknown as TDSChallan[]); else failures.push(why(chal));
      if (ret.status === "fulfilled") setReturnCounts(ret.value.figures); else { failures.push(why(ret)); setReturnCounts(null); }
      if (cert.status === "fulfilled") {
        setCertificates(cert.value.rows as unknown as TDSCertificate[]); setCertificateCounts(cert.value.figures);
      } else { failures.push(why(cert)); setCertificateCounts(null); }
      setCut({
        deductions: ded.status === "fulfilled" && ded.value.hasMore,
        challans: chal.status === "fulfilled" && chal.value.hasMore,
        certificates: cert.status === "fulfilled" && cert.value.hasMore,
      });
      setListErrors({
        deductions: ded.status === "rejected" ? why(ded) : null,
        challans: chal.status === "rejected" ? why(chal) : null,
        certificates: cert.status === "rejected" ? why(cert) : null,
      });
      setTableError(failures.length > 0);
      setLoadErrorMessage(failures.length > 0 ? failures[0] : null);
    } finally {
      // Only the read that is still the latest lowers the flag: an older one that finishes late must not clear a newer one's.
      if (seq === listSeq.current) setLoading(false);
    }
  }

  // Retract the challan chosen. The server keeps the reason and the challan in the audit log first, then removes the row, and answers
  // in words; the lists and the deposit position are read again because everything drawn from the register has changed.
  async function confirmRetract(reason: string) {
    if (!retracting || !selectedClientId) return;
    const clientAtClick = selectedClientId;
    setRetractBusy(true); setRetractError(null);
    try {
      const done = await retractTdsChallan(retracting.id, reason);
      if (clientAtClick !== openClient.current) return;      // the CA moved to another client meanwhile: nothing here is theirs to show
      setRetracting(null);
      setRetractionNotes([done.calendar_note, done.statement_note].filter((n): n is string => !!n));
      toast({ title: "Challan retracted", description: "It is out of the register. The reason is in the audit log." });
      void loadLists(clientAtClick, false);
      void refreshDepositState(clientAtClick, true);
    } catch (e) {
      // A row that is gone, or is not this firm's to see, is answered with the same two words either way; say what that means here.
      const said = e instanceof Error ? e.message : "";
      setRetractError(said === "Not found" ? "That challan is no longer in the register; it may have been retracted already." : said || "Could not retract the challan.");
    } finally {
      setRetractBusy(false);
    }
  }

  // Open the match prompt for a challan and ask the server what in the ledger could have paid it. An answer that lands after the CA
  // switched client, or after they opened another challan, is dropped.
  const matchSeq = useRef(0);
  async function openMatch(c: TDSChallan) {
    const clientAtClick = selectedClientId;
    const seq = ++matchSeq.current;
    setMatching(c); setMatchAnswer(null); setMatchLoadError(null); setMatchError(null); setMatchLoading(true);
    try {
      const answer = await fetchChallanLedgerCandidates(c.id);
      if (clientAtClick !== openClient.current || seq !== matchSeq.current) return;
      setMatchAnswer(answer);
    } catch (e) {
      if (clientAtClick !== openClient.current || seq !== matchSeq.current) return;
      const said = e instanceof Error ? e.message : "";
      setMatchLoadError(said === "Not found" ? "That challan is no longer in the register." : said || "Could not look in the ledger.");
    } finally {
      if (seq === matchSeq.current) setMatchLoading(false);
    }
  }

  function closeMatch() {
    if (matchBusy) return;
    matchSeq.current += 1;
    setMatching(null); setMatchAnswer(null); setMatchLoadError(null); setMatchError(null); setMatchLoading(false);
  }

  // Tie the challan to the entry chosen, or take the link back. The server checks the entry is this client's, debits the right account
  // and is not another challan's, and answers in words; the register is read again so the row shows the link it now has.
  async function confirmLink(journalEntryId: string) {
    if (!matching || !selectedClientId) return;
    const clientAtClick = selectedClientId;
    setMatchBusy(true); setMatchError(null);
    try {
      await linkChallanPayment(matching.id, journalEntryId);
      if (clientAtClick !== openClient.current) return;
      closeMatchAfterWrite();
      toast({ title: "Challan tied to the ledger entry", description: "Nothing was posted. The challan now points at the entry that paid it." });
      void loadLists(clientAtClick, false);
    } catch (e) {
      setMatchError(e instanceof Error && e.message ? e.message : "Could not tie the challan to that entry.");
    } finally {
      setMatchBusy(false);
    }
  }

  async function confirmUnlink() {
    if (!matching || !selectedClientId) return;
    const clientAtClick = selectedClientId;
    setMatchBusy(true); setMatchError(null);
    try {
      await unlinkChallanPayment(matching.id);
      if (clientAtClick !== openClient.current) return;
      closeMatchAfterWrite();
      toast({ title: "Link taken back", description: "The challan reads \"not tied to an entry\" again. The entry is untouched." });
      void loadLists(clientAtClick, false);
    } catch (e) {
      setMatchError(e instanceof Error && e.message ? e.message : "Could not take the link back.");
    } finally {
      setMatchBusy(false);
    }
  }

  function closeMatchAfterWrite() {
    matchSeq.current += 1;
    setMatching(null); setMatchAnswer(null); setMatchLoadError(null); setMatchError(null); setMatchLoading(false);
  }

  useEffect(() => {
    // A client switch starts from nothing, so no card or row can show the previous client's figures while this one is read, and a
    // failure for the previous client does not blank this one's cards.
    openClient.current = selectedClientId;
    depositSeq.current += 1;
    setDepositState(null); setDepositStateError(null); setCalendarAnswers(null);
    setRetracting(null); setRetractError(null); setRetractionNotes([]);
    matchSeq.current += 1;
    setMatching(null); setMatchAnswer(null); setMatchLoadError(null); setMatchError(null); setMatchLoading(false);
    setYearFilter("");
    // client_id is required by the reads below; an empty string would be refused.
    if (!selectedClientId) {
      listSeq.current += 1;
      setDeductions([]); setChallans([]); setCertificates([]);
      setDeductionTotals(null); setReturnCounts(null); setCertificateCounts(null);
      setListErrors({ deductions: null, challans: null, certificates: null });
      setTableError(false); setLoadErrorMessage(null); setLoading(false);
      return;
    }
    void refreshDepositState(selectedClientId);
    void loadLists(selectedClientId, true, "");
    return () => { listSeq.current += 1; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedClientId]);

  // The section names and the sections a deduction or a challan may be recorded under, from the server, once.
  useEffect(() => {
    let alive = true;
    listTdsSections()
      .then((r) => { if (alive) { setChoices(sectionChoices(r)); setChoicesError(null); } })
      .catch((e) => { if (alive) setChoicesError(e instanceof Error ? e.message : "Could not read the TDS sections."); });
    return () => { alive = false; };
  }, []);

  // The answer counts only for the client that is open: it is cleared on a switch, and this holds the cards and the column to it
  // if an answer for another one were ever still in state.
  const depositForClient = depositState && depositState.client_id === selectedClientId ? depositState : null;
  // Every count and total on this screen is the server's (`domain/tds/screen_counts`), taken over all of the client's rows and not
  // over the window a list shows. Overdue is derived there: `tds_returns` stores no such status, and a return is overdue when it is
  // not filed and its Rule 31A due date has passed, on the Indian day.
  const returnTabCounts = returnCounts ? [
    { label: "Not filed", n: returnCounts.not_filed },
    { label: "Filed", n: returnCounts.filed },
    { label: "Overdue", n: returnCounts.overdue },
  ] : null;

  // ── Deductions DataTable columns — money in integer paise, aligned right ────
  const deductionColumns: Column<TDSDeduction>[] = useMemo(() => [
    {
      key: "party_name", header: "Party Name", accessor: (d) => d.deductee_name,
      searchable: true, sortable: true, sticky: true, hideable: false,
      render: (d) => <span className="font-medium text-ps-ink">{d.deductee_name}</span>,
    },
    {
      key: "party_pan", header: "PAN", accessor: (d) => d.deductee_pan ?? "", searchable: true,
      render: (d) => <span className="font-mono text-xs text-ps-label">{d.deductee_pan || "—"}</span>,
    },
    {
      key: "section", header: "Section", accessor: (d) => d.section, sortable: true,
      render: (d) => (
        <>
          <span className="text-xs font-mono font-medium text-blue-700 bg-blue-50 px-1.5 py-0.5 rounded">{d.section}</span>
          <p className="text-3xs text-ps-hint mt-0.5">{choices.labels[d.section]}</p>
        </>
      ),
    },
    {
      key: "transaction_date", header: "Payment Date", accessor: (d) => d.transaction_date, sortable: true,
      render: (d) => <span className="text-xs text-ps-label">{formatDate(d.transaction_date)}</span>,
    },
    {
      key: "gross_amount_paise", header: "Gross Amount", accessor: (d) => d.payment_amount_paise,
      sortable: true, align: "right", exportValue: (d) => d.payment_amount_paise / 100,
      render: (d) => <span className="text-ps-ink">{formatPaise(d.payment_amount_paise)}</span>,
    },
    {
      key: "tds_rate", header: "TDS Rate", accessor: (d) => d.tds_rate_pct, sortable: true, align: "right",
      render: (d) => <span className="text-xs text-ps-label">{d.tds_rate_pct}%</span>,
    },
    {
      key: "tds_amount_paise", header: "TDS Amount", accessor: (d) => d.tds_paise,
      sortable: true, align: "right", exportValue: (d) => d.tds_paise / 100,
      render: (d) => <span className="font-medium text-ps-ink">{formatPaise(d.tds_paise)}</span>,
    },
    {
      // What the challan register says became of this deduction (the server's words). It used to print `challan_no`, a field
      // nothing writes for a deduction a purchase bill creates, so it was a dash for nearly every row.
      key: "deposit", header: "Deposit",
      accessor: (d) => {
        const row = depositForClient?.deductions[d.id];
        return row ? depositForClient?.legend[row.state]?.label ?? "" : "";
      },
      // A CSV says what the screen says: the label alone would read "Not deposited" for tax not due until next month, and "Deposited"
      // for a deposit made four months late.
      exportValue: (d) => {
        const row = depositForClient?.deductions[d.id];
        if (!row) return "";
        const label = depositForClient?.legend[row.state]?.label ?? "";
        return [label, row.due_note, row.challans && row.challans.length > 0 ? `challan ${row.challans.join(", ")}` : null]
          .filter(Boolean).join(". ");
      },
      render: (d) => {
        const row = depositForClient?.deductions[d.id];
        if (!depositForClient || !row) {
          return (
            <span className="text-xs text-ps-hint"
              title={depositStateError ?? (depositForClient ? "This deduction was added after the deposit state was read."
                : "The deposit position has not been read yet.")}>
              {depositStateError ? "Not read" : depositForClient ? "Added after the read" : "—"}
            </span>
          );
        }
        const words = depositForClient.legend[row.state];
        // A row's own sentence (a part's rupees, a challan dated before the tax) replaces the state's.
        const sentence = row.detail ?? words?.sentence;
        // Not yet due is not a failure, and a deposit made late or with a challan dated before the tax is not drawn as ready: the
        // server says which (`overdue`, `paid_late`, `dated_before`).
        const tone = row.state === "deposited" ? (row.paid_late || row.dated_before ? "text-state-attention" : "text-state-ready")
          : row.state === "part" || row.state === "not_deposited" ? (row.overdue ? "text-state-problem" : "text-state-attention")
          : "text-ps-label";
        // A sentence about THIS row (a part's rupees, a challan dated before the tax) is read on the screen, and not only in a hover
        // title that reaches neither a keyboard nor a touch screen; the generic ones (the same for every row of a state) are said once
        // under the cards and are a tooltip and screen-reader text here, so a client with hundreds of rows is not a wall of repeats.
        const shown = row.state === "part" || row.dated_before === true;
        return (
          <span className="block" title={sentence}>
            <span className={`text-xs font-medium ${tone}`}>{words?.label ?? "—"}</span>
            {sentence && !shown && <span className="sr-only">{`. ${sentence}`}</span>}
            {sentence && shown && <span className="block max-w-xs text-3xs leading-snug text-ps-label">{sentence}</span>}
            {row.due_note && <span className={`block text-3xs leading-snug ${row.overdue || row.paid_late ? "text-state-problem" : "text-state-attention"}`}>{row.due_note}</span>}
            {row.challans && row.challans.length > 0 && <span className="block font-mono text-3xs text-ps-hint">{row.challans.join(", ")}</span>}
          </span>
        );
      },
    },
  ], [depositForClient, depositStateError, choices.labels]);

  const deductionFilters: FilterDef<TDSDeduction>[] = useMemo(() => [
    {
      key: "section", label: "Section", type: "select", accessor: (d) => d.section,
      options: choices.filterable.map((k) => ({ value: k, label: sectionOptionText(k, choices.labels) })),
    },
    {
      key: "quarter", label: "Quarter", type: "select", accessor: (d) => d.quarter,
      options: QUARTERS.map((q) => ({ value: q, label: QUARTER_LABEL[q] })),
    },
  ], [choices]);

  return (
    <div className="p-6 max-w-ps-data mx-auto space-y-6">
      <PageHeader
        title="TDS Module"
        subtitle="Tax Deducted at Source — IT Act Chapter XVII-B"
        actions={
          <>
            {/* Deductions are per client, so the client is chosen before anything
                can be recorded or listed. */}
            <div className="min-w-[240px]">
              <label className="block text-xs font-medium text-ps-label mb-1">Client *</label>
              <ClientLookup clients={clients} value={selectedClientId} onChange={setSelectedClientId} />
            </div>
          </>
        }
      />

      {!selectedClientId && (
        <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 text-sm text-blue-800">
          Select a client to view and record their TDS deductions.
        </div>
      )}

      {tableError && (
        <div className="bg-state-attention-surface border border-state-attention-border rounded-lg px-4 py-3 flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
          <p className="text-sm text-state-attention">
            {loadErrorMessage ?? (
              <>TDS deductions table not found. Run migration to create <code className="font-mono bg-amber-100 px-1 rounded">tds_deductions</code> table.</>
            )}
          </p>
        </div>
      )}

      {choicesError && (
        <Callout tone="attention" title="The TDS sections could not be read">
          {choicesError} The section lists in the forms below stay empty until they can be.
        </Callout>
      )}

      {/* What recording a challan did to the compliance calendar, in the server's words. The live region is always on the page, so
          that what is put in it is announced; the tone is attention only for a month the server left open. */}
      <div role="status" className="space-y-2 empty:!mt-0">
        {calendarAnswers && calendarAnswers.length > 0 && (
          <>
            <Callout tone={calendarAnswers.some(a => a.needs_action) ? "attention" : "note"}
              title="Challan recorded. What became of the monthly deposits on the compliance calendar:">
              <ul className="list-disc pl-5 space-y-1">
                {calendarAnswers.map((a, i) => (
                  <li key={`${a.month ?? "all"}-${i}`}>{a.message}</li>
                ))}
              </ul>
            </Callout>
            <button type="button" onClick={() => setCalendarAnswers(null)} className="text-xs text-ps-label underline">Dismiss</button>
          </>
        )}
        {retractionNotes.length > 0 && (
          <>
            <Callout tone="attention" title="Challan retracted. What it did not change:">
              <ul className="list-disc pl-5 space-y-1">
                {retractionNotes.map((n, i) => <li key={i}>{n}</li>)}
              </ul>
            </Callout>
            <button type="button" onClick={() => setRetractionNotes([])} className="text-xs text-ps-label underline">Dismiss</button>
          </>
        )}
      </div>
      {/* Summary cards. A figure is shown only when it was read for the client chosen: before one is chosen, while the screen is
          reading and when a read failed, the card says so and shows a dash (an unknown is never shown as a value). */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          {
            // The server's total (everything deducted for the client, surcharge and cess included), so that this card and the next
            // count tax the same way.
            icon: <IndianRupee className="w-4 h-4 text-blue-600" />, bg: "bg-blue-50", label: "Total TDS Deducted",
            value: !selectedClientId || !depositForClient ? "—" : formatPaise(depositForClient.totals.deducted_paise),
            sub: !selectedClientId ? "Choose a client" : depositStateError ? "Could not be read" : !depositForClient ? "Reading"
              : "Recorded here, with surcharge and cess (salary tax is in payroll)", note: null as string | null,
          },
          {
            // A figure only where the server could judge one: no read yet, a failed read, a position that could not be read and
            // tax that no recorded challan can be set against all show a dash and say why.
            icon: <FileText className="w-4 h-4 text-amber-600" />, bg: "bg-state-attention-surface", label: "Tax not yet deposited",
            value: !selectedClientId || !depositForClient?.position || !depositForClient.position.figure_known ? "—"
              : formatPaise(depositForClient.position.undeposited_paise),
            sub: !selectedClientId ? "Choose a client"
              : depositStateError ? "Could not be read"
              : !depositForClient ? "Reading the challan register"
              : !depositForClient.position ? "The position could not be read"
              : depositForClient.position.basis,
            note: depositForClient?.position?.caveat ?? null,
          },
          {
            icon: <Calendar className="w-4 h-4 text-red-600" />, bg: "bg-state-problem-surface", label: "Returns Due",
            value: !selectedClientId || !returnCounts ? "—" : String(returnCounts.not_filed),
            sub: !selectedClientId ? "Choose a client" : !returnCounts ? (loading ? "Reading" : "Could not be read") : "24Q/26Q/27Q", note: null as string | null,
          },
          {
            icon: <Award className="w-4 h-4 text-purple-600" />, bg: "bg-purple-50", label: "Certificates Pending",
            value: !selectedClientId || !certificateCounts ? "—" : String(certificateCounts.pending),
            sub: !selectedClientId ? "Choose a client" : !certificateCounts ? (loading ? "Reading" : "Could not be read") : "Form 16/16A", note: null as string | null,
          },
        ].map(c => (
          <div key={c.label} className="bg-white rounded-xl border border-ps-border p-4">
            <div className="flex items-center gap-2 mb-3">
              <div className={`w-8 h-8 rounded-lg ${c.bg} flex items-center justify-center`}>{c.icon}</div>
              <span className="text-xs text-ps-label">{c.label}</span>
            </div>
            <p className="text-lg font-semibold text-ps-ink">{c.value}</p>
            <p className="text-xs text-ps-hint mt-0.5">{c.sub}</p>
            {c.note && <p className="text-3xs leading-snug text-state-attention mt-1.5">{c.note}</p>}
          </div>
        ))}
      </div>
      {depositStateError && (
        <Callout tone="attention" title="The deposit state could not be read">
          {depositStateError}. The Deposit column and the undeposited figure are not shown until it can be.
        </Callout>
      )}
      {depositForClient && <p className="text-xs text-ps-hint">Deposit state read from {depositForClient.read}</p>}
      {depositForClient && Object.values(depositForClient.deductions).some(r => r.state === "not_deposited") && (
        <p className="text-xs text-ps-hint">Not deposited: {depositForClient.legend.not_deposited.sentence}</p>
      )}
      {depositForClient && depositForClient.warnings.length > 0 && (
        <Callout tone="attention" title="About the challans recorded for this client">
          <ul className="list-disc pl-5 space-y-1">
            {depositForClient.warnings.map((w, i) => <li key={`${w.code}-${i}`}>{w.message}</li>)}
          </ul>
        </Callout>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-ps-border">
        {TABS.map((tab, i) => (
          <button key={tab} onClick={() => setActiveTab(i)}
            className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === i ? "border-brand text-blue-700" : "border-transparent text-ps-label hover:text-ps-body"}`}>
            {tab}
          </button>
        ))}
      </div>

      {/* This firm-wide workspace holds only Deductions/Challans/Returns/
          Certificates. 26AS Reconciliation and §197 Lower-Deduction
          Certificates live on the client's own Compliance → TDS workspace —
          not duplicated here, just pointed to, once a client is selected. */}
      {selectedClientId && (
        <Callout tone="note">
          26AS Reconciliation and §197 Lower-Deduction Certificates are on{" "}
          <Link href={`/clients/${selectedClientId}/compliance/tds`} className="underline font-medium">
            this client&apos;s Compliance → TDS workspace
          </Link>
          , not here.
        </Callout>
      )}

      {/* Tab: Deductions — shared DataTable (search, filters, sort, pagination, export, prefs) */}
      {activeTab === 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-ps-ink">TDS Deductions</h2>
              <p className="text-xs text-ps-hint mt-0.5">IT Act Section 194 — deductions recorded</p>
            </div>
            <div className="flex items-center gap-2">
              {/* Nothing to narrow until a client is open (a read with no client is refused), and the footer and the cut notice
                  describe the PREVIOUS choice until the new answer lands, so they come down at once. */}
              <YearPicker value={yearFilter} placeholder="All years" count={10} size="sm" className="w-auto" disabled={loading || !selectedClientId}
                onChange={(v) => {
                  if (!selectedClientId) return;
                  setYearFilter(v); setDeductionTotals(null); setCut((c) => ({ ...c, deductions: false }));
                  void loadLists(selectedClientId, false, v);
                }} />
              <button onClick={() => setShowImport(true)}
                className="flex items-center gap-1.5 border border-ps-border text-ps-label text-xs px-3 py-1.5 rounded-lg hover:bg-ps-bg">
                <Upload className="w-3.5 h-3.5" /> Import CSV
              </button>
              <button onClick={() => setShowAddDeduction(true)}
                className="flex items-center gap-1.5 bg-brand text-white text-xs px-3 py-1.5 rounded-lg hover:bg-brand-dark">
                <Plus className="w-3.5 h-3.5" /> Add Deduction
              </button>
            </div>
          </div>

          <DataTable
            data={deductions}
            columns={deductionColumns}
            filters={deductionFilters}
            getRowId={(d) => d.id}
            loading={loading}
            error={listErrors.deductions}
            searchPlaceholder="Search by party name or PAN…"
            initialSort={{ key: "transaction_date", dir: "desc" }}
            exportFilename="tds-deductions"
            persistKey="tds.deductions"
            emptyTitle={yearFilter ? `No deductions recorded for FY ${yearFilter}` : "No deductions recorded yet"}
            emptyDescription={yearFilter
              ? "Nothing is recorded in this financial year. Choose another year, or record a deduction."
              : "A deduction is one payment on which tax was withheld. Record each one so the challans and the quarterly statement can be built from them."}
            emptyAction={
              <EmptyStateActions>
                <EmptyStateAction requires={["tds", "compute"]} icon={<Plus size={14} />} label="Add Deduction"
                  onClick={() => setShowAddDeduction(true)} />
              </EmptyStateActions>
            }
          />

          <ListWindowNotice hasMore={cut.deductions}
            what={`the latest ${deductions.length} deductions${yearFilter ? ` of FY ${yearFilter}` : ""}`} limit={deductions.length}
            maxLimit={deductions.length}
            elsewhere={yearFilter
              ? `The totals below are over all of this client's deductions of FY ${yearFilter}.`
              : "Choose a financial year above to see the older ones. The totals below are over all of this client's deductions."} />
          {deductionTotals && deductionTotals.count > 0 && (
            <div className="flex flex-wrap justify-end gap-x-6 gap-y-1 px-1 text-xs text-ps-label">
              {yearFilter && <span className="font-medium">FY {yearFilter}</span>}
              <span>Total Gross: <span className="font-semibold text-ps-ink">{formatPaise(deductionTotals.payment_amount_paise)}</span></span>
              <span>Total of the TDS Amount column: <span className="font-semibold text-ps-ink">{formatPaise(deductionTotals.tds_paise)}</span></span>
            </div>
          )}
        </div>
      )}

      {/* Tab: Challans */}
      {activeTab === 1 && (
        <div className="space-y-4">
        <DepositDuePanel clientId={selectedClientId} />
        <div className="bg-white rounded-xl border border-ps-border overflow-hidden">
          <div className="px-5 py-4 border-b border-ps-border flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-ps-ink">Challan 281 Tracker</h2>
              <p className="text-xs text-ps-hint mt-0.5">IT Act Section 200(1) — TDS deposit challans</p>
            </div>
            <button onClick={() => setShowAddChallan(true)}
              className="flex items-center gap-1.5 bg-brand text-white text-xs px-3 py-1.5 rounded-lg hover:bg-brand-dark">
              <Plus className="w-3.5 h-3.5" /> Add Challan
            </button>
          </div>
          <ListWindowNotice hasMore={cut.challans} what={`the latest ${challans.length} challans`} limit={challans.length}
            maxLimit={challans.length} />
          {challans.length === 0 && (loading || listErrors.challans) ? (
            <ListNotRead loading={loading} error={listErrors.challans} what="challans" />
          ) : challans.length === 0 ? (
            <EmptyState
              className="py-10"
              title="No challans added yet"
              description="A challan is one deposit of tax withheld, with its BSR code, date and serial number. Record each deposit so a quarter's statement can be matched to it."
              action={
                <EmptyStateActions>
                  <EmptyStateAction requires={["tds", "compute"]} icon={<Plus size={14} />} label="Add Challan"
                    onClick={() => setShowAddChallan(true)} />
                </EmptyStateActions>
              }
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-ps-border">
                    {["BSR Code", "Payment Date", "Challan No.", "Amount", "Period", "FY", "Section", "Minor head", "Ledger"].map(h => (
                      <th key={h} className="text-left text-xs font-medium text-ps-hint px-4 py-3">{h}</th>
                    ))}
                    {canRetract && <th className="text-left text-xs font-medium text-ps-hint px-4 py-3"><span className="sr-only">Actions</span></th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-ps-border">
                  {challans.map(c => (
                    <tr key={c.id} className="hover:bg-ps-bg/50">
                      <td className="px-4 py-3 text-xs font-mono text-ps-ink">{c.bsr_code || "—"}</td>
                      <td className="px-4 py-3 text-xs text-ps-label">{formatDate(c.payment_date)}</td>
                      <td className="px-4 py-3 text-xs font-mono text-ps-label">{c.challan_no || "—"}</td>
                      {/* total_paise, not tds_paise: a challan can carry
                          interest and penalty as well as tax, and the tracker
                          is about what was DEPOSITED. */}
                      <td className="px-4 py-3 text-sm font-medium text-ps-ink">{formatPaise(c.total_paise)}</td>
                      <td className="px-4 py-3 text-xs text-ps-label">{QUARTER_LABEL[c.quarter] ?? c.quarter}</td>
                      <td className="px-4 py-3 text-xs text-ps-label">{c.financial_year}</td>
                      <td className="px-4 py-3 text-xs font-mono text-blue-700">{c.section ?? "—"}</td>
                      <td className="px-4 py-3 text-xs text-ps-label">{minorHeadLabel(c.minor_head)}</td>
                      <td className="px-4 py-3 text-xs">
                        {c.journal_entry_id
                          ? <span className={c.ledger_link && c.ledger_link.state !== "live" ? "text-state-attention" : "text-state-ready"}>
                              {c.ledger_link?.label ?? "Tied to an entry"}
                            </span>
                          : <span className="text-ps-hint">Not tied</span>}
                        {" "}
                        <button type="button" onClick={() => void openMatch(c)}
                          aria-label={`${c.journal_entry_id ? "Open the ledger link of" : "Match"} challan ${c.challan_no || c.bsr_code || ""} of ${formatDate(c.payment_date)} ${c.journal_entry_id ? "" : "to the ledger"}`.replace(/\s+/g, " ").trim()}
                          className="text-xs text-brand underline">
                          {c.journal_entry_id ? "View" : "Match"}
                        </button>
                      </td>
                      {canRetract && (
                        <td className="px-4 py-3 text-right">
                          <button type="button" onClick={() => { setRetractError(null); setRetracting(c); }}
                            aria-label={`Retract challan ${c.challan_no || c.bsr_code || ""} of ${formatDate(c.payment_date)}`.replace(/\s+/g, " ")}
                            className="text-xs text-state-problem underline">
                            Retract
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        </div>
      )}

      {/* Tab: Returns */}
      {activeTab === 2 && (
        <div className="space-y-4">
          <div className="bg-state-attention-surface border border-amber-100 rounded-lg px-4 py-3 flex gap-2">
            {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
            <AlertCircle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
            <p className="text-sm text-state-attention">File 24Q/26Q returns manually on the Income Tax e-filing portal (incometax.gov.in), under the deductor&apos;s TAN login. TRACES is post-filing only (Form 16/16A, defaults, corrections). PracticeSync does not auto-submit to any government portal.</p>
          </div>
          <div className="bg-white rounded-xl border border-ps-border overflow-hidden">
            <div className="px-5 py-4 border-b border-ps-border flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-ps-ink">TDS Returns (24Q / 26Q / 27Q)</h2>
                <p className="text-xs text-ps-hint mt-0.5">IT Act Section 200(3) — quarterly TDS return filing status</p>
              </div>
              <Link
                href="/tds/returns"
                className="flex items-center gap-1.5 text-xs bg-brand text-white px-3 py-2 rounded-lg hover:bg-brand-dark shrink-0"
              >
                Prepare a Return <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </div>
            {/* Counted from the CHECK's own vocabulary, and OVERDUE is derived
                rather than stored: tds_returns has no such status — a return is
                overdue when it is not filed and its Rule 31A due date has
                passed. Counting r.status === "Overdue" could only ever be 0. */}
            <div className="px-5 py-4 grid grid-cols-3 gap-4 text-center">
              {(returnTabCounts ?? ["Not filed", "Filed", "Overdue"].map((label) => ({ label, n: null as number | null }))).map(({ label, n }) => (
                <div key={label}>
                  <p className="text-2xl font-semibold text-ps-ink">{n === null ? "—" : n}</p>
                  <p className="text-xs text-ps-label mt-0.5">{label}</p>
                </div>
              ))}
            </div>
            <p className="px-5 pb-4 text-xs text-ps-hint">
              Generate, review, and mark a specific quarter&apos;s return as filed in{" "}
              <Link href="/tds/returns" className="text-blue-600 hover:underline">Prepare a Return</Link>.
            </p>
          </div>
        </div>
      )}

      {/* Tab: Certificates */}
      {activeTab === 3 && (
        <div className="bg-white rounded-xl border border-ps-border overflow-hidden">
          <div className="px-5 py-4 border-b border-ps-border">
            <h2 className="text-sm font-semibold text-ps-ink">Form 16A Certificates</h2>
            <p className="text-xs text-ps-hint mt-0.5">TDS certificates issued to deductees — IT Act Section 203</p>
          </div>
          <ListWindowNotice hasMore={cut.certificates} what={`the latest ${certificates.length} certificates`} limit={certificates.length}
            maxLimit={certificates.length} />
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-ps-border">
                  {["Form", "Deductee Name", "PAN", "Period", "TDS Amount", "Issue Date", "Status"].map(h => (
                    <th key={h} className="text-left text-xs font-medium text-ps-hint px-4 py-3">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-ps-border">
                {certificates.map(c => (
                  <tr key={c.id} className="hover:bg-ps-bg/50">
                    {/* certificate_form is the FY's own name for it, derived
                        server-side: from 01-04-2026 Form 16 is 130 and 16A is
                        131 (CBDT Notification 22/2026). Falls back to the
                        stored key for a row read straight from PostgREST. */}
                    <td className="px-4 py-3 text-xs text-ps-label">Form {c.certificate_form ?? c.certificate_type}</td>
                    <td className="px-4 py-3 text-sm font-medium text-ps-ink">{c.deductee_name}</td>
                    <td className="px-4 py-3 text-xs font-mono text-ps-label">{c.deductee_pan}</td>
                    {/* financial_year + quarter, the two real columns. `period`
                        never existed, so this cell rendered nothing at all. A
                        Form 16 is annual and has no quarter. */}
                    <td className="px-4 py-3 text-xs text-ps-label">
                      {c.quarter ? `${QUARTER_LABEL[c.quarter] ?? c.quarter} ` : ""}{c.financial_year}
                    </td>
                    <td className="px-4 py-3 text-sm font-medium text-ps-ink">{formatPaise(c.tds_deducted_paise ?? 0)}</td>
                    <td className="px-4 py-3 text-xs text-ps-label">{formatDate(c.issued_at)}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_STYLE[c.status] ?? ""}`}>
                        {STATUS_LABEL[c.status] ?? c.status}
                      </span>
                    </td>
                  </tr>
                ))}
                {certificates.length === 0 && (loading || listErrors.certificates) && (
                  <tr><td colSpan={7}><ListNotRead loading={loading} error={listErrors.certificates} what="certificates" /></td></tr>
                )}
                {certificates.length === 0 && !loading && !listErrors.certificates && (
                  <tr><td colSpan={7} className="px-4 py-10 text-center text-sm text-ps-hint">
                    No certificates for this client yet. Generate a draft from the client&apos;s Compliance → TDS tab.
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {showAddDeduction && selectedClientId && (
        <AddDeductionModal clientId={selectedClientId} choices={choices} onClose={() => setShowAddDeduction(false)}
          onAdded={() => { void loadLists(selectedClientId, false); void refreshDepositState(selectedClientId, true); }} />
      )}
      {showAddChallan && selectedClientId && (
        <AddChallanModal clientId={selectedClientId} choices={choices} onClose={() => setShowAddChallan(false)}
          onAdded={c => {
            void loadLists(selectedClientId, false);
            setCalendarAnswers(c.compliance_obligations ?? null);
            void refreshDepositState(selectedClientId, true);
          }} />
      )}

      {retracting && selectedClientId && (
        <RetractChallanModal
          intro={`Challan ${retracting.challan_no || "(no serial number)"} of ${formatDate(retracting.payment_date)} for ${formatPaise(retracting.total_paise)}, `
            + `${QUARTER_LABEL[retracting.quarter] ?? retracting.quarter} of ${retracting.financial_year}.`}
          busy={retractBusy} error={retractError}
          onConfirm={confirmRetract}
          onClose={() => { if (!retractBusy) { setRetracting(null); setRetractError(null); } }} />
      )}

      {matching && selectedClientId && (
        <MatchChallanToLedgerModal
          intro={`Challan ${matching.challan_no || "(no serial number)"} of ${formatDate(matching.payment_date)} for ${formatPaise(matching.total_paise)}, `
            + `${QUARTER_LABEL[matching.quarter] ?? matching.quarter} of ${matching.financial_year}.`}
          answer={matchAnswer} loading={matchLoading} loadError={matchLoadError}
          busy={matchBusy} error={matchError} canTie={canTie}
          onLink={confirmLink} onUnlink={confirmUnlink}
          onClose={closeMatch} />
      )}

      {showImport && selectedClientId && (
        <CsvImportModal
          title="Import TDS Deductions from CSV"
          columns={TDS_IMPORT_COLUMNS}
          templateFilename="practicesync-tds-template.xlsx"
          onClose={() => setShowImport(false)}
          onImport={async (rows: ImportRow[]) => {
            let imported = 0;
            const errors: string[] = [];
            // ONE ROW AT A TIME, THROUGH THE ENGINE, IN ORDER. Not a
            // performance choice: each row's tax depends on the year's running
            // total for that payee under that section, so row 4 cannot be
            // resolved until rows 1-3 are on the register. IT Act §194C(5) and
            // the parallel "aggregate of the sums" limbs.
            //
            // The spreadsheet's own tds_rate column is DELIBERATELY NOT READ.
            // It used to be: `parseFloat(row.tds_rate) `, then
            // `Math.round(grossPaise * rate / 100)` — so whatever a CA had
            // typed into a spreadsheet became the withholding, unchecked
            // against the section on the same row, with parseFloat("abc")
            // giving NaN and JSON.stringify sending that as null into a
            // NOT NULL column. The rate is the engine's answer now.
            for (const row of rows) {
              // Skip and report rather than block the import, but never coerce
              // — "1,25,000" in a spreadsheet column is exactly how an amount
              // gets there, and parseFloat reads it as 1.
              const grossPaise = paiseFromRupeeInput(row.gross_amount_rs ?? "0");
              if (grossPaise === null) {
                errors.push(`${row.party_name ?? "row"}: gross_amount_rs must be a `
                            + "plain amount in rupees, without commas");
                continue;
              }
              try {
                await createTdsDeduction({
                  client_id: selectedClientId,
                  deductee_name: row.party_name,
                  deductee_pan: row.party_pan?.toUpperCase() || null,
                  section: row.section,
                  payment_amount_paise: grossPaise,
                  transaction_date: row.payment_date,
                  challan_no: row.challan_no || null,
                });
                imported++;
              } catch (e) {
                errors.push(`${row.party_name}: ${e instanceof Error ? e.message : "failed"}`);
              }
            }
            if (imported > 0) {
              void loadLists(selectedClientId, false);
              void refreshDepositState(selectedClientId, true);
            }
            return { imported, errors };
          }}
          validateRow={(row) => {
            const errs: string[] = [];
            const panIssue = row.party_pan?.trim() ? panProblem(row.party_pan) : "PAN is required. IT Act §139A — e.g. AABCU9603R.";
            if (panIssue) errs.push(panIssue);
            if (row.payment_date && !/^\d{4}-\d{2}-\d{2}$/.test(row.payment_date)) errs.push("payment_date must be YYYY-MM-DD");
            if (row.gross_amount_rs && isNaN(parseFloat(row.gross_amount_rs))) errs.push("gross_amount_rs must be a number");
            return errs;
          }}
        />
      )}
    </div>
  );
}
