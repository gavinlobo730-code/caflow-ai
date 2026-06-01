"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { Upload, CheckCircle, AlertCircle, ArrowRight, Building2, FileText } from "lucide-react";
import { getClients } from "@/lib/data/clients";
import { parseCSV, importBankStatement } from "@/lib/data/bankStatements";
import type { ParsedTransaction } from "@/lib/data/bankStatements";
import type { Client } from "@/lib/types";

const BANKS = [
  "HDFC Bank", "SBI", "ICICI Bank", "Axis Bank", "Kotak Mahindra Bank",
  "Bank of Baroda", "Punjab National Bank", "Canara Bank", "Union Bank", "Other",
];

function formatPaise(p: number) {
  return "₹" + (p / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 });
}

type Step = "upload" | "review" | "done";

export default function BankImportPage() {
  const [step, setStep] = useState<Step>("upload");
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState("");
  const [bankName, setBankName] = useState("HDFC Bank");
  const [accountNo, setAccountNo] = useState("");
  const [parsed, setParsed] = useState<ParsedTransaction[]>([]);
  const [fileName, setFileName] = useState("");
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getClients().then(setClients).catch(() => {});
  }, []);

  const processFile = useCallback(async (file: File) => {
    setError(null);
    if (!clientId) { setError("Select a client first"); return; }
    const text = await file.text();
    const rows = parseCSV(text);
    if (rows.length === 0) {
      setError("No transactions found. Make sure this is a CSV bank statement.");
      return;
    }
    setFileName(file.name);
    setParsed(rows);
    setStep("review");
  }, [clientId]);

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) processFile(file);
  }

  async function handleImport() {
    if (!clientId || parsed.length === 0) return;
    setImporting(true);
    setError(null);
    try {
      await importBankStatement(clientId, bankName, accountNo, parsed);
      setStep("done");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setImporting(false);
    }
  }

  const totalDebits = parsed.reduce((s, t) => s + t.debit_paise, 0);
  const totalCredits = parsed.reduce((s, t) => s + t.credit_paise, 0);

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Bank Statement Import</h1>
        <p className="text-sm text-gray-500 mt-1">Import CSV bank statements from any Indian bank</p>
      </div>

      {/* Steps indicator */}
      <div className="flex items-center gap-2 text-sm">
        {(["upload", "review", "done"] as Step[]).map((s, i) => (
          <div key={s} className="flex items-center gap-2">
            {i > 0 && <ArrowRight size={14} className="text-gray-300" />}
            <span className={`px-3 py-1 rounded-full text-xs font-medium ${
              step === s ? "bg-blue-600 text-white" :
              (["upload","review","done"].indexOf(step) > i) ? "bg-green-100 text-green-700" :
              "bg-gray-100 text-gray-500"
            }`}>
              {i + 1}. {s.charAt(0).toUpperCase() + s.slice(1)}
            </span>
          </div>
        ))}
      </div>

      {step === "upload" && (
        <div className="space-y-5">
          {/* Client + Bank selection */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Client *</label>
              <select value={clientId} onChange={e => setClientId(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500">
                <option value="">Select client…</option>
                {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Bank</label>
              <select value={bankName} onChange={e => setBankName(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500">
                {BANKS.map(b => <option key={b}>{b}</option>)}
              </select>
            </div>
            <div className="col-span-2">
              <label className="block text-xs font-medium text-gray-700 mb-1">Account Number (optional)</label>
              <input value={accountNo} onChange={e => setAccountNo(e.target.value)}
                placeholder="XXXX XXXX XXXX 1234"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500" />
            </div>
          </div>

          {/* Supported banks */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-gray-500">Supported formats:</span>
            {["HDFC", "SBI", "ICICI", "Axis", "Kotak", "Generic CSV"].map(b => (
              <span key={b} className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">{b}</span>
            ))}
          </div>

          {/* Drop zone */}
          <div
            onDragOver={e => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileRef.current?.click()}
            className={`flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-12 cursor-pointer transition-colors ${
              dragOver ? "border-blue-400 bg-blue-50" : "border-gray-200 hover:border-blue-300 hover:bg-gray-50"
            }`}
          >
            <input ref={fileRef} type="file" accept=".csv,.txt" className="hidden"
              onChange={e => { const f = e.target.files?.[0]; if (f) processFile(f); }} />
            <Upload className="h-10 w-10 text-gray-400" />
            <div className="text-center">
              <p className="text-sm font-medium text-gray-700">Drop CSV statement here or click to browse</p>
              <p className="text-xs text-gray-400 mt-1">Download from your bank&apos;s net banking → Statements → Export as CSV</p>
            </div>
          </div>

          {error && (
            <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>
          )}
        </div>
      )}

      {step === "review" && (
        <div className="space-y-4">
          {/* Summary */}
          <div className="grid grid-cols-4 gap-4">
            <div className="bg-gray-50 rounded-xl p-4">
              <p className="text-xs text-gray-500 mb-1">File</p>
              <p className="text-sm font-semibold text-gray-900 truncate">{fileName}</p>
            </div>
            <div className="bg-gray-50 rounded-xl p-4">
              <p className="text-xs text-gray-500 mb-1">Transactions</p>
              <p className="text-sm font-semibold text-gray-900">{parsed.length}</p>
            </div>
            <div className="bg-red-50 rounded-xl p-4">
              <p className="text-xs text-red-500 mb-1">Total Debits</p>
              <p className="text-sm font-semibold text-red-700">{formatPaise(totalDebits)}</p>
            </div>
            <div className="bg-green-50 rounded-xl p-4">
              <p className="text-xs text-green-500 mb-1">Total Credits</p>
              <p className="text-sm font-semibold text-green-700">{formatPaise(totalCredits)}</p>
            </div>
          </div>

          {/* Transaction table */}
          <div className="border border-gray-200 rounded-xl overflow-hidden">
            <div className="max-h-96 overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="bg-gray-50 border-b border-gray-200 sticky top-0">
                  <tr>
                    <th className="text-left px-4 py-2.5 text-gray-600 font-medium">Date</th>
                    <th className="text-left px-4 py-2.5 text-gray-600 font-medium">Description</th>
                    <th className="text-right px-4 py-2.5 text-gray-600 font-medium">Debit</th>
                    <th className="text-right px-4 py-2.5 text-gray-600 font-medium">Credit</th>
                    <th className="text-right px-4 py-2.5 text-gray-600 font-medium">Balance</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {parsed.slice(0, 200).map((t, i) => (
                    <tr key={i} className="hover:bg-gray-50">
                      <td className="px-4 py-2 font-mono text-gray-600">{t.date}</td>
                      <td className="px-4 py-2 text-gray-800 max-w-xs truncate">{t.description}</td>
                      <td className="px-4 py-2 text-right font-mono text-red-600">
                        {t.debit_paise > 0 ? formatPaise(t.debit_paise) : "—"}
                      </td>
                      <td className="px-4 py-2 text-right font-mono text-green-600">
                        {t.credit_paise > 0 ? formatPaise(t.credit_paise) : "—"}
                      </td>
                      <td className="px-4 py-2 text-right font-mono text-gray-600">
                        {t.balance_paise > 0 ? formatPaise(t.balance_paise) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {parsed.length > 200 && (
              <div className="px-4 py-2 bg-amber-50 text-xs text-amber-700 border-t border-amber-100">
                Showing first 200 of {parsed.length} transactions
              </div>
            )}
          </div>

          {error && (
            <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>
          )}

          <div className="flex gap-3">
            <button onClick={() => { setStep("upload"); setParsed([]); }}
              className="flex-1 rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50">
              Back
            </button>
            <button onClick={handleImport} disabled={importing}
              className="flex-1 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60">
              {importing ? "Importing…" : `Import ${parsed.length} Transactions`}
            </button>
          </div>
        </div>
      )}

      {step === "done" && (
        <div className="text-center py-16">
          <div className="w-16 h-16 rounded-2xl bg-green-50 flex items-center justify-center mx-auto mb-4">
            <CheckCircle className="h-8 w-8 text-green-500" />
          </div>
          <h3 className="text-lg font-semibold text-gray-900 mb-2">
            {parsed.length} transactions imported
          </h3>
          <p className="text-sm text-gray-500 mb-6">
            Transactions are saved. Review and map them to accounts in the Ledger.
          </p>
          <div className="flex gap-3 justify-center">
            <button onClick={() => { setStep("upload"); setParsed([]); setFileName(""); }}
              className="flex items-center gap-2 rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
              <FileText size={15} /> Import Another
            </button>
            <a href="/accounting"
              className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">
              <Building2 size={15} /> Go to Accounting
            </a>
          </div>
        </div>
      )}

      {/* Help box */}
      {step === "upload" && (
        <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 text-sm text-blue-800">
          <p className="font-medium mb-1 flex items-center gap-1.5"><AlertCircle size={14} /> How to export from your bank</p>
          <ul className="text-xs space-y-0.5 text-blue-700 list-disc list-inside">
            <li><strong>HDFC:</strong> NetBanking → Account Summary → Download Statement → CSV</li>
            <li><strong>SBI:</strong> OnlineSBI → Account Statement → View → Download as CSV</li>
            <li><strong>ICICI:</strong> iMobile / NetBanking → Accounts → Statement → Download CSV</li>
            <li><strong>Axis:</strong> Internet Banking → Accounts → Account Statement → Export CSV</li>
          </ul>
        </div>
      )}
    </div>
  );
}
