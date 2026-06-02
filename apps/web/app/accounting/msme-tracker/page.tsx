"use client";

/**
 * MSME 43B(h) Tracker
 * IT Act Section 43B(h) — effective FY 2024-25
 * Payments to MSME vendors must be made within 45 days (15 days for verbal agreement).
 * Non-payment by due date triggers disallowance of the expense in the year of accrual.
 *
 * Reference: Finance Act 2023 — insertion of clause (h) in Section 43B of IT Act.
 * MSME registration governed by MSMED Act 2006.
 *
 * All monetary amounts stored in paise (integer arithmetic).
 */

import { useState, useEffect } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Plus,
  X,
  AlertCircle,
  CheckCircle,
  Clock,
  AlertTriangle,
  IndianRupee,
} from "lucide-react";
import { formatPaise } from "@/lib/services/formatting";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MSMEVendor {
  id: string;
  name: string;
  gstin: string;
  msmeRegNo: string;
  paymentTermsDays: 15 | 45; // 15 = verbal agreement; 45 = written agreement
}

interface MSMEInvoice {
  id: string;
  vendorId: string;
  invoiceDate: string; // ISO date string
  amountPaise: number;
  paid: boolean;
  paidDate?: string; // ISO date string
}

type TrafficLight = "green" | "yellow" | "red";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Compute due date for MSME payment. IT Act Section 43B(h). */
function computeDueDate(invoiceDate: string, termsDays: 15 | 45): string {
  const d = new Date(invoiceDate);
  d.setDate(d.getDate() + termsDays);
  return d.toISOString().slice(0, 10);
}

/** Days between two ISO date strings (positive = overdue) */
function daysDiff(dueDateISO: string, todayISO: string): number {
  const due = new Date(dueDateISO).getTime();
  const today = new Date(todayISO).getTime();
  return Math.floor((today - due) / (24 * 60 * 60 * 1000));
}

function getTrafficLight(
  paid: boolean,
  dueDate: string,
  todayISO: string
): TrafficLight {
  if (paid) return "green";
  const days = daysDiff(dueDate, todayISO);
  if (days > 0) return "red";
  if (days >= -7) return "yellow";
  return "green";
}

const TRAFFIC_STYLE: Record<TrafficLight, string> = {
  green: "bg-green-100 text-green-700",
  yellow: "bg-amber-100 text-amber-700",
  red: "bg-red-100 text-red-700",
};

const TRAFFIC_ICON: Record<TrafficLight, React.ReactNode> = {
  green: <CheckCircle className="w-3.5 h-3.5 text-green-600" />,
  yellow: <Clock className="w-3.5 h-3.5 text-amber-600" />,
  red: <AlertTriangle className="w-3.5 h-3.5 text-red-600" />,
};

const TRAFFIC_LABEL: Record<TrafficLight, string> = {
  green: "On Track",
  yellow: "Due Soon",
  red: "Overdue — Disallowance Risk",
};

/** Validate GSTIN format — 2-digit state + PAN (10) + 1 entity + Z + 1 check */
function isValidGSTIN(gstin: string): boolean {
  if (!gstin) return true; // optional
  return /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9Z][Z][0-9A-Z]$/.test(gstin);
}

const TODAY_ISO = "2026-06-02";
const STORAGE_KEY_VENDORS = "caflow_msme_vendors";
const STORAGE_KEY_INVOICES = "caflow_msme_invoices";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function MSMETrackerPage() {
  const [vendors, setVendors] = useState<MSMEVendor[]>([]);
  const [invoices, setInvoices] = useState<MSMEInvoice[]>([]);

  // Modals
  const [showAddVendor, setShowAddVendor] = useState(false);
  const [showAddInvoice, setShowAddInvoice] = useState(false);

  // Vendor form
  const [vName, setVName] = useState("");
  const [vGstin, setVGstin] = useState("");
  const [vMsmeReg, setVMsmeReg] = useState("");
  const [vTerms, setVTerms] = useState<15 | 45>(45);
  const [vError, setVError] = useState<string | null>(null);

  // Invoice form
  const [iVendorId, setIVendorId] = useState("");
  const [iDate, setIDate] = useState(TODAY_ISO);
  const [iAmount, setIAmount] = useState("");
  const [iError, setIError] = useState<string | null>(null);

  // Load from localStorage
  useEffect(() => {
    try {
      const sv = localStorage.getItem(STORAGE_KEY_VENDORS);
      const si = localStorage.getItem(STORAGE_KEY_INVOICES);
      if (sv) setVendors(JSON.parse(sv));
      if (si) setInvoices(JSON.parse(si));
    } catch {}
  }, []);

  // Persist to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY_VENDORS, JSON.stringify(vendors));
    } catch {}
  }, [vendors]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY_INVOICES, JSON.stringify(invoices));
    } catch {}
  }, [invoices]);

  function resetVendorForm() {
    setVName("");
    setVGstin("");
    setVMsmeReg("");
    setVTerms(45);
    setVError(null);
  }

  function resetInvoiceForm() {
    setIVendorId("");
    setIDate(TODAY_ISO);
    setIAmount("");
    setIError(null);
  }

  function handleAddVendor() {
    if (!vName.trim()) {
      setVError("Vendor name is required");
      return;
    }
    if (vGstin && !isValidGSTIN(vGstin.toUpperCase())) {
      setVError("Invalid GSTIN format");
      return;
    }
    const vendor: MSMEVendor = {
      id: Date.now().toString(),
      name: vName.trim(),
      gstin: vGstin.trim().toUpperCase(),
      msmeRegNo: vMsmeReg.trim(),
      paymentTermsDays: vTerms,
    };
    setVendors((prev) => [...prev, vendor]);
    setShowAddVendor(false);
    resetVendorForm();
  }

  function handleAddInvoice() {
    if (!iVendorId) {
      setIError("Select a vendor");
      return;
    }
    const amount = parseFloat(iAmount);
    if (isNaN(amount) || amount <= 0) {
      setIError("Enter a valid amount");
      return;
    }
    if (!iDate) {
      setIError("Invoice date is required");
      return;
    }
    const invoice: MSMEInvoice = {
      id: Date.now().toString(),
      vendorId: iVendorId,
      invoiceDate: iDate,
      amountPaise: Math.round(amount * 100),
      paid: false,
    };
    setInvoices((prev) => [...prev, invoice]);
    setShowAddInvoice(false);
    resetInvoiceForm();
  }

  function markPaid(invoiceId: string) {
    setInvoices((prev) =>
      prev.map((inv) =>
        inv.id === invoiceId
          ? { ...inv, paid: true, paidDate: TODAY_ISO }
          : inv
      )
    );
  }

  // Build rows with computed fields
  const rows = invoices.map((inv) => {
    const vendor = vendors.find((v) => v.id === inv.vendorId);
    const termsDays = vendor?.paymentTermsDays ?? 45;
    const dueDate = computeDueDate(inv.invoiceDate, termsDays);
    const overdueDays = inv.paid ? 0 : daysDiff(dueDate, TODAY_ISO);
    const traffic = getTrafficLight(inv.paid, dueDate, TODAY_ISO);
    return {
      inv,
      vendor,
      dueDate,
      overdueDays,
      traffic,
    };
  });

  // Disallowance: unpaid invoices where overdueDays > 0
  const disallowedInvoices = rows.filter((r) => !r.inv.paid && r.overdueDays > 0);
  const totalDisallowancePaise = disallowedInvoices.reduce(
    (sum, r) => sum + r.inv.amountPaise,
    0
  );
  const totalOutstandingPaise = rows
    .filter((r) => !r.inv.paid)
    .reduce((sum, r) => sum + r.inv.amountPaise, 0);

  const inputCls =
    "w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500";

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-3">
          <Link
            href="/accounting"
            className="text-gray-400 hover:text-gray-600 mt-0.5"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h1 className="text-xl font-semibold text-gray-900">
              MSME 43B(h) Tracker
            </h1>
            <p className="text-sm text-gray-500 mt-0.5">
              IT Act Section 43B(h) — MSME payment compliance — FY 2026-27
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowAddInvoice(true)}
            disabled={vendors.length === 0}
            className="flex items-center gap-1.5 px-3 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <Plus className="w-4 h-4" />
            Add Invoice
          </button>
          <button
            onClick={() => setShowAddVendor(true)}
            className="flex items-center gap-1.5 px-3 py-2 border border-gray-200 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-50 transition-colors"
          >
            <Plus className="w-4 h-4" />
            Add MSME Vendor
          </button>
        </div>
      </div>

      {/* Info banner */}
      <div className="bg-blue-50 border border-blue-100 rounded-xl px-5 py-4 flex gap-3">
        <Info className="w-4 h-4 text-blue-600 shrink-0 mt-0.5" />
        <div>
          <p className="text-xs font-semibold text-blue-800 uppercase tracking-wide">
            About Section 43B(h)
          </p>
          <p className="text-xs text-blue-700 mt-1">
            Effective FY 2024-25, payments to MSME vendors must be made within
            45 days (written agreement) or 15 days (verbal/no agreement). If not
            paid by the due date, the expense is disallowed under Section 43B(h)
            of the IT Act and can only be deducted in the year of actual payment.
          </p>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-white rounded-xl border border-gray-100 p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center">
              <IndianRupee className="w-4 h-4 text-blue-600" />
            </div>
            <span className="text-xs text-gray-500">Total Outstanding</span>
          </div>
          <p className="text-lg font-semibold text-gray-900">
            {formatPaise(totalOutstandingPaise)}
          </p>
          <p className="text-xs text-gray-400 mt-0.5">
            {rows.filter((r) => !r.inv.paid).length} unpaid invoice(s)
          </p>
        </div>

        <div className="bg-white rounded-xl border border-gray-100 p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-red-50 flex items-center justify-center">
              <AlertTriangle className="w-4 h-4 text-red-600" />
            </div>
            <span className="text-xs text-gray-500">Disallowance Risk</span>
          </div>
          <p className="text-lg font-semibold text-red-600">
            {formatPaise(totalDisallowancePaise)}
          </p>
          <p className="text-xs text-gray-400 mt-0.5">
            s.43B(h) — overdue unpaid invoices
          </p>
        </div>

        <div className="bg-white rounded-xl border border-gray-100 p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-purple-50 flex items-center justify-center">
              <Plus className="w-4 h-4 text-purple-600" />
            </div>
            <span className="text-xs text-gray-500">MSME Vendors</span>
          </div>
          <p className="text-lg font-semibold text-gray-900">{vendors.length}</p>
          <p className="text-xs text-gray-400 mt-0.5">Registered</p>
        </div>

        <div className="bg-white rounded-xl border border-gray-100 p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-amber-50 flex items-center justify-center">
              <Clock className="w-4 h-4 text-amber-600" />
            </div>
            <span className="text-xs text-gray-500">Due Within 7 Days</span>
          </div>
          <p className="text-lg font-semibold text-gray-900">
            {rows.filter((r) => r.traffic === "yellow").length}
          </p>
          <p className="text-xs text-gray-400 mt-0.5">Invoice(s)</p>
        </div>
      </div>

      {/* Vendor List */}
      {vendors.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50">
            <h2 className="text-sm font-semibold text-gray-900">MSME Vendors</h2>
            <p className="text-xs text-gray-400 mt-0.5">
              Vendors registered under MSMED Act 2006
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-[10px] text-gray-400 uppercase tracking-wide">
                  <th className="text-left px-5 py-2.5">Vendor Name</th>
                  <th className="text-left px-4 py-2.5">GSTIN</th>
                  <th className="text-left px-4 py-2.5">MSME Reg No</th>
                  <th className="text-left px-4 py-2.5">Payment Terms</th>
                  <th className="text-right px-4 py-2.5">Outstanding</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {vendors.map((v) => {
                  const outstanding = invoices
                    .filter((inv) => inv.vendorId === v.id && !inv.paid)
                    .reduce((s, inv) => s + inv.amountPaise, 0);
                  return (
                    <tr key={v.id} className="hover:bg-gray-50/50">
                      <td className="px-5 py-3 font-medium text-gray-900">
                        {v.name}
                      </td>
                      <td className="px-4 py-3">
                        {v.gstin ? (
                          <span className="text-xs font-mono text-gray-600 bg-gray-50 px-1.5 py-0.5 rounded">
                            {v.gstin}
                          </span>
                        ) : (
                          <span className="text-gray-300 text-xs">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-600">
                        {v.msmeRegNo || <span className="text-gray-300">—</span>}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`text-xs px-2 py-0.5 rounded-full font-medium ${v.paymentTermsDays === 15 ? "bg-purple-100 text-purple-700" : "bg-blue-100 text-blue-700"}`}
                        >
                          {v.paymentTermsDays} days
                          {v.paymentTermsDays === 15 ? " (verbal)" : " (written)"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right text-sm font-medium text-gray-900">
                        {formatPaise(outstanding)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Invoice Table */}
      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-gray-900">
              Invoices — 43B(h) Compliance
            </h2>
            <p className="text-xs text-gray-400 mt-0.5">
              Track payment status to avoid disallowance under IT Act Section 43B(h)
            </p>
          </div>
          {disallowedInvoices.length > 0 && (
            <span className="flex items-center gap-1 text-xs text-red-600 font-medium">
              <AlertTriangle className="w-3.5 h-3.5" />
              {disallowedInvoices.length} overdue — disallowance risk
            </span>
          )}
        </div>

        {invoices.length === 0 ? (
          <div className="px-5 py-14 text-center space-y-3">
            <IndianRupee className="w-10 h-10 text-gray-200 mx-auto" />
            <p className="text-sm font-medium text-gray-600">
              No invoices tracked yet
            </p>
            <p className="text-xs text-gray-400 max-w-sm mx-auto">
              Add MSME vendors first, then add invoices to track 43B(h)
              compliance. Overdue payments risk disallowance of the deduction.
            </p>
            {vendors.length === 0 ? (
              <button
                onClick={() => setShowAddVendor(true)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 text-blue-600 text-xs font-medium rounded-lg hover:bg-blue-100 transition-colors mt-1"
              >
                <Plus className="w-3.5 h-3.5" />
                Add first MSME vendor
              </button>
            ) : (
              <button
                onClick={() => setShowAddInvoice(true)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 text-blue-600 text-xs font-medium rounded-lg hover:bg-blue-100 transition-colors mt-1"
              >
                <Plus className="w-3.5 h-3.5" />
                Add first invoice
              </button>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-[10px] text-gray-400 uppercase tracking-wide">
                  <th className="text-left px-5 py-2.5">Status</th>
                  <th className="text-left px-4 py-2.5">Vendor</th>
                  <th className="text-left px-4 py-2.5">Invoice Date</th>
                  <th className="text-right px-4 py-2.5">Amount</th>
                  <th className="text-left px-4 py-2.5">Due Date</th>
                  <th className="text-right px-4 py-2.5">Days Overdue</th>
                  <th className="text-left px-4 py-2.5">Disallowance</th>
                  <th className="px-5 py-2.5"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {rows.map(({ inv, vendor, dueDate, overdueDays, traffic }) => (
                  <tr key={inv.id} className="hover:bg-gray-50/50">
                    <td className="px-5 py-3">
                      <span
                        className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium ${TRAFFIC_STYLE[traffic]}`}
                      >
                        {TRAFFIC_ICON[traffic]}
                        {inv.paid ? "Paid" : TRAFFIC_LABEL[traffic]}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <p className="font-medium text-gray-900">
                        {vendor?.name ?? "—"}
                      </p>
                      {vendor?.gstin && (
                        <p className="text-[10px] font-mono text-gray-400">
                          {vendor.gstin}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-600">
                      {new Date(inv.invoiceDate).toLocaleDateString("en-IN", {
                        day: "numeric",
                        month: "short",
                        year: "numeric",
                      })}
                    </td>
                    <td className="px-4 py-3 text-right font-medium text-gray-900">
                      {formatPaise(inv.amountPaise)}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-600">
                      {new Date(dueDate).toLocaleDateString("en-IN", {
                        day: "numeric",
                        month: "short",
                        year: "numeric",
                      })}
                      <p className="text-[10px] text-gray-400 mt-0.5">
                        {vendor?.paymentTermsDays ?? 45} day terms
                      </p>
                    </td>
                    <td className="px-4 py-3 text-right">
                      {inv.paid ? (
                        <span className="text-xs text-gray-400">Paid</span>
                      ) : overdueDays > 0 ? (
                        <span className="text-xs font-medium text-red-600">
                          {overdueDays} days
                        </span>
                      ) : (
                        <span className="text-xs text-gray-400">
                          {-overdueDays} days left
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {!inv.paid && overdueDays > 0 ? (
                        <span className="text-xs text-red-600 font-medium">
                          {formatPaise(inv.amountPaise)}
                        </span>
                      ) : (
                        <span className="text-xs text-gray-300">—</span>
                      )}
                    </td>
                    <td className="px-5 py-3">
                      {!inv.paid && (
                        <button
                          onClick={() => markPaid(inv.id)}
                          className="text-xs text-green-600 hover:text-green-800 font-medium whitespace-nowrap"
                        >
                          Mark Paid
                        </button>
                      )}
                      {inv.paid && inv.paidDate && (
                        <span className="text-[10px] text-gray-400">
                          Paid{" "}
                          {new Date(inv.paidDate).toLocaleDateString("en-IN", {
                            day: "numeric",
                            month: "short",
                          })}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Disallowance Summary */}
      {invoices.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-100 p-5 space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-gray-900">
              Disallowance Summary — Section 43B(h)
            </h2>
            <p className="text-xs text-gray-400 mt-0.5">
              Total amount at risk of disallowance for FY 2026-27
            </p>
          </div>

          <div className="space-y-2 text-xs">
            <div className="flex justify-between">
              <span className="text-gray-500">Total MSME Invoices</span>
              <span className="text-gray-700">
                {formatPaise(
                  invoices.reduce((s, i) => s + i.amountPaise, 0)
                )}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Paid on time</span>
              <span className="text-green-600">
                {formatPaise(
                  invoices
                    .filter((i) => i.paid)
                    .reduce((s, i) => s + i.amountPaise, 0)
                )}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Overdue — disallowance risk</span>
              <span className="text-red-600 font-medium">
                {formatPaise(totalDisallowancePaise)}
              </span>
            </div>
            <div className="flex justify-between border-t border-gray-100 pt-2 mt-2">
              <span className="font-semibold text-gray-700">
                Net Deductible under 43B(h)
              </span>
              <span className="font-bold text-gray-900">
                {formatPaise(
                  invoices
                    .filter((i) => i.paid)
                    .reduce((s, i) => s + i.amountPaise, 0)
                )}
              </span>
            </div>
          </div>

          {totalDisallowancePaise > 0 && (
            <div className="flex gap-3 bg-red-50 border border-red-100 rounded-lg px-4 py-3">
              {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
              <AlertCircle className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />
              <p className="text-xs text-red-700">
                <strong>
                  {formatPaise(totalDisallowancePaise)}
                </strong>{" "}
                will be disallowed under Section 43B(h). Pay overdue MSME
                invoices before 31 March 2027 to retain deduction in FY
                2026-27.
              </p>
            </div>
          )}

          {totalDisallowancePaise === 0 && invoices.length > 0 && (
            <p className="text-xs text-green-700 bg-green-50 rounded px-3 py-2">
              All MSME invoices paid on time — no disallowance under Section
              43B(h) for FY 2026-27.
            </p>
          )}
        </div>
      )}

      {/* ================================================================== */}
      {/* MODAL: Add Vendor                                                   */}
      {/* ================================================================== */}
      {showAddVendor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            <div className="flex items-center justify-between px-6 py-5 border-b border-gray-100">
              <h3 className="text-base font-semibold text-gray-900">
                Add MSME Vendor
              </h3>
              <button
                onClick={() => {
                  setShowAddVendor(false);
                  resetVendorForm();
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="px-6 py-5 space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  Vendor Name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  placeholder="e.g. ABC Enterprises"
                  value={vName}
                  onChange={(e) => setVName(e.target.value)}
                  className={inputCls}
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  GSTIN
                  <span className="ml-1 text-gray-400 font-normal">(optional)</span>
                </label>
                <input
                  type="text"
                  placeholder="e.g. 27AABCU9603R1ZM"
                  value={vGstin}
                  onChange={(e) => setVGstin(e.target.value.toUpperCase())}
                  className={`${inputCls} font-mono`}
                  maxLength={15}
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  MSME Registration Number
                  <span className="ml-1 text-gray-400 font-normal">(Udyam/Udyog Aadhaar)</span>
                </label>
                <input
                  type="text"
                  placeholder="e.g. UDYAM-MH-12-0012345"
                  value={vMsmeReg}
                  onChange={(e) => setVMsmeReg(e.target.value)}
                  className={inputCls}
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 mb-2">
                  Payment Terms
                </label>
                <div className="flex gap-3">
                  <button
                    onClick={() => setVTerms(45)}
                    className={`flex-1 py-2 text-sm rounded-lg border transition-colors ${vTerms === 45 ? "bg-blue-600 text-white border-blue-600" : "border-gray-200 text-gray-600 hover:bg-gray-50"}`}
                  >
                    45 days (written agreement)
                  </button>
                  <button
                    onClick={() => setVTerms(15)}
                    className={`flex-1 py-2 text-sm rounded-lg border transition-colors ${vTerms === 15 ? "bg-blue-600 text-white border-blue-600" : "border-gray-200 text-gray-600 hover:bg-gray-50"}`}
                  >
                    15 days (verbal / none)
                  </button>
                </div>
                <p className="text-[10px] text-gray-400 mt-1.5">
                  MSMED Act 2006 Section 15 — 15 days if no written agreement
                </p>
              </div>

              {vError && (
                <p className="text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg">
                  {vError}
                </p>
              )}
            </div>

            <div className="px-6 py-4 border-t border-gray-100 flex gap-3 justify-end">
              <button
                onClick={() => {
                  setShowAddVendor(false);
                  resetVendorForm();
                }}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200"
              >
                Cancel
              </button>
              <button
                onClick={handleAddVendor}
                className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700"
              >
                Add Vendor
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ================================================================== */}
      {/* MODAL: Add Invoice                                                  */}
      {/* ================================================================== */}
      {showAddInvoice && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            <div className="flex items-center justify-between px-6 py-5 border-b border-gray-100">
              <h3 className="text-base font-semibold text-gray-900">
                Add Invoice
              </h3>
              <button
                onClick={() => {
                  setShowAddInvoice(false);
                  resetInvoiceForm();
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="px-6 py-5 space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  Vendor <span className="text-red-500">*</span>
                </label>
                <select
                  value={iVendorId}
                  onChange={(e) => setIVendorId(e.target.value)}
                  className={inputCls}
                >
                  <option value="">Select MSME vendor…</option>
                  {vendors.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name} ({v.paymentTermsDays} days)
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  Invoice Date <span className="text-red-500">*</span>
                </label>
                <input
                  type="date"
                  value={iDate}
                  onChange={(e) => setIDate(e.target.value)}
                  className={inputCls}
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  Invoice Amount (₹) <span className="text-red-500">*</span>
                </label>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  placeholder="0.00"
                  value={iAmount}
                  onChange={(e) => setIAmount(e.target.value)}
                  className={`${inputCls} text-right tabular-nums`}
                />
              </div>

              {/* Auto-computed due date preview */}
              {iVendorId && iDate && (
                <div className="bg-gray-50 rounded-lg px-4 py-3 text-xs space-y-1">
                  <div className="flex justify-between">
                    <span className="text-gray-500">Payment Terms</span>
                    <span className="font-medium text-gray-700">
                      {vendors.find((v) => v.id === iVendorId)?.paymentTermsDays ?? 45} days
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Payment Due By</span>
                    <span className="font-semibold text-gray-900">
                      {new Date(
                        computeDueDate(
                          iDate,
                          vendors.find((v) => v.id === iVendorId)
                            ?.paymentTermsDays ?? 45
                        )
                      ).toLocaleDateString("en-IN", {
                        day: "numeric",
                        month: "long",
                        year: "numeric",
                      })}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Disallowance date (if unpaid)</span>
                    <span className="text-red-600 font-medium">
                      {new Date(
                        computeDueDate(
                          iDate,
                          vendors.find((v) => v.id === iVendorId)
                            ?.paymentTermsDays ?? 45
                        )
                      ).toLocaleDateString("en-IN", {
                        day: "numeric",
                        month: "long",
                        year: "numeric",
                      })}
                    </span>
                  </div>
                </div>
              )}

              {iError && (
                <p className="text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg">
                  {iError}
                </p>
              )}
            </div>

            <div className="px-6 py-4 border-t border-gray-100 flex gap-3 justify-end">
              <button
                onClick={() => {
                  setShowAddInvoice(false);
                  resetInvoiceForm();
                }}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200"
              >
                Cancel
              </button>
              <button
                onClick={handleAddInvoice}
                className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700"
              >
                Add Invoice
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Info icon (inline to avoid extra import)
// ---------------------------------------------------------------------------
function Info({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
    >
      <circle cx="12" cy="12" r="10" strokeWidth={2} />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 16v-4M12 8h.01" />
    </svg>
  );
}
