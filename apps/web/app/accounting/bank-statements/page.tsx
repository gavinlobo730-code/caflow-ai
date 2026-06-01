"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import Link from "next/link";
import { Building2, Upload, X, CheckCircle2, AlertCircle } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDate, formatPaise } from "@/lib/services/formatting";
import { getAllBankStatements, parseCSV, importBankStatement } from "@/lib/data/bankStatements";
import { getClients } from "@/lib/data/clients";
import type { BankStatement, ParsedTransaction } from "@/lib/data/bankStatements";
import type { Client } from "@/lib/types";

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  reviewed: "bg-blue-100 text-blue-700",
  posted: "bg-green-100 text-green-700",
};

function LoadingSkeleton() {
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-4 animate-pulse">
      <div className="h-8 bg-gray-200 rounded w-64" />
      <div className="h-64 bg-gray-100 rounded-xl" />
    </div>
  );
}

export default function BankStatementsPage() {
  // ── Statements list state ──────────────────────────────────────────────────
  const [statements, setStatements] = useState<BankStatement[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  // ── Upload form state ──────────────────────────────────────────────────────
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState("");
  const [bankName, setBankName] = useState("");
  const [accountNumber, setAccountNumber] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [parsedRows, setParsedRows] = useState<ParsedTransaction[] | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [importSuccess, setImportSuccess] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── Load initial data ──────────────────────────────────────────────────────
  const loadStatements = useCallback(() => {
    setListLoading(true);
    setListError(null);
    getAllBankStatements()
      .then(setStatements)
      .catch(err => setListError(err instanceof Error ? err.message : "Failed to load statements"))
      .finally(() => setListLoading(false));
  }, []);

  useEffect(() => {
    loadStatements();
    getClients()
      .then(setClients)
      .catch(() => undefined); // non-fatal
  }, [loadStatements]);

  // ── File handling ──────────────────────────────────────────────────────────
  function handleFile(file: File) {
    if (!file.name.endsWith(".csv")) {
      setImportError("Only .csv files are accepted");
      return;
    }
    setImportError(null);
    setImportSuccess(null);
    setFileName(file.name);
    const reader = new FileReader();
    reader.onload = e => {
      const text = e.target?.result as string;
      const rows = parseCSV(text);
      if (rows.length === 0) {
        setImportError("No transactions found in file. Check that it matches HDFC, SBI, ICICI, or Axis format.");
        setParsedRows(null);
      } else {
        setParsedRows(rows);
      }
    };
    reader.readAsText(file);
  }

  function onFileInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  }

  function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }

  function clearFile() {
    setParsedRows(null);
    setFileName(null);
    setImportError(null);
    setImportSuccess(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  // ── Import ─────────────────────────────────────────────────────────────────
  async function handleImport() {
    if (!clientId) { setImportError("Please select a client"); return; }
    if (!bankName.trim()) { setImportError("Please enter the bank name"); return; }
    if (!parsedRows || parsedRows.length === 0) { setImportError("No transactions to import"); return; }

    setImporting(true);
    setImportError(null);
    setImportSuccess(null);
    try {
      const stmt = await importBankStatement(clientId, bankName.trim(), accountNumber.trim(), parsedRows);
      setImportSuccess(`Imported ${stmt.row_count} transactions successfully.`);
      clearFile();
      setClientId("");
      setBankName("");
      setAccountNumber("");
      loadStatements();
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setImporting(false);
    }
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-8">
      {/* ── Page header ──────────────────────────────────────────────────── */}
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Bank Statements</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Import CSV bank statements, allocate transactions to accounts, and post to the ledger.
        </p>
      </div>

      {/* ── Upload section ───────────────────────────────────────────────── */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Import Bank Statement</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          {/* Row 1: Client + Bank name + Account number */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {/* Client dropdown */}
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-600">Client <span className="text-red-500">*</span></label>
              <select
                value={clientId}
                onChange={e => setClientId(e.target.value)}
                className="text-sm border border-gray-200 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">— Select client —</option>
                {clients.map(c => (
                  <option key={c.id} value={c.id}>{c.client_name}</option>
                ))}
              </select>
            </div>

            {/* Bank name */}
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-600">Bank Name <span className="text-red-500">*</span></label>
              <input
                type="text"
                placeholder="e.g. HDFC Bank"
                value={bankName}
                onChange={e => setBankName(e.target.value)}
                className="text-sm border border-gray-200 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            {/* Account number */}
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-600">Account Number</label>
              <input
                type="text"
                placeholder="e.g. XXXX1234"
                value={accountNumber}
                onChange={e => setAccountNumber(e.target.value)}
                className="text-sm border border-gray-200 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          {/* File upload area */}
          {!parsedRows ? (
            <div
              onDragOver={e => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`flex flex-col items-center justify-center gap-2 border-2 border-dashed rounded-xl py-10 cursor-pointer transition-colors ${
                dragOver ? "border-blue-400 bg-blue-50" : "border-gray-200 bg-gray-50 hover:bg-gray-100"
              }`}
            >
              <Upload size={24} className="text-gray-400" />
              <p className="text-sm font-medium text-gray-600">
                Drag & drop a CSV file, or <span className="text-blue-600">browse</span>
              </p>
              <p className="text-xs text-gray-400">Supports HDFC, SBI, ICICI, and Axis Bank formats</p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv"
                className="hidden"
                onChange={onFileInputChange}
              />
            </div>
          ) : (
            /* Preview panel */
            <div className="border border-gray-200 rounded-xl overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2.5 bg-gray-50 border-b border-gray-100">
                <span className="text-xs font-medium text-gray-700">
                  Preview — {fileName} · {parsedRows.length} transaction{parsedRows.length !== 1 ? "s" : ""} found
                </span>
                <button onClick={clearFile} className="text-gray-400 hover:text-gray-600">
                  <X size={15} />
                </button>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-gray-100 text-gray-400">
                      <th className="px-4 py-2 text-left font-semibold">Date</th>
                      <th className="px-3 py-2 text-left font-semibold">Description</th>
                      <th className="px-3 py-2 text-right font-semibold">Debit</th>
                      <th className="px-3 py-2 text-right font-semibold">Credit</th>
                      <th className="px-3 py-2 text-right font-semibold">Balance</th>
                      <th className="px-3 py-2 text-left font-semibold">Ref</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {parsedRows.slice(0, 5).map((row, i) => (
                      <tr key={i} className="hover:bg-gray-50">
                        <td className="px-4 py-2 text-gray-600 whitespace-nowrap">{row.date}</td>
                        <td className="px-3 py-2 text-gray-800 max-w-xs truncate" title={row.description}>{row.description}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-red-600">
                          {row.debit_paise > 0 ? formatPaise(row.debit_paise) : ""}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-green-600">
                          {row.credit_paise > 0 ? formatPaise(row.credit_paise) : ""}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-gray-500">
                          {row.balance_paise > 0 ? formatPaise(row.balance_paise) : ""}
                        </td>
                        <td className="px-3 py-2 text-gray-400 font-mono truncate max-w-[100px]">{row.reference_no || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {parsedRows.length > 5 && (
                  <p className="text-xs text-gray-400 px-4 py-2 border-t border-gray-100">
                    …and {parsedRows.length - 5} more rows
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Success / Error messages */}
          {importSuccess && (
            <div className="flex items-center gap-2 text-sm text-green-700 bg-green-50 rounded-lg px-4 py-3">
              <CheckCircle2 size={16} className="shrink-0" />
              {importSuccess}
            </div>
          )}
          {importError && (
            <div className="flex items-center gap-2 text-sm text-red-700 bg-red-50 rounded-lg px-4 py-3">
              <AlertCircle size={16} className="shrink-0" />
              {importError}
            </div>
          )}

          {/* Import button */}
          {parsedRows && parsedRows.length > 0 && (
            <div className="flex justify-end">
              <button
                onClick={handleImport}
                disabled={importing}
                className="text-sm bg-blue-600 text-white px-5 py-2 rounded-md hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {importing ? "Importing…" : `Import ${parsedRows.length} Transactions`}
              </button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Statements list ───────────────────────────────────────────────── */}
      {listLoading ? (
        <LoadingSkeleton />
      ) : listError ? (
        <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{listError}</div>
      ) : (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">
              {statements.length} statement{statements.length !== 1 ? "s" : ""}
            </CardTitle>
          </CardHeader>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 text-xs text-gray-400">
                  <th className="px-5 py-3 text-left font-semibold">Bank</th>
                  <th className="px-3 py-3 text-left font-semibold">Client</th>
                  <th className="px-3 py-3 text-left font-semibold">Period</th>
                  <th className="px-3 py-3 text-right font-semibold">Debits</th>
                  <th className="px-3 py-3 text-right font-semibold">Credits</th>
                  <th className="px-3 py-3 text-center font-semibold">Rows</th>
                  <th className="px-3 py-3 text-left font-semibold">Status</th>
                  <th className="px-5 py-3 text-left font-semibold">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {statements.map(s => (
                  <tr key={s.id} className="hover:bg-gray-50">
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-2">
                        <Building2 size={15} className="text-gray-400 shrink-0" />
                        <div>
                          <p className="text-sm font-medium text-gray-900">{s.bank_name}</p>
                          {s.account_number && (
                            <p className="text-xs text-gray-400 font-mono">{s.account_number}</p>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-3 text-xs text-gray-500">
                      {clients.find(c => c.id === s.client_id)?.client_name ?? s.client_id.slice(0, 8) + "…"}
                    </td>
                    <td className="px-3 py-3 text-xs text-gray-500 whitespace-nowrap">
                      {formatDate(s.statement_from)} – {formatDate(s.statement_to)}
                    </td>
                    <td className="px-3 py-3 text-sm text-right tabular-nums text-red-600">
                      {formatPaise(s.total_debits_paise)}
                    </td>
                    <td className="px-3 py-3 text-sm text-right tabular-nums text-green-600">
                      {formatPaise(s.total_credits_paise)}
                    </td>
                    <td className="px-3 py-3 text-xs text-center text-gray-500">{s.row_count}</td>
                    <td className="px-3 py-3">
                      <Badge className={`text-xs ${STATUS_COLORS[s.import_status] ?? "bg-gray-100 text-gray-600"}`}>
                        {s.import_status}
                      </Badge>
                    </td>
                    <td className="px-5 py-3">
                      <Link
                        href={`/accounting/bank-statements/${s.id}`}
                        className="text-xs text-blue-600 hover:underline"
                      >
                        Allocate →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {statements.length === 0 && (
              <div className="text-center py-12 text-sm text-gray-400">
                No bank statements imported yet. Upload one above to get started.
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
