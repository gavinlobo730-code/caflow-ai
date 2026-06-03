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

import { useState, useEffect } from "react";
import {
  IndianRupee, Calendar, AlertCircle, Plus, X, FileText, Award, Upload,
} from "lucide-react";
import CsvImportModal, { type ImportRow } from "@/components/CsvImportModal";

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
import { formatPaise } from "@/lib/services/formatting";
import { useToast } from "@/components/ui/use-toast";

// ─── TDS Section Rates — IT Act Chapter XVII-B ───────────────────────────────
const TDS_SECTIONS: Record<string, { label: string; rate: number; rateLabel: string }> = {
  "192":  { label: "Salary",                      rate: 0,    rateLabel: "As per slab" },
  "194A": { label: "Interest",                    rate: 10,   rateLabel: "10%" },
  "194C": { label: "Contractor Payments",         rate: 2,    rateLabel: "1%/2%" },
  "194D": { label: "Insurance Commission",        rate: 5,    rateLabel: "5%" },
  "194H": { label: "Commission/Brokerage",        rate: 5,    rateLabel: "5%" },
  "194I": { label: "Rent",                        rate: 10,   rateLabel: "10%" },
  "194J": { label: "Professional/Technical Fees", rate: 10,   rateLabel: "10%" },
  "194Q": { label: "Purchase of Goods",           rate: 0.1,  rateLabel: "0.1%" },
};

const QUARTERS = ["Q1 (Apr-Jun)", "Q2 (Jul-Sep)", "Q3 (Oct-Dec)", "Q4 (Jan-Mar)"];
const FY_LIST = ["2023-24", "2024-25", "2025-26", "2026-27"];

const STATUS_STYLE: Record<string, string> = {
  Pending:  "bg-amber-100 text-amber-700",
  Paid:     "bg-green-100 text-green-700",
  Overdue:  "bg-red-100 text-red-700",
  Filed:    "bg-green-100 text-green-700",
  Draft:    "bg-gray-100 text-gray-600",
  Issued:   "bg-green-100 text-green-700",
};

// ─── Types ───────────────────────────────────────────────────────────────────

interface TDSDeduction {
  id: string;
  firm_id: string;
  client_id: string | null;
  party_name: string;
  party_pan: string;
  section: string;
  gross_amount_paise: number;
  tds_rate: number;
  tds_amount_paise: number;
  payment_date: string;
  challan_no: string | null;
  fy: string;
  quarter: string;
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
  issue_date: string | null;
  status: "Pending" | "Issued";
}

const TABS = ["Deductions", "Challans", "Returns", "Certificates"];

// Seed data for Returns (IT Act Section 200(3) — 31st of month following quarter end)
const SEED_RETURNS: TDSReturn[] = [
  { id: "r1", form_type: "26Q", quarter: "Q1", fy: "2025-26", due_date: "2025-07-31", filed_date: "2025-07-28", prn: "PRN1234567", status: "Filed" },
  { id: "r2", form_type: "26Q", quarter: "Q2", fy: "2025-26", due_date: "2025-10-31", filed_date: "2025-10-25", prn: "PRN1234568", status: "Filed" },
  { id: "r3", form_type: "26Q", quarter: "Q3", fy: "2025-26", due_date: "2026-01-31", filed_date: "2026-01-28", prn: "PRN1234569", status: "Filed" },
  { id: "r4", form_type: "26Q", quarter: "Q4", fy: "2025-26", due_date: "2026-05-31", filed_date: null, prn: null, status: "Overdue" },
  { id: "r5", form_type: "26Q", quarter: "Q1", fy: "2026-27", due_date: "2026-07-31", filed_date: null, prn: null, status: "Pending" },
  { id: "r6", form_type: "24Q", quarter: "Q4", fy: "2025-26", due_date: "2026-05-31", filed_date: null, prn: null, status: "Overdue" },
];

const SEED_CERTS: TDSCertificate[] = [
  { id: "c1", deductee_name: "Ravi Kumar", deductee_pan: "BNPKR1234M", period: "Q3 FY 2025-26", amount_paise: 2500000, issue_date: "2026-01-30", status: "Issued" },
  { id: "c2", deductee_name: "Sunita Enterprises", deductee_pan: "AABCS5678P", period: "Q4 FY 2025-26", amount_paise: 1800000, issue_date: null, status: "Pending" },
];

// ─── Add Deduction Modal ─────────────────────────────────────────────────────

function AddDeductionModal({ firmId, onClose, onAdded }: {
  firmId: string;
  onClose: () => void;
  onAdded: (d: TDSDeduction) => void;
}) {
  const { toast } = useToast();
  const [partyName, setPartyName] = useState("");
  const [partyPan, setPartyPan] = useState("");
  const [section, setSection] = useState("194J");
  const [grossRupees, setGrossRupees] = useState("");
  const [tdsRate, setTdsRate] = useState(10);
  const [paymentDate, setPaymentDate] = useState("");
  const [challanNo, setChallanNo] = useState("");
  const [fy, setFy] = useState("2025-26");
  const [quarter, setQuarter] = useState("Q1 (Apr-Jun)");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Auto-populate TDS rate based on section — IT Act rates
  useEffect(() => {
    const s = TDS_SECTIONS[section];
    if (s && s.rate > 0) setTdsRate(s.rate);
  }, [section]);

  // All monetary calculations in integer paise — never float
  const grossPaise = grossRupees ? Math.round(parseFloat(grossRupees) * 100) : 0;
  // TDS = grossPaise * rate / 100, integer arithmetic
  const tdsPaise = Math.round((grossPaise * tdsRate) / 100);

  async function handleSubmit() {
    if (!partyName.trim() || !paymentDate) {
      setErr("Party name and payment date are required.");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      const sb = getSupabaseClient();
      // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
      const { data, error } = await sb.from("tds_deductions").insert({
        firm_id: firmId,
        client_id: null,
        party_name: partyName.trim(),
        party_pan: partyPan.trim().toUpperCase(),
        section,
        gross_amount_paise: grossPaise,
        tds_rate: tdsRate,
        tds_amount_paise: tdsPaise,
        payment_date: paymentDate,
        challan_no: challanNo.trim() || null,
        fy,
        quarter,
      }).select().single();
      if (error) throw new Error(error.message);
      onAdded(data as TDSDeduction);
      toast({ title: "TDS deduction recorded" });
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900">Add TDS Deduction</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-4 h-4" /></button>
        </div>
        {err && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{err}</p>}

        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="text-xs font-medium text-gray-700 block mb-1">Party / Vendor Name</label>
            <input className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={partyName} onChange={e => setPartyName(e.target.value)} placeholder="Vendor name" />
          </div>
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">PAN of Party</label>
            <input className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono uppercase focus:outline-none focus:ring-2 focus:ring-blue-500" value={partyPan} onChange={e => setPartyPan(e.target.value.toUpperCase())} placeholder="ABCDE1234F" maxLength={10} />
          </div>
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">TDS Section</label>
            <select className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={section} onChange={e => setSection(e.target.value)}>
              {Object.entries(TDS_SECTIONS).map(([k, v]) => (
                <option key={k} value={k}>{k} — {v.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Gross Payment (₹)</label>
            <input type="number" min="0" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={grossRupees} onChange={e => setGrossRupees(e.target.value)} placeholder="0.00" />
          </div>
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">TDS Rate (%)</label>
            <input type="number" min="0" step="0.1" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={tdsRate} onChange={e => setTdsRate(parseFloat(e.target.value) || 0)} />
          </div>
          <div className="col-span-2 bg-blue-50 rounded-lg px-3 py-2 flex justify-between items-center">
            <span className="text-xs text-blue-700 font-medium">TDS Amount (auto-calculated)</span>
            <span className="text-sm font-semibold text-blue-900">{formatPaise(tdsPaise)}</span>
          </div>
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Payment Date</label>
            <input type="date" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={paymentDate} onChange={e => setPaymentDate(e.target.value)} />
          </div>
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Challan No.</label>
            <input className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={challanNo} onChange={e => setChallanNo(e.target.value)} placeholder="Optional" />
          </div>
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Financial Year</label>
            <select className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={fy} onChange={e => setFy(e.target.value)}>
              {FY_LIST.map(f => <option key={f} value={f}>{f}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Quarter</label>
            <select className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={quarter} onChange={e => setQuarter(e.target.value)}>
              {QUARTERS.map(q => <option key={q} value={q}>{q}</option>)}
            </select>
          </div>
        </div>

        <div className="flex gap-2 pt-1">
          <button onClick={onClose} className="flex-1 border border-gray-200 text-gray-600 text-sm py-2 rounded-lg hover:bg-gray-50">Cancel</button>
          <button onClick={handleSubmit} disabled={saving} className="flex-1 bg-blue-600 text-white text-sm py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50">
            {saving ? "Saving…" : "Add Deduction"}
          </button>
        </div>
        <p className="text-[10px] text-amber-600 bg-amber-50 rounded px-2 py-1.5">
          {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
          Deposit TDS to government account via TRACES portal. CAflow does not auto-submit.
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

  function handleAdd() {
    // Convert to paise — integer arithmetic, never float
    const amtPaise = Math.round(parseFloat(amtRupees || "0") * 100);
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
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900">Add Challan 281</h3>
          <button onClick={onClose}><X className="w-4 h-4 text-gray-400" /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">BSR Code</label>
            <input className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500" value={bsrCode} onChange={e => setBsrCode(e.target.value)} placeholder="7-digit BSR code" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-gray-700 block mb-1">Challan Date</label>
              <input type="date" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={challanDate} onChange={e => setChallanDate(e.target.value)} />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-700 block mb-1">Serial No.</label>
              <input className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500" value={serialNo} onChange={e => setSerialNo(e.target.value)} placeholder="00001" />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Amount (₹)</label>
            <input type="number" min="0" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={amtRupees} onChange={e => setAmtRupees(e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-gray-700 block mb-1">Period</label>
              <select className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={period} onChange={e => setPeriod(e.target.value)}>
                {QUARTERS.map(q => <option key={q}>{q}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-700 block mb-1">FY</label>
              <select className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={fy} onChange={e => setFy(e.target.value)}>
                {FY_LIST.map(f => <option key={f}>{f}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Section</label>
            <select className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={section} onChange={e => setSection(e.target.value)}>
              {Object.entries(TDS_SECTIONS).map(([k, v]) => <option key={k} value={k}>{k} — {v.label}</option>)}
            </select>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 border border-gray-200 text-gray-600 text-sm py-2 rounded-lg">Cancel</button>
          <button onClick={handleAdd} className="flex-1 bg-blue-600 text-white text-sm py-2 rounded-lg hover:bg-blue-700">Add</button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function TDSPage() {
  const [activeTab, setActiveTab] = useState(0);
  const [firmId, setFirmId] = useState("");
  const [deductions, setDeductions] = useState<TDSDeduction[]>([]);
  const [challans, setChallans] = useState<TDSChallan[]>([]);
  const [returns] = useState<TDSReturn[]>(SEED_RETURNS);
  const [certificates] = useState<TDSCertificate[]>(SEED_CERTS);
  const [loading, setLoading] = useState(true);
  const [showAddDeduction, setShowAddDeduction] = useState(false);
  const [showAddChallan, setShowAddChallan] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [tableError, setTableError] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const fid = await getFirmId().catch(() => "");
        setFirmId(fid);
        if (!fid) return;
        const sb = getSupabaseClient();
        const { data, error } = await sb
          .from("tds_deductions")
          .select("*")
          .eq("firm_id", fid)
          .order("payment_date", { ascending: false });
        if (error) {
          setTableError(true);
        } else {
          setDeductions((data ?? []) as TDSDeduction[]);
        }
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  // Summary stats — all integer paise arithmetic
  const totalTDSPaise = deductions.reduce((s, d) => s + d.tds_amount_paise, 0);
  const pendingChallans = challans.filter(c => !c.bsr_code).length;
  const pendingReturns = returns.filter(r => r.status !== "Filed").length;
  const pendingCerts = certificates.filter(c => c.status === "Pending").length;

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">TDS Module</h1>
        <p className="text-sm text-gray-500 mt-0.5">Tax Deducted at Source — IT Act Chapter XVII-B</p>
      </div>

      {tableError && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 flex gap-2">
          <AlertCircle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
          <p className="text-sm text-amber-700">
            TDS deductions table not found. Run migration to create <code className="font-mono bg-amber-100 px-1 rounded">tds_deductions</code> table.
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
          <div key={c.label} className="bg-white rounded-xl border border-gray-100 p-4">
            <div className="flex items-center gap-2 mb-3">
              <div className={`w-8 h-8 rounded-lg ${c.bg} flex items-center justify-center`}>{c.icon}</div>
              <span className="text-xs text-gray-500">{c.label}</span>
            </div>
            <p className="text-lg font-semibold text-gray-900">{c.value}</p>
            <p className="text-xs text-gray-400 mt-0.5">{c.sub}</p>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-100">
        {TABS.map((tab, i) => (
          <button key={tab} onClick={() => setActiveTab(i)}
            className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === i ? "border-blue-600 text-blue-700" : "border-transparent text-gray-500 hover:text-gray-700"}`}>
            {tab}
          </button>
        ))}
      </div>

      {/* Tab: Deductions */}
      {activeTab === 0 && (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-gray-900">TDS Deductions</h2>
              <p className="text-xs text-gray-400 mt-0.5">IT Act Section 194 — deductions recorded</p>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={() => setShowImport(true)}
                className="flex items-center gap-1.5 border border-gray-200 text-gray-600 text-xs px-3 py-1.5 rounded-lg hover:bg-gray-50">
                <Upload className="w-3.5 h-3.5" /> Import CSV
              </button>
              <button onClick={() => setShowAddDeduction(true)}
                className="flex items-center gap-1.5 bg-blue-600 text-white text-xs px-3 py-1.5 rounded-lg hover:bg-blue-700">
                <Plus className="w-3.5 h-3.5" /> Add Deduction
              </button>
            </div>
          </div>
          {loading ? <div className="px-5 py-10 text-center text-sm text-gray-400">Loading…</div>
            : deductions.length === 0 ? (
              <div className="px-5 py-10 text-center text-sm text-gray-400">No deductions recorded yet. Click &ldquo;Add Deduction&rdquo; to start.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-50">
                      {["Party Name", "PAN", "Section", "Payment Date", "Gross Amount", "TDS Rate", "TDS Amount", "Challan No"].map(h => (
                        <th key={h} className="text-left text-xs font-medium text-gray-400 px-4 py-3">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {deductions.map(d => (
                      <tr key={d.id} className="hover:bg-gray-50/50">
                        <td className="px-4 py-3 text-sm font-medium text-gray-900">{d.party_name}</td>
                        <td className="px-4 py-3 text-xs font-mono text-gray-600">{d.party_pan || "—"}</td>
                        <td className="px-4 py-3">
                          <span className="text-xs font-mono font-medium text-blue-700 bg-blue-50 px-1.5 py-0.5 rounded">{d.section}</span>
                          <p className="text-[10px] text-gray-400 mt-0.5">{TDS_SECTIONS[d.section]?.label}</p>
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-600">{new Date(d.payment_date).toLocaleDateString("en-IN")}</td>
                        <td className="px-4 py-3 text-sm text-right text-gray-900">{formatPaise(d.gross_amount_paise)}</td>
                        <td className="px-4 py-3 text-xs text-right text-gray-600">{d.tds_rate}%</td>
                        <td className="px-4 py-3 text-sm text-right font-medium text-gray-900">{formatPaise(d.tds_amount_paise)}</td>
                        <td className="px-4 py-3 text-xs font-mono text-gray-600">{d.challan_no || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="border-t border-gray-100 bg-gray-50/50">
                      <td colSpan={4} className="px-4 py-3 text-xs font-medium text-gray-500">Total</td>
                      <td className="px-4 py-3 text-right text-sm font-semibold">{formatPaise(deductions.reduce((s, d) => s + d.gross_amount_paise, 0))}</td>
                      <td></td>
                      <td className="px-4 py-3 text-right text-sm font-semibold">{formatPaise(totalTDSPaise)}</td>
                      <td></td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}
        </div>
      )}

      {/* Tab: Challans */}
      {activeTab === 1 && (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-gray-900">Challan 281 Tracker</h2>
              <p className="text-xs text-gray-400 mt-0.5">IT Act Section 200(1) — TDS deposit challans</p>
            </div>
            <button onClick={() => setShowAddChallan(true)}
              className="flex items-center gap-1.5 bg-blue-600 text-white text-xs px-3 py-1.5 rounded-lg hover:bg-blue-700">
              <Plus className="w-3.5 h-3.5" /> Add Challan
            </button>
          </div>
          {challans.length === 0 ? (
            <div className="px-5 py-10 text-center text-sm text-gray-400">No challans added yet. Click &ldquo;Add Challan&rdquo; to record a deposit.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-50">
                    {["BSR Code", "Challan Date", "Serial No.", "Amount", "Period", "FY", "Section"].map(h => (
                      <th key={h} className="text-left text-xs font-medium text-gray-400 px-4 py-3">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {challans.map(c => (
                    <tr key={c.id} className="hover:bg-gray-50/50">
                      <td className="px-4 py-3 text-xs font-mono text-gray-900">{c.bsr_code || "—"}</td>
                      <td className="px-4 py-3 text-xs text-gray-600">{c.challan_date ? new Date(c.challan_date).toLocaleDateString("en-IN") : "—"}</td>
                      <td className="px-4 py-3 text-xs font-mono text-gray-600">{c.challan_serial_no || "—"}</td>
                      <td className="px-4 py-3 text-sm font-medium text-gray-900">{formatPaise(c.amount_paise)}</td>
                      <td className="px-4 py-3 text-xs text-gray-600">{c.period}</td>
                      <td className="px-4 py-3 text-xs text-gray-600">{c.fy}</td>
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
            <p className="text-sm text-amber-700">File 24Q/26Q returns manually on TRACES portal (traces.gov.in). CAflow does not auto-submit to any government portal.</p>
          </div>
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50">
              <h2 className="text-sm font-semibold text-gray-900">TDS Returns (24Q / 26Q / 27Q)</h2>
              <p className="text-xs text-gray-400 mt-0.5">IT Act Section 200(3) — quarterly TDS return filing status</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-50">
                    {["Form Type", "Quarter", "FY", "Due Date", "Filed Date", "PRN / Acknowledgement", "Status"].map(h => (
                      <th key={h} className="text-left text-xs font-medium text-gray-400 px-4 py-3">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {returns.map(r => (
                    <tr key={r.id} className="hover:bg-gray-50/50">
                      <td className="px-4 py-3 text-xs font-mono font-medium text-blue-700">{r.form_type}</td>
                      <td className="px-4 py-3 text-sm font-medium text-gray-900">{r.quarter}</td>
                      <td className="px-4 py-3 text-xs text-gray-600">{r.fy}</td>
                      <td className="px-4 py-3 text-xs text-gray-600">{new Date(r.due_date).toLocaleDateString("en-IN")}</td>
                      <td className="px-4 py-3 text-xs text-gray-600">{r.filed_date ? new Date(r.filed_date).toLocaleDateString("en-IN") : "—"}</td>
                      <td className="px-4 py-3 text-xs font-mono text-gray-600">{r.prn || "—"}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_STYLE[r.status] ?? "bg-gray-100 text-gray-600"}`}>{r.status}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Tab: Certificates */}
      {activeTab === 3 && (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50">
            <h2 className="text-sm font-semibold text-gray-900">Form 16A Certificates</h2>
            <p className="text-xs text-gray-400 mt-0.5">TDS certificates issued to deductees — IT Act Section 203</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-50">
                  {["Deductee Name", "PAN", "Period", "TDS Amount", "Issue Date", "Status"].map(h => (
                    <th key={h} className="text-left text-xs font-medium text-gray-400 px-4 py-3">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {certificates.map(c => (
                  <tr key={c.id} className="hover:bg-gray-50/50">
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">{c.deductee_name}</td>
                    <td className="px-4 py-3 text-xs font-mono text-gray-600">{c.deductee_pan}</td>
                    <td className="px-4 py-3 text-xs text-gray-600">{c.period}</td>
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">{formatPaise(c.amount_paise)}</td>
                    <td className="px-4 py-3 text-xs text-gray-600">{c.issue_date ? new Date(c.issue_date).toLocaleDateString("en-IN") : "—"}</td>
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
        <AddDeductionModal firmId={firmId} onClose={() => setShowAddDeduction(false)} onAdded={d => setDeductions(prev => [d, ...prev])} />
      )}
      {showAddChallan && (
        <AddChallanModal onClose={() => setShowAddChallan(false)} onAdded={c => setChallans(prev => [c, ...prev])} />
      )}

      {showImport && firmId && (
        <CsvImportModal
          title="Import TDS Deductions from CSV"
          columns={TDS_IMPORT_COLUMNS}
          templateFilename="caflow-tds-template.xlsx"
          onClose={() => setShowImport(false)}
          onImport={async (rows: ImportRow[]) => {
            const sb = getSupabaseClient();
            let imported = 0;
            const errors: string[] = [];
            for (const row of rows) {
              const grossPaise = Math.round(parseFloat(row.gross_amount_rs ?? "0") * 100);
              const rate = parseFloat(row.tds_rate ?? "0");
              const tdsPaise = Math.round(grossPaise * rate / 100);
              const { error } = await sb.from("tds_deductions").insert({
                firm_id: firmId,
                client_id: null,
                party_name: row.party_name,
                party_pan: row.party_pan.toUpperCase(),
                section: row.section,
                gross_amount_paise: grossPaise,
                tds_rate: rate,
                tds_amount_paise: tdsPaise,
                payment_date: row.payment_date,
                challan_no: row.challan_no || null,
                fy: row.fy,
                quarter: row.quarter,
              });
              if (error) errors.push(`${row.party_name}: ${error.message}`);
              else imported++;
            }
            if (imported > 0) {
              const sb2 = getSupabaseClient();
              const { data } = await sb2.from("tds_deductions").select("*").eq("firm_id", firmId).order("payment_date", { ascending: false });
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
