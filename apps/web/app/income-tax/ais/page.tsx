"use client";

/**
 * AIS (Annual Information Statement) Ingestion Tool
 * IT Act Section 285BB — Annual Information Statement
 * CAs must review AIS before filing ITR to identify unreported income.
 *
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
 * This tool only assists in reviewing AIS data. No submission to Income Tax Portal.
 */

import { useState, useRef, useCallback } from "react";
import Link from "next/link";
import {
  Upload,
  ArrowLeft,
  Plus,
  Download,
  AlertTriangle,
  CheckCircle2,
  AlertCircle,
  FileText,
  Trash2,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TransactionType =
  | "Salary"
  | "Interest"
  | "Dividend"
  | "Stock Sale"
  | "Property Sale"
  | "Foreign Remittance"
  | "Rent Received"
  | "Other";

const TRANSACTION_TYPES: TransactionType[] = [
  "Salary",
  "Interest",
  "Dividend",
  "Stock Sale",
  "Property Sale",
  "Foreign Remittance",
  "Rent Received",
  "Other",
];

interface AISTransaction {
  id: string;
  type: TransactionType;
  /** Amount in paise — integer arithmetic only, never floating point */
  amountPaise: number;
  payer: string;
  tdsDeductedPaise: number;
  source: "json" | "manual";
}

interface ComparisonRow extends AISTransaction {
  /** Amount in books in paise — entered by CA */
  booksAmountPaise: number;
  status: "matched" | "not_in_books" | "amount_mismatch";
}

// ---------------------------------------------------------------------------
// AIS JSON parser
// IT Act Section 285BB — AIS format from Income Tax portal
// ---------------------------------------------------------------------------

interface AISSubCategory {
  informationDescription?: { label?: string; value?: string }[];
  informationValue?: string;
  informationSource?: string;
  amount?: number | string;
  tdsAmount?: number | string;
  [key: string]: unknown;
}

interface AISRoot {
  AnnualInformationStatement?: {
    taxpayerInfo?: { pan?: string; name?: string };
    aisInformation?: {
      aisSubInformationCategory?: AISSubCategory[];
    };
  };
}

/** Convert rupees (possibly float from external JSON) to paise using integer arithmetic */
function rupeesToPaise(val: number | string | undefined): number {
  if (val === undefined || val === null || val === "") return 0;
  const n = typeof val === "string" ? parseFloat(val) : val;
  if (isNaN(n)) return 0;
  // Multiply by 100 and round to avoid floating point issues
  return Math.round(n * 100);
}

function formatRupees(paise: number): string {
  const rupees = Math.floor(Math.abs(paise) / 100);
  const paiseRemainder = Math.abs(paise) % 100;
  const sign = paise < 0 ? "-" : "";
  const formatted = rupees.toLocaleString("en-IN");
  return `${sign}₹${formatted}.${String(paiseRemainder).padStart(2, "0")}`;
}

function guessTransactionType(label: string): TransactionType {
  const l = label.toLowerCase();
  if (l.includes("salary") || l.includes("tds on salary")) return "Salary";
  if (l.includes("interest")) return "Interest";
  if (l.includes("dividend")) return "Dividend";
  if (l.includes("securities") || l.includes("stock") || l.includes("shares") || l.includes("mutual fund"))
    return "Stock Sale";
  if (l.includes("property") || l.includes("immovable")) return "Property Sale";
  if (l.includes("foreign") || l.includes("remittance")) return "Foreign Remittance";
  if (l.includes("rent")) return "Rent Received";
  return "Other";
}

function parseAISJSON(raw: string): AISTransaction[] {
  const root: AISRoot = JSON.parse(raw);
  const categories =
    root?.AnnualInformationStatement?.aisInformation?.aisSubInformationCategory ?? [];

  const results: AISTransaction[] = [];
  let idx = 0;

  for (const cat of categories) {
    const descArr = cat.informationDescription ?? [];
    const labelEntry = descArr.find((d) => d.label?.toLowerCase().includes("nature") || d.label?.toLowerCase().includes("type"));
    const label = labelEntry?.value ?? cat.informationSource ?? "Other";
    const type = guessTransactionType(label);
    const amountPaise = rupeesToPaise(cat.amount ?? cat.informationValue);
    const tdsDeductedPaise = rupeesToPaise(cat.tdsAmount);
    const payer =
      descArr.find((d) => d.label?.toLowerCase().includes("deductor") || d.label?.toLowerCase().includes("payer") || d.label?.toLowerCase().includes("source"))
        ?.value ?? cat.informationSource ?? "Unknown";

    results.push({
      id: `ais-${idx++}`,
      type,
      amountPaise,
      payer,
      tdsDeductedPaise,
      source: "json",
    });
  }

  return results;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

const BLANK_MANUAL = {
  type: "Salary" as TransactionType,
  amount: "",
  payer: "",
  tds: "",
};

export default function AISPage() {
  const [clientName, setClientName] = useState("");
  const [transactions, setTransactions] = useState<AISTransaction[]>([]);
  const [parseError, setParseError] = useState<string | null>(null);
  const [showManual, setShowManual] = useState(false);
  const [manualForm, setManualForm] = useState(BLANK_MANUAL);

  // Comparison table — booksAmountPaise entered by CA
  const [booksAmounts, setBooksAmounts] = useState<Record<string, string>>({});

  const fileRef = useRef<HTMLInputElement>(null);

  // ---------------------------------------------------------------------------
  // File upload
  // ---------------------------------------------------------------------------

  const handleFileUpload = useCallback((file: File) => {
    setParseError(null);
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target?.result as string;
      try {
        const parsed = parseAISJSON(text);
        if (parsed.length === 0) {
          setParseError(
            "No transactions found in the AIS JSON. Please verify the file format or use manual entry below."
          );
          setShowManual(true);
        } else {
          setTransactions((prev) => [...prev, ...parsed]);
        }
      } catch {
        setParseError(
          "Could not parse AIS JSON. The file may be in an unexpected format. Please use manual entry below."
        );
        setShowManual(true);
      }
    };
    reader.readAsText(file);
  }, []);

  // ---------------------------------------------------------------------------
  // Manual entry
  // ---------------------------------------------------------------------------

  function handleAddManual() {
    if (!manualForm.payer.trim() || !manualForm.amount.trim()) return;
    const amountPaise = rupeesToPaise(manualForm.amount);
    const tdsDeductedPaise = rupeesToPaise(manualForm.tds || "0");
    setTransactions((prev) => [
      ...prev,
      {
        id: `manual-${Date.now()}`,
        type: manualForm.type,
        amountPaise,
        payer: manualForm.payer.trim(),
        tdsDeductedPaise,
        source: "manual",
      },
    ]);
    setManualForm(BLANK_MANUAL);
  }

  function handleDeleteTransaction(id: string) {
    setTransactions((prev) => prev.filter((t) => t.id !== id));
    setBooksAmounts((prev) => {
      const copy = { ...prev };
      delete copy[id];
      return copy;
    });
  }

  // ---------------------------------------------------------------------------
  // Comparison table
  // ---------------------------------------------------------------------------

  const comparisonRows: ComparisonRow[] = transactions.map((t) => {
    const booksStr = booksAmounts[t.id] ?? "";
    const booksAmountPaise = booksStr.trim() === "" ? -1 : rupeesToPaise(booksStr);
    let status: ComparisonRow["status"];
    if (booksAmountPaise < 0) {
      status = "not_in_books";
    } else if (booksAmountPaise === t.amountPaise) {
      status = "matched";
    } else {
      status = "amount_mismatch";
    }
    return { ...t, booksAmountPaise: Math.max(0, booksAmountPaise), status };
  });

  // ---------------------------------------------------------------------------
  // Discrepancy summary
  // Integer paise arithmetic — IT Act Section 139 — declaring all income
  // ---------------------------------------------------------------------------

  const totalAISPaise = transactions.reduce((s, t) => s + t.amountPaise, 0);
  const notInBooks = comparisonRows.filter((r) => r.status === "not_in_books");
  const mismatched = comparisonRows.filter((r) => r.status === "amount_mismatch");

  // Estimated undeclared = AIS amounts not in books + positive differences for mismatches
  const undeclaredPaise = [
    ...notInBooks.map((r) => r.amountPaise),
    ...mismatched.map((r) => Math.max(0, r.amountPaise - r.booksAmountPaise)),
  ].reduce((s, v) => s + v, 0);

  // Rough estimated tax at 30% slab (conservative high estimate) — integer paise
  const estimatedTaxPaise = Math.round(undeclaredPaise * 30) / 100;

  // ---------------------------------------------------------------------------
  // CSV export
  // ---------------------------------------------------------------------------

  function exportCSV() {
    const header = [
      "Client",
      "Transaction Type",
      "Payer/Deductor",
      "AIS Amount (₹)",
      "TDS Deducted (₹)",
      "Amount in Books (₹)",
      "Difference (₹)",
      "Status",
    ].join(",");

    const rows = comparisonRows.map((r) => {
      const diff =
        r.status === "not_in_books"
          ? r.amountPaise
          : r.amountPaise - r.booksAmountPaise;
      return [
        `"${clientName}"`,
        `"${r.type}"`,
        `"${r.payer}"`,
        (r.amountPaise / 100).toFixed(2),
        (r.tdsDeductedPaise / 100).toFixed(2),
        r.status === "not_in_books" ? "Not entered" : (r.booksAmountPaise / 100).toFixed(2),
        (diff / 100).toFixed(2),
        `"${r.status === "matched" ? "Matched" : r.status === "not_in_books" ? "Not in Books" : "Amount Mismatch"}"`,
      ].join(",");
    });

    const csv = [header, ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `AIS_Discrepancy_${clientName || "Client"}_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const statusBadge = (status: ComparisonRow["status"]) => {
    if (status === "matched")
      return (
        <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700 font-medium">
          <CheckCircle2 className="w-3 h-3" /> Matched
        </span>
      );
    if (status === "not_in_books")
      return (
        <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700 font-medium">
          <AlertCircle className="w-3 h-3" /> Not in Books
        </span>
      );
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 font-medium">
        <AlertTriangle className="w-3 h-3" /> Amount Mismatch
      </span>
    );
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <Link
            href="/income-tax"
            className="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 mb-2 transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Income Tax
          </Link>
          <h1 className="text-xl font-semibold text-gray-900">
            AIS Ingestion Tool
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Annual Information Statement — IT Act Section 285BB
          </p>
        </div>
        {transactions.length > 0 && (
          <button
            onClick={exportCSV}
            className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-lg hover:bg-green-700 transition-colors"
          >
            <Download className="w-4 h-4" />
            Export Discrepancy CSV
          </button>
        )}
      </div>

      {/* Client selector */}
      <div className="bg-white rounded-xl border border-gray-100 px-5 py-4">
        <label className="block text-xs font-medium text-gray-700 mb-1.5">
          Client Name
        </label>
        <input
          type="text"
          placeholder="Enter client name for this AIS review…"
          value={clientName}
          onChange={(e) => setClientName(e.target.value)}
          className="w-full max-w-sm border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {/* Upload AIS JSON */}
      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50">
          <h2 className="text-sm font-semibold text-gray-900">
            Step 1 — Upload AIS JSON
          </h2>
          <p className="text-xs text-gray-400 mt-0.5">
            Download from{" "}
            <span className="font-mono">incometax.gov.in</span> → AIS → Download JSON
          </p>
        </div>
        <div className="px-5 py-6">
          <input
            ref={fileRef}
            type="file"
            accept=".json,application/json"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleFileUpload(file);
              e.target.value = "";
            }}
          />
          <div
            onClick={() => fileRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const file = e.dataTransfer.files[0];
              if (file) handleFileUpload(file);
            }}
            className="border-2 border-dashed border-gray-200 rounded-xl p-8 text-center cursor-pointer hover:border-blue-300 hover:bg-blue-50/30 transition-colors"
          >
            <Upload className="w-8 h-8 text-gray-300 mx-auto mb-3" />
            <p className="text-sm font-medium text-gray-600">
              Click to upload or drag & drop AIS JSON
            </p>
            <p className="text-xs text-gray-400 mt-1">
              Supports the AnnualInformationStatement JSON format from the IT portal
            </p>
          </div>

          {parseError && (
            <div className="mt-3 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
              <p className="text-xs text-amber-700">{parseError}</p>
            </div>
          )}

          <button
            onClick={() => setShowManual((v) => !v)}
            className="mt-4 inline-flex items-center gap-1.5 text-xs text-blue-600 hover:text-blue-700 font-medium transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            {showManual ? "Hide" : "Show"} manual entry form
          </button>
        </div>
      </div>

      {/* Manual entry form */}
      {showManual && (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50">
            <h2 className="text-sm font-semibold text-gray-900">
              Manual Transaction Entry
            </h2>
            <p className="text-xs text-gray-400 mt-0.5">
              Add transactions manually when JSON is unavailable or incomplete
            </p>
          </div>
          <div className="px-5 py-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  Transaction Type
                </label>
                <select
                  value={manualForm.type}
                  onChange={(e) =>
                    setManualForm((p) => ({ ...p, type: e.target.value as TransactionType }))
                  }
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {TRANSACTION_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  Payer / Deductor Name
                </label>
                <input
                  type="text"
                  placeholder="e.g. ABC Pvt Ltd"
                  value={manualForm.payer}
                  onChange={(e) =>
                    setManualForm((p) => ({ ...p, payer: e.target.value }))
                  }
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  Amount (₹)
                </label>
                <input
                  type="number"
                  placeholder="e.g. 500000"
                  min="0"
                  value={manualForm.amount}
                  onChange={(e) =>
                    setManualForm((p) => ({ ...p, amount: e.target.value }))
                  }
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  TDS Deducted (₹)
                </label>
                <input
                  type="number"
                  placeholder="e.g. 50000"
                  min="0"
                  value={manualForm.tds}
                  onChange={(e) =>
                    setManualForm((p) => ({ ...p, tds: e.target.value }))
                  }
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>
            <button
              onClick={handleAddManual}
              disabled={!manualForm.payer.trim() || !manualForm.amount.trim()}
              className="mt-3 inline-flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 transition-colors"
            >
              <Plus className="w-4 h-4" />
              Add Transaction
            </button>
          </div>
        </div>
      )}

      {/* Transactions loaded */}
      {transactions.length > 0 && (
        <>
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50 flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-gray-900">
                  Step 2 — Comparison Table
                </h2>
                <p className="text-xs text-gray-400 mt-0.5">
                  Enter &ldquo;Amount in Books&rdquo; for each AIS transaction to identify discrepancies
                </p>
              </div>
              <span className="text-xs text-gray-500 font-medium">
                {transactions.length} transaction{transactions.length !== 1 ? "s" : ""} · Total AIS: {formatRupees(totalAISPaise)}
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 text-xs text-gray-500 font-medium uppercase tracking-wider">
                    <th className="px-5 py-2.5 text-left">Transaction Type</th>
                    <th className="px-4 py-2.5 text-left">Payer / Deductor</th>
                    <th className="px-4 py-2.5 text-left">Source</th>
                    <th className="px-4 py-2.5 text-right">AIS Amount</th>
                    <th className="px-4 py-2.5 text-right">TDS Deducted</th>
                    <th className="px-4 py-2.5 text-right">Amount in Books</th>
                    <th className="px-4 py-2.5 text-right">Difference</th>
                    <th className="px-4 py-2.5 text-left">Status</th>
                    <th className="px-4 py-2.5 text-left"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {comparisonRows.map((row) => {
                    const diff =
                      row.status === "not_in_books"
                        ? row.amountPaise
                        : row.amountPaise - row.booksAmountPaise;
                    return (
                      <tr key={row.id} className="hover:bg-gray-50/50 transition-colors">
                        <td className="px-5 py-3 font-medium text-gray-900">
                          {row.type}
                        </td>
                        <td className="px-4 py-3 text-gray-600 text-xs max-w-xs truncate">
                          {row.payer}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                              row.source === "json"
                                ? "bg-purple-50 text-purple-700"
                                : "bg-gray-100 text-gray-600"
                            }`}
                          >
                            {row.source === "json" ? "AIS JSON" : "Manual"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right text-gray-900 font-medium text-xs">
                          {formatRupees(row.amountPaise)}
                        </td>
                        <td className="px-4 py-3 text-right text-gray-600 text-xs">
                          {row.tdsDeductedPaise > 0
                            ? formatRupees(row.tdsDeductedPaise)
                            : <span className="text-gray-300">—</span>}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <input
                            type="number"
                            placeholder="Enter amount"
                            min="0"
                            value={booksAmounts[row.id] ?? ""}
                            onChange={(e) =>
                              setBooksAmounts((prev) => ({
                                ...prev,
                                [row.id]: e.target.value,
                              }))
                            }
                            className="w-32 border border-gray-200 rounded-lg px-2 py-1 text-xs text-gray-900 text-right focus:outline-none focus:ring-2 focus:ring-blue-500"
                          />
                        </td>
                        <td className="px-4 py-3 text-right text-xs font-medium">
                          {row.status === "not_in_books" ? (
                            <span className="text-red-600">
                              {formatRupees(diff)}
                            </span>
                          ) : diff === 0 ? (
                            <span className="text-green-600">₹0.00</span>
                          ) : (
                            <span className="text-amber-600">
                              {formatRupees(diff)}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3">{statusBadge(row.status)}</td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => handleDeleteTransaction(row.id)}
                            className="text-gray-300 hover:text-red-500 transition-colors"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Discrepancy Summary */}
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50">
              <h2 className="text-sm font-semibold text-gray-900">
                Step 3 — Discrepancy Summary
              </h2>
              <p className="text-xs text-gray-400 mt-0.5">
                Estimated tax impact at 30% slab rate — conservative estimate
              </p>
            </div>
            <div className="px-5 py-5 grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="bg-gray-50 rounded-xl p-4">
                <p className="text-xs text-gray-500 font-medium uppercase tracking-wide mb-1">
                  Total AIS Income
                </p>
                <p className="text-lg font-semibold text-gray-900">
                  {formatRupees(totalAISPaise)}
                </p>
              </div>
              <div className="bg-red-50 rounded-xl p-4">
                <p className="text-xs text-red-600 font-medium uppercase tracking-wide mb-1">
                  Not in Books
                </p>
                <p className="text-lg font-semibold text-red-700">
                  {notInBooks.length} transaction{notInBooks.length !== 1 ? "s" : ""}
                </p>
              </div>
              <div className="bg-amber-50 rounded-xl p-4">
                <p className="text-xs text-amber-600 font-medium uppercase tracking-wide mb-1">
                  Est. Undeclared Amount
                </p>
                <p className="text-lg font-semibold text-amber-700">
                  {formatRupees(undeclaredPaise)}
                </p>
              </div>
              <div className="bg-orange-50 rounded-xl p-4">
                <p className="text-xs text-orange-600 font-medium uppercase tracking-wide mb-1">
                  Est. Tax Impact (30%)
                </p>
                <p className="text-lg font-semibold text-orange-700">
                  {formatRupees(estimatedTaxPaise)}
                </p>
              </div>
            </div>

            {(notInBooks.length > 0 || mismatched.length > 0) && (
              <div className="px-5 pb-5">
                <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 flex items-start gap-3">
                  <AlertTriangle className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />
                  <div>
                    <p className="text-xs font-semibold text-red-800">
                      Discrepancies Found — CA Review Required
                    </p>
                    <p className="text-xs text-red-700 mt-1">
                      {notInBooks.length > 0 && (
                        <span>
                          {notInBooks.length} transaction{notInBooks.length !== 1 ? "s" : ""} not found in client&apos;s books.{" "}
                        </span>
                      )}
                      {mismatched.length > 0 && (
                        <span>
                          {mismatched.length} transaction{mismatched.length !== 1 ? "s" : ""} with amount mismatch.{" "}
                        </span>
                      )}
                      These must be reconciled before filing the ITR. Do not file ITR without resolving discrepancies.
                    </p>
                  </div>
                </div>
              </div>
            )}

            {notInBooks.length === 0 && mismatched.length === 0 && transactions.length > 0 && (
              <div className="px-5 pb-5">
                <div className="bg-green-50 border border-green-200 rounded-xl px-4 py-3 flex items-center gap-3">
                  <CheckCircle2 className="w-4 h-4 text-green-600 shrink-0" />
                  <p className="text-xs text-green-700 font-medium">
                    All AIS transactions matched with books. Safe to proceed with ITR filing.
                  </p>
                </div>
              </div>
            )}
          </div>
        </>
      )}

      {/* Empty state */}
      {transactions.length === 0 && !parseError && (
        <div className="bg-white rounded-xl border border-gray-100 px-5 py-14 text-center space-y-3">
          <FileText className="w-10 h-10 text-gray-200 mx-auto" />
          <p className="text-sm font-medium text-gray-600">
            No AIS data loaded yet
          </p>
          <p className="text-xs text-gray-400 max-w-sm mx-auto">
            Upload the AIS JSON downloaded from the Income Tax portal, or use manual entry to add transactions.
          </p>
        </div>
      )}

      {/* Footer note */}
      <div className="bg-blue-50 border border-blue-100 rounded-xl px-5 py-3">
        <p className="text-xs text-blue-700">
          <span className="font-semibold">Note:</span> AIS data is governed by IT Act Section 285BB. Data entered here is stored locally in your browser only. CAflow does not transmit AIS data to any external server or government portal.
        </p>
      </div>
    </div>
  );
}
