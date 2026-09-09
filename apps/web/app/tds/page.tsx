"use client";

/**
 * TDS Module — Tax Deducted at Source
 * IT Act Chapter XVII-B: Deduction and Collection of Tax at Source
 * Section 192: TDS on Salary
 * Section 194A: TDS on Interest (threshold ₹40,000 bank, ₹5,000 others)
 * Section 194C: TDS on Contractor Payments (1% individual, 2% company)
 * Section 194D: TDS on Insurance Commission (5%)
 * Section 194H: TDS on Commission/Brokerage (5%)
 * Section 194I: TDS on Rent (10%)
 * Section 194J: TDS on Professional/Technical Fees (10%)
 * Section 194Q: TDS on Purchase of Goods (0.1%)
 * Section 200: TDS deposit and return filing obligations
 * Section 203: Issuance of TDS certificates
 */

import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { useState, useEffect, useMemo } from "react";
import Link from "next/link";
import {
  IndianRupee, Calendar, AlertCircle, Plus, X, FileText, Award, Upload, ArrowRight,
} from "lucide-react";
import CsvImportModal, { type ImportRow } from "@/components/CsvImportModal";
import { DataTable } from "@/components/ui/data-table";
import type { Column, FilterDef } from "@/lib/table/types";

const TDS_IMPORT_COLUMNS = [
  { key: "party_name",      label: "Party Name",       required: true,  hint: "Name of deductee e.g. ABC Consulting" },
  { key: "party_pan",       label: "Party PAN",        required: true,  hint: "e.g. AABCU9603R" },
  { key: "section",         label: "TDS Section",      required: true,  hint: "e.g. 194C | 194J | 194A | 192" },
  { key: "gross_amount_rs", label: "Gross Amount (₹)", required: true,  hint: "e.g. 100000 (in rupees)" },
  { key: "tds_rate",        label: "TDS Rate %",       required: true,  hint: "e.g. 10 (for 10%)" },
  { key: "payment_date",    label: "Payment Date",     required: true,  hint: "YYYY-MM-DD e.g. 2025-05-15" },
  { key: "fy",              label: "Financial Year",   required: true,  hint: "e.g. 2025-26" },
  { key: "quarter",         label: "Quarter",          required: true,  hint: "Q1 (Apr-Jun) | Q2 (Jul-Sep) | Q3 (Oct-Dec) | Q4 (Jan-Mar)" },
  { key: "challan_no",      label: "Challan No",       required: false, hint: "BSR code + serial e.g. 0510001-12345" },
];

const PAN_RE_TDS = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { useClientPicker } from "@/lib/workspace/useClientPicker";
import { formatPaise } from "@/lib/services/formatting";
import { useToast } from "@/components/ui/use-toast";
// The engine, reached through the API. Rates, thresholds, the
// individual-vs-company split, §206AA and the year's aggregate are all
// resolved server-side — CLAUDE.md: zero business logic in the frontend.
import {
  listTdsSections, previewTdsDeduction, createTdsDeduction,
} from "@/lib/data/tds";

// ─── TDS section labels ──────────────────────────────────────────────────────
//
// COSMETIC NAMES ONLY. No rates, no thresholds — those come from
// GET /api/tds/sections, which reads domain/tds/section_rates.py.
//
// What used to be here was a table of rates, and it was wrong in eight ways:
// s.194C flat at the company rate (an individual/HUF is 1%), s.194D at 5% when
// the statute says 2% individual and 10% company, s.194H at a rate the Finance
// (No. 2) Act 2024 cut, s.194Q charged on the whole sum where s.194Q(1) charges
// on the excess over Rs.50 lakh, s.194IA offered at all when the engine does
// not hold it, s.192 leaving the previous rate in the box, no threshold on
// anything, and no FY aggregate. The same shape as
// app/accounting/suppliers/page.tsx, which already does this correctly.
const SECTION_LABELS: Record<string, string> = {
  "192":   "Salary",
  "193":   "Interest on securities",
  "194":   "Dividends",
  "194A":  "Interest other than securities",
  "194B":  "Lottery / winnings",
  "194C":  "Contractor payments",
  "194D":  "Insurance commission",
  "194G":  "Commission on lottery tickets",
  "194H":  "Commission / brokerage",
  "194I":  "Rent",
  "194J":  "Professional / technical fees",
  "194K":  "Income from units",
  "194LA": "Compensation on immovable property",
  "194Q":  "Purchase of goods",
  "206C":  "TCS on sale of goods",
};

const QUARTERS = ["Q1 (Apr-Jun)", "Q2 (Jul-Sep)", "Q3 (Oct-Dec)", "Q4 (Jan-Mar)"];
const FY_LIST = ["2023-24", "2024-25", "2025-26", "2026-27"];

const STATUS_STYLE: Record<string, string> = {
  Pending:  "bg-amber-100 text-amber-700",
  Paid:     "bg-green-100 text-green-700",
  Overdue:  "bg-red-100 text-red-700",
  Filed:    "bg-green-100 text-green-700",
  Draft:    "bg-[#F1F5F9] text-[#475569]",
  Issued:   "bg-green-100 text-green-700",
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

interface TDSChallan {
  id: string;
  bsr_code: string;
  challan_date: string;
  challan_serial_no: string;
  amount_paise: number;
  period: string;
  section: string;
  fy: string;
}

interface TDSReturn {
  id: string;
  form_type: string;
  quarter: string;
  fy: string;
  due_date: string;
  filed_date: string | null;
  prn: string | null;
  status: "Pending" | "Filed" | "Overdue";
}

interface TDSCertificate {
  id: string;
  deductee_name: string;
  deductee_pan: string;
  period: string;
  amount_paise: number;
  issued_at: string | null;   // the column is issued_at, not issue_date
  status: "Pending" | "Issued";
}

const TABS = ["Deductions", "Challans", "Returns", "Certificates"];

// TDS returns (IT Act §200(3)) and certificates (Form 16/16A) are loaded from the
// firm's real data; empty until the firm records them (no fictional seed data).

// ─── Add Deduction Modal ─────────────────────────────────────────────────────

function AddDeductionModal({ clientId, onClose, onAdded }: {
  // No firmId. The server takes the firm from the caller's own token, which is
  // the point of routing this through the API — a firm_id the browser supplies
  // is a firm_id the browser could get wrong.
  //
  // tds_deductions.client_id is NOT NULL. This page used to insert null, so
  // every deduction ever entered on this form was rejected by the database.
  clientId: string;
  onClose: () => void;
  onAdded: (d: TDSDeduction) => void;
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
  // The section list, with its rates and thresholds, from the engine.
  const [sections, setSections] = useState<string[]>(Object.keys(SECTION_LABELS));
  // What the SERVER says this deduction comes to. There is no local answer to
  // fall back on — that was the bug.
  const [quote, setQuote] = useState<Awaited<ReturnType<typeof previewTdsDeduction>> | null>(null);
  const [quoting, setQuoting] = useState(false);
  const [quoteErr, setQuoteErr] = useState<string | null>(null);

  // The FY the PAYMENT falls in decides which year's rates apply and which
  // quarter the row belongs to, and the server derives both from the date.
  // There is no FY or Quarter control any more: letting a CA pick a quarter
  // that contradicts the payment date is how this column ended up with three
  // vocabularies, none of which the return preparer matched.
  useEffect(() => {
    let alive = true;
    listTdsSections()
      .then((r) => { if (alive && r.sections.length) setSections(r.sections.map((x) => x.section)); })
      .catch(() => { /* keep the label keys as the fallback list */ });
    return () => { alive = false; };
  }, []);

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
      const saved = await createTdsDeduction({
        client_id: clientId,
        deductee_name: partyName.trim(),
        deductee_pan: partyPan.trim().toUpperCase() || null,
        section,
        payment_amount_paise: grossPaise,
        transaction_date: paymentDate,
        challan_no: challanNo.trim() || null,
      });
      onAdded(saved as unknown as TDSDeduction);
      toast({ title: "TDS deduction recorded" });
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[#0F172A]">Add TDS Deduction</h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]"><X className="w-4 h-4" /></button>
        </div>
        {err && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{err}</p>}

        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="text-xs font-medium text-[#334155] block mb-1">Party / Vendor Name</label>
            <input className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={partyName} onChange={e => setPartyName(e.target.value)} placeholder="Vendor name" />
          </div>
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">PAN of Party</label>
            <input className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm font-mono uppercase focus:outline-none focus:ring-2 focus:ring-blue-500" value={partyPan} onChange={e => setPartyPan(e.target.value.toUpperCase())} placeholder="ABCDE1234F" maxLength={10} />
          </div>
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">TDS Section</label>
            <select className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={section} onChange={e => setSection(e.target.value)}>
              {sections.map(k => (
                <option key={k} value={k}>{k}{SECTION_LABELS[k] ? ` — ${SECTION_LABELS[k]}` : ""}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">Gross Payment (₹)</label>
            <input type="number" min="0" className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={grossRupees} onChange={e => setGrossRupees(e.target.value)} placeholder="0.00" />
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
              <p className="text-[11px] text-blue-800">
                Nothing is deducted — this payment is below §{section}&apos;s threshold, and
                the year&apos;s total for this payee has not reached it either.
              </p>
            )}
            {quote && quote.explain.fy_prior_tds_paise > 0 && (
              <p className="text-[11px] text-blue-800">
                Charged on the year&apos;s aggregate for this payee, crediting the{" "}
                {formatPaise(quote.explain.fy_prior_tds_paise)} already withheld (IT Act §200).
              </p>
            )}
            {quote && quote.quarter && (
              <p className="text-[10px] text-blue-700">
                Recorded in {quote.quarter}, derived from the payment date.
              </p>
            )}
            {quote?.explain.gap_messages.map((m) => (
              <p key={m} className="text-[11px] text-amber-700 bg-amber-50 rounded px-2 py-1">{m}</p>
            ))}
            {quoteErr && <p className="text-[11px] text-red-600">{quoteErr}</p>}
          </div>
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">Payment Date</label>
            <input type="date" className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={paymentDate} onChange={e => setPaymentDate(e.target.value)} />
          </div>
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">Challan No.</label>
            <input className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={challanNo} onChange={e => setChallanNo(e.target.value)} placeholder="Optional" />
          </div>
        </div>

        <div className="flex gap-2 pt-1">
          <button onClick={onClose} className="flex-1 border border-[#E2E8F0] text-[#475569] text-sm py-2 rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
          <button onClick={handleSubmit} disabled={saving} className="flex-1 bg-blue-600 text-white text-sm py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50">
            {saving ? "Saving…" : "Add Deduction"}
          </button>
        </div>
        <p className="text-[10px] text-amber-600 bg-amber-50 rounded px-2 py-1.5">
          {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
          Deposit TDS to the government account via e-Pay Tax on incometax.gov.in (challan ITNS 281). PracticeSync does not auto-submit.
        </p>
      </div>
    </div>
  );
}

// ─── Add Challan Modal ───────────────────────────────────────────────────────

function AddChallanModal({ onClose, onAdded }: {
  onClose: () => void;
  onAdded: (c: TDSChallan) => void;
}) {
  const [bsrCode, setBsrCode] = useState("");
  const [challanDate, setChallanDate] = useState("");
  const [serialNo, setSerialNo] = useState("");
  const [amtRupees, setAmtRupees] = useState("");
  const [period, setPeriod] = useState("Q1 (Apr-Jun)");
  const [section, setSection] = useState("194J");
  const [fy, setFy] = useState("2025-26");
  const [error, setError] = useState<string | null>(null);

  function handleAdd() {
    // Convert to paise — integer arithmetic, never float
    const amtPaise = paiseFromRupeeInput(amtRupees || "0");
    if (amtPaise === null) {
      setError("Amount must be in rupees, e.g. 125000 or 125000.50 — without commas.");
      return;
    }
    onAdded({
      id: Date.now().toString(),
      bsr_code: bsrCode,
      challan_date: challanDate,
      challan_serial_no: serialNo,
      amount_paise: amtPaise,
      period,
      section,
      fy,
    });
    onClose();
  }

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[#0F172A]">Add Challan 281</h3>
          <button onClick={onClose}><X className="w-4 h-4 text-[#94A3B8]" /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">BSR Code</label>
            <input className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500" value={bsrCode} onChange={e => setBsrCode(e.target.value)} placeholder="7-digit BSR code" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-[#334155] block mb-1">Challan Date</label>
              <input type="date" className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={challanDate} onChange={e => setChallanDate(e.target.value)} />
            </div>
            <div>
              <label className="text-xs font-medium text-[#334155] block mb-1">Serial No.</label>
              <input className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500" value={serialNo} onChange={e => setSerialNo(e.target.value)} placeholder="00001" />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">Amount (₹)</label>
            <input type="number" min="0" className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={amtRupees} onChange={e => { setAmtRupees(e.target.value); setError(null); }} />
          </div>
          {/* Without this the refusal above would be silent, which is worse
              than the coercion it replaced: the CA would press Add and nothing
              would happen. */}
          {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-[#334155] block mb-1">Period</label>
              <select className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={period} onChange={e => setPeriod(e.target.value)}>
                {QUARTERS.map(q => <option key={q}>{q}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-[#334155] block mb-1">FY</label>
              <select className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={fy} onChange={e => setFy(e.target.value)}>
                {FY_LIST.map(f => <option key={f}>{f}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">Section</label>
            <select className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={section} onChange={e => setSection(e.target.value)}>
              {Object.entries(SECTION_LABELS).map(([k, v]) => <option key={k} value={k}>{k} — {v}</option>)}
            </select>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 border border-[#E2E8F0] text-[#475569] text-sm py-2 rounded-lg">Cancel</button>
          <button onClick={handleAdd} className="flex-1 bg-blue-600 text-white text-sm py-2 rounded-lg hover:bg-blue-700">Add</button>
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
  const [firmId, setFirmId] = useState("");
  const [deductions, setDeductions] = useState<TDSDeduction[]>([]);
  const [challans, setChallans] = useState<TDSChallan[]>([]);
  const [returns, setReturns] = useState<TDSReturn[]>([]);
  const [certificates, setCertificates] = useState<TDSCertificate[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddDeduction, setShowAddDeduction] = useState(false);
  const [showAddChallan, setShowAddChallan] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [tableError, setTableError] = useState(false);
  // The real Postgres error message, distinct from tableError's narrower
  // "the tds_deductions table itself is missing" case — without this, a
  // failed firm-id lookup or tds_returns/tds_certificates query silently
  // left "Pending Returns"/"Pending Certificates" at their initial empty
  // state with no indication anything went wrong.
  const [loadErrorMessage, setLoadErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        let fid = "";
        try {
          fid = await getFirmId();
        } catch (e) {
          setLoadErrorMessage(e instanceof Error ? e.message : "Couldn't resolve your firm.");
        }
        setFirmId(fid);
        if (!fid) return;
        // client_id is required by the query below; an empty string would be
        // sent as `client_id=eq.` and rejected.
        if (!selectedClientId) { setDeductions([]); setLoading(false); return; }
        const sb = getSupabaseClient();
        const { data, error } = await sb
          .from("tds_deductions")
          .select("*")
          .eq("firm_id", fid)
          .eq("client_id", selectedClientId)
          .order("transaction_date", { ascending: false });
        if (error) {
          setTableError(true);
          setLoadErrorMessage(prev => prev ?? error.message);
        } else {
          setDeductions((data ?? []) as TDSDeduction[]);
        }
        // Returns + certificates from the firm's real data (best-effort; empty if
        // the tables are absent — never show fictional records).
        const [retRes, certRes] = await Promise.all([
          sb.from("tds_returns").select("*").eq("firm_id", fid).order("due_date", { ascending: false }),
          sb.from("tds_certificates").select("*").eq("firm_id", fid).order("issued_at", { ascending: false }),
        ]);
        if (retRes.error) {
          setTableError(true);
          setLoadErrorMessage(prev => prev ?? retRes.error!.message);
        } else {
          setReturns((retRes.data ?? []) as TDSReturn[]);
        }
        if (certRes.error) {
          setTableError(true);
          setLoadErrorMessage(prev => prev ?? certRes.error!.message);
        } else {
          setCertificates((certRes.data ?? []) as TDSCertificate[]);
        }
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [selectedClientId]);

  // Summary stats — all integer paise arithmetic
  const totalTDSPaise = deductions.reduce((s, d) => s + d.tds_paise, 0);
  const pendingChallans = challans.filter(c => !c.bsr_code).length;
  const pendingReturns = returns.filter(r => r.status !== "Filed").length;
  const pendingCerts = certificates.filter(c => c.status === "Pending").length;

  // ── Deductions DataTable columns — money in integer paise, aligned right ────
  const deductionColumns: Column<TDSDeduction>[] = useMemo(() => [
    {
      key: "party_name", header: "Party Name", accessor: (d) => d.deductee_name,
      searchable: true, sortable: true, sticky: true, hideable: false,
      render: (d) => <span className="font-medium text-[#0F172A]">{d.deductee_name}</span>,
    },
    {
      key: "party_pan", header: "PAN", accessor: (d) => d.deductee_pan ?? "", searchable: true,
      render: (d) => <span className="font-mono text-xs text-[#475569]">{d.deductee_pan || "—"}</span>,
    },
    {
      key: "section", header: "Section", accessor: (d) => d.section, sortable: true,
      render: (d) => (
        <>
          <span className="text-xs font-mono font-medium text-blue-700 bg-blue-50 px-1.5 py-0.5 rounded">{d.section}</span>
          <p className="text-[10px] text-[#94A3B8] mt-0.5">{SECTION_LABELS[d.section]}</p>
        </>
      ),
    },
    {
      key: "transaction_date", header: "Payment Date", accessor: (d) => d.transaction_date, sortable: true,
      render: (d) => <span className="text-xs text-[#475569]">{d.transaction_date ? new Date(d.transaction_date).toLocaleDateString("en-IN") : "—"}</span>,
    },
    {
      key: "gross_amount_paise", header: "Gross Amount", accessor: (d) => d.payment_amount_paise,
      sortable: true, align: "right", exportValue: (d) => d.payment_amount_paise / 100,
      render: (d) => <span className="text-[#0F172A]">{formatPaise(d.payment_amount_paise)}</span>,
    },
    {
      key: "tds_rate", header: "TDS Rate", accessor: (d) => d.tds_rate_pct, sortable: true, align: "right",
      render: (d) => <span className="text-xs text-[#475569]">{d.tds_rate_pct}%</span>,
    },
    {
      key: "tds_amount_paise", header: "TDS Amount", accessor: (d) => d.tds_paise,
      sortable: true, align: "right", exportValue: (d) => d.tds_paise / 100,
      render: (d) => <span className="font-medium text-[#0F172A]">{formatPaise(d.tds_paise)}</span>,
    },
    {
      key: "challan_no", header: "Challan No", accessor: (d) => d.challan_no ?? "",
      render: (d) => <span className="font-mono text-xs text-[#475569]">{d.challan_no || "—"}</span>,
    },
  ], []);

  const deductionFilters: FilterDef<TDSDeduction>[] = useMemo(() => [
    {
      key: "section", label: "Section", type: "select", accessor: (d) => d.section,
      options: Object.entries(SECTION_LABELS).map(([k, v]) => ({ value: k, label: `${k} — ${v}` })),
    },
    {
      key: "quarter", label: "Quarter", type: "select", accessor: (d) => d.quarter,
      options: QUARTERS.map((q) => ({ value: q, label: q })),
    },
  ], []);

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">TDS Module</h1>
          <p className="text-sm text-[#64748B] mt-0.5">Tax Deducted at Source — IT Act Chapter XVII-B</p>
        </div>
        {/* Deductions are per client, so the client is chosen before anything
            can be recorded or listed. */}
        <div className="min-w-[240px]">
          <label className="block text-xs font-medium text-[#475569] mb-1">Client *</label>
          <ClientLookup clients={clients} value={selectedClientId} onChange={setSelectedClientId} />
        </div>
      </div>

      {!selectedClientId && (
        <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 text-sm text-blue-800">
          Select a client to view and record their TDS deductions.
        </div>
      )}

      {tableError && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
          <p className="text-sm text-amber-700">
            {loadErrorMessage ?? (
              <>TDS deductions table not found. Run migration to create <code className="font-mono bg-amber-100 px-1 rounded">tds_deductions</code> table.</>
            )}
          </p>
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { icon: <IndianRupee className="w-4 h-4 text-blue-600" />, bg: "bg-blue-50", label: "Total TDS Deducted", value: loading ? "—" : formatPaise(totalTDSPaise), sub: "All time" },
          { icon: <FileText className="w-4 h-4 text-amber-600" />, bg: "bg-amber-50", label: "Pending Challans", value: String(pendingChallans), sub: "Undeposited" },
          { icon: <Calendar className="w-4 h-4 text-red-600" />, bg: "bg-red-50", label: "Returns Due", value: String(pendingReturns), sub: "24Q/26Q/27Q" },
          { icon: <Award className="w-4 h-4 text-purple-600" />, bg: "bg-purple-50", label: "Certificates Pending", value: String(pendingCerts), sub: "Form 16/16A" },
        ].map(c => (
          <div key={c.label} className="bg-white rounded-xl border border-[#F1F5F9] p-4">
            <div className="flex items-center gap-2 mb-3">
              <div className={`w-8 h-8 rounded-lg ${c.bg} flex items-center justify-center`}>{c.icon}</div>
              <span className="text-xs text-[#64748B]">{c.label}</span>
            </div>
            <p className="text-lg font-semibold text-[#0F172A]">{c.value}</p>
            <p className="text-xs text-[#94A3B8] mt-0.5">{c.sub}</p>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[#F1F5F9]">
        {TABS.map((tab, i) => (
          <button key={tab} onClick={() => setActiveTab(i)}
            className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === i ? "border-blue-600 text-blue-700" : "border-transparent text-[#64748B] hover:text-[#334155]"}`}>
            {tab}
          </button>
        ))}
      </div>

      {/* Tab: Deductions — shared DataTable (search, filters, sort, pagination, export, prefs) */}
      {activeTab === 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-[#0F172A]">TDS Deductions</h2>
              <p className="text-xs text-[#94A3B8] mt-0.5">IT Act Section 194 — deductions recorded</p>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={() => setShowImport(true)}
                className="flex items-center gap-1.5 border border-[#E2E8F0] text-[#475569] text-xs px-3 py-1.5 rounded-lg hover:bg-[#F8FAFC]">
                <Upload className="w-3.5 h-3.5" /> Import CSV
              </button>
              <button onClick={() => setShowAddDeduction(true)}
                className="flex items-center gap-1.5 bg-blue-600 text-white text-xs px-3 py-1.5 rounded-lg hover:bg-blue-700">
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
            searchPlaceholder="Search by party name or PAN…"
            initialSort={{ key: "transaction_date", dir: "desc" }}
            exportFilename="tds-deductions"
            persistKey="tds.deductions"
            emptyTitle="No deductions recorded yet"
            emptyDescription={'Click "Add Deduction" to start.'}
          />

          {deductions.length > 0 && (
            <div className="flex flex-wrap justify-end gap-x-6 gap-y-1 px-1 text-xs text-[#64748B]">
              <span>Total Gross: <span className="font-semibold text-[#0F172A]">{formatPaise(deductions.reduce((s, d) => s + d.payment_amount_paise, 0))}</span></span>
              <span>Total TDS: <span className="font-semibold text-[#0F172A]">{formatPaise(totalTDSPaise)}</span></span>
            </div>
          )}
        </div>
      )}

      {/* Tab: Challans */}
      {activeTab === 1 && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-[#0F172A]">Challan 281 Tracker</h2>
              <p className="text-xs text-[#94A3B8] mt-0.5">IT Act Section 200(1) — TDS deposit challans</p>
            </div>
            <button onClick={() => setShowAddChallan(true)}
              className="flex items-center gap-1.5 bg-blue-600 text-white text-xs px-3 py-1.5 rounded-lg hover:bg-blue-700">
              <Plus className="w-3.5 h-3.5" /> Add Challan
            </button>
          </div>
          {challans.length === 0 ? (
            <div className="px-5 py-10 text-center text-sm text-[#94A3B8]">No challans added yet. Click &ldquo;Add Challan&rdquo; to record a deposit.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-50">
                    {["BSR Code", "Challan Date", "Serial No.", "Amount", "Period", "FY", "Section"].map(h => (
                      <th key={h} className="text-left text-xs font-medium text-[#94A3B8] px-4 py-3">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F8FAFC]">
                  {challans.map(c => (
                    <tr key={c.id} className="hover:bg-[#F8FAFC]/50">
                      <td className="px-4 py-3 text-xs font-mono text-[#0F172A]">{c.bsr_code || "—"}</td>
                      <td className="px-4 py-3 text-xs text-[#475569]">{c.challan_date ? new Date(c.challan_date).toLocaleDateString("en-IN") : "—"}</td>
                      <td className="px-4 py-3 text-xs font-mono text-[#475569]">{c.challan_serial_no || "—"}</td>
                      <td className="px-4 py-3 text-sm font-medium text-[#0F172A]">{formatPaise(c.amount_paise)}</td>
                      <td className="px-4 py-3 text-xs text-[#475569]">{c.period}</td>
                      <td className="px-4 py-3 text-xs text-[#475569]">{c.fy}</td>
                      <td className="px-4 py-3 text-xs font-mono text-blue-700">{c.section}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Tab: Returns */}
      {activeTab === 2 && (
        <div className="space-y-4">
          <div className="bg-amber-50 border border-amber-100 rounded-lg px-4 py-3 flex gap-2">
            {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
            <AlertCircle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
            <p className="text-sm text-amber-700">File 24Q/26Q returns manually on the Income Tax e-filing portal (incometax.gov.in), under the deductor&apos;s TAN login. TRACES is post-filing only (Form 16/16A, defaults, corrections). PracticeSync does not auto-submit to any government portal.</p>
          </div>
          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50 flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-[#0F172A]">TDS Returns (24Q / 26Q / 27Q)</h2>
                <p className="text-xs text-[#94A3B8] mt-0.5">IT Act Section 200(3) — quarterly TDS return filing status</p>
              </div>
              <Link
                href="/tds/returns"
                className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-2 rounded-lg hover:bg-blue-700 shrink-0"
              >
                Prepare a Return <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </div>
            <div className="px-5 py-4 grid grid-cols-3 gap-4 text-center">
              {(["Pending", "Filed", "Overdue"] as const).map(s => (
                <div key={s}>
                  <p className="text-2xl font-semibold text-[#0F172A]">{returns.filter(r => r.status === s).length}</p>
                  <p className="text-xs text-[#64748B] mt-0.5">{s}</p>
                </div>
              ))}
            </div>
            <p className="px-5 pb-4 text-xs text-[#94A3B8]">
              Generate, review, and mark a specific quarter&apos;s return as filed in{" "}
              <Link href="/tds/returns" className="text-blue-600 hover:underline">Prepare a Return</Link>.
            </p>
          </div>
        </div>
      )}

      {/* Tab: Certificates */}
      {activeTab === 3 && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50">
            <h2 className="text-sm font-semibold text-[#0F172A]">Form 16A Certificates</h2>
            <p className="text-xs text-[#94A3B8] mt-0.5">TDS certificates issued to deductees — IT Act Section 203</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-50">
                  {["Deductee Name", "PAN", "Period", "TDS Amount", "Issue Date", "Status"].map(h => (
                    <th key={h} className="text-left text-xs font-medium text-[#94A3B8] px-4 py-3">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {certificates.map(c => (
                  <tr key={c.id} className="hover:bg-[#F8FAFC]/50">
                    <td className="px-4 py-3 text-sm font-medium text-[#0F172A]">{c.deductee_name}</td>
                    <td className="px-4 py-3 text-xs font-mono text-[#475569]">{c.deductee_pan}</td>
                    <td className="px-4 py-3 text-xs text-[#475569]">{c.period}</td>
                    <td className="px-4 py-3 text-sm font-medium text-[#0F172A]">{formatPaise(c.amount_paise)}</td>
                    <td className="px-4 py-3 text-xs text-[#475569]">{c.issued_at ? new Date(c.issued_at).toLocaleDateString("en-IN") : "—"}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_STYLE[c.status]}`}>{c.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {showAddDeduction && firmId && (
        <AddDeductionModal clientId={selectedClientId} onClose={() => setShowAddDeduction(false)} onAdded={d => setDeductions(prev => [d, ...prev])} />
      )}
      {showAddChallan && (
        <AddChallanModal onClose={() => setShowAddChallan(false)} onAdded={c => setChallans(prev => [c, ...prev])} />
      )}

      {showImport && firmId && (
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
              const sb2 = getSupabaseClient();
              const { data } = await sb2.from("tds_deductions").select("*").eq("firm_id", firmId).eq("client_id", selectedClientId).order("transaction_date", { ascending: false });
              if (data) setDeductions(data as TDSDeduction[]);
            }
            return { imported, errors };
          }}
          validateRow={(row) => {
            const errs: string[] = [];
            if (!PAN_RE_TDS.test(row.party_pan?.toUpperCase() ?? "")) errs.push("Invalid PAN format");
            if (row.payment_date && !/^\d{4}-\d{2}-\d{2}$/.test(row.payment_date)) errs.push("payment_date must be YYYY-MM-DD");
            if (row.gross_amount_rs && isNaN(parseFloat(row.gross_amount_rs))) errs.push("gross_amount_rs must be a number");
            return errs;
          }}
        />
      )}
    </div>
  );
}
