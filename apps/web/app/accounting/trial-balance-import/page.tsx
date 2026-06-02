"use client";

/**
 * Trial Balance Import — Universal importer for Tally, Busy, QuickBooks, Zoho, Excel exports.
 * Parses CSV client-side (no external library). All balances in integer paise.
 */

import { useState, useRef } from "react";
import { Upload, ChevronRight, CheckCircle, AlertCircle, Link as LinkIcon } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";

// ── CSV parser (no external library) ─────────────────────────────────────

function parseCSV(text: string): string[][] {
  const rows: string[][] = [];
  let i = 0;
  while (i < text.length) {
    const row: string[] = [];
    while (i < text.length && text[i] !== "\n" && text[i] !== "\r") {
      let field = "";
      if (text[i] === '"') {
        i++; // skip opening quote
        while (i < text.length) {
          if (text[i] === '"' && text[i + 1] === '"') { field += '"'; i += 2; }
          else if (text[i] === '"') { i++; break; }
          else { field += text[i++]; }
        }
      } else {
        while (i < text.length && text[i] !== "," && text[i] !== "\n" && text[i] !== "\r") {
          field += text[i++];
        }
      }
      row.push(field.trim());
      if (i < text.length && text[i] === ",") i++;
    }
    if (text[i] === "\r") i++;
    if (text[i] === "\n") i++;
    if (row.length > 0 && !(row.length === 1 && row[0] === "")) rows.push(row);
  }
  return rows;
}

// ── Account type auto-detection ───────────────────────────────────────────

function detectType(name: string): string {
  const n = name.toLowerCase();
  if (/sales|revenue|income|turnover/.test(n)) return "revenue";
  if (/purchase|cogs|cost of/.test(n)) return "expense";
  if (/expense|depreciation|salary|rent|utilities/.test(n)) return "expense";
  if (/cash|bank|receivable|debtor|advances paid/.test(n)) return "asset";
  if (/fixed asset|plant|machinery|building|vehicle|furniture/.test(n)) return "asset";
  if (/payable|creditor|loan payable|advances received/.test(n)) return "liability";
  if (/capital|reserve|retained earnings|equity/.test(n)) return "equity";
  return "asset";
}

// ── Types ──────────────────────────────────────────────────────────────────

type ParsedAccount = {
  account_name: string;
  account_code: string;
  account_type: string;
  dr_balance: string; // raw string from CSV
  cr_balance: string;
  dr_paise: number;
  cr_paise: number;
  typeOverride?: string;
};

type ColumnMap = {
  nameCol: number;
  codeCol: number;
  drCol: number;
  crCol: number;
  typeCol: number;
};

const SAMPLE_CSV = `Account Name,Account Code,Debit Balance,Credit Balance,Account Type
Cash in Hand,1001,50000,0,Asset
Bank - HDFC Current,1002,250000,0,Asset
Sundry Debtors,1003,180000,0,Asset
Capital Account,3001,0,500000,Equity
Sales Account,4001,0,450000,Revenue
Purchase Account,5001,300000,0,Expense`;

const MIGRATION_SQL = `-- Add opening balance columns if not present:
ALTER TABLE chart_of_accounts
  ADD COLUMN IF NOT EXISTS opening_balance_dr_paise BIGINT DEFAULT 0,
  ADD COLUMN IF NOT EXISTS opening_balance_cr_paise BIGINT DEFAULT 0;`;

export default function TrialBalanceImportPage() {
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  const [rawRows, setRawRows] = useState<string[][]>([]);
  const [headers, setHeaders] = useState<string[]>([]);
  const [colMap, setColMap] = useState<ColumnMap>({ nameCol: 0, codeCol: -1, drCol: 2, crCol: 3, typeCol: -1 });
  const [accounts, setAccounts] = useState<ParsedAccount[]>([]);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<{ success: number; errors: number } | null>(null);
  const [migrationNeeded, setMigrationNeeded] = useState(false);
  const [err, setErr] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.name.endsWith(".xlsx") || file.name.endsWith(".xls")) {
      setErr("Excel files are not supported. Please export as CSV from Excel (File > Save As > CSV).");
      return;
    }
    setErr("");
    const reader = new FileReader();
    reader.onload = ev => {
      const text = ev.target?.result as string;
      const rows = parseCSV(text);
      if (rows.length < 2) { setErr("CSV appears empty or has only headers."); return; }
      setHeaders(rows[0]);
      setRawRows(rows.slice(1));
      // Auto-detect columns
      const hdrs = rows[0].map(h => h.toLowerCase());
      const nameIdx = hdrs.findIndex(h => h.includes("name") || h.includes("account"));
      const codeIdx = hdrs.findIndex(h => h.includes("code"));
      const drIdx = hdrs.findIndex(h => h.includes("debit") || h === "dr");
      const crIdx = hdrs.findIndex(h => h.includes("credit") || h === "cr");
      const typeIdx = hdrs.findIndex(h => h.includes("type"));
      setColMap({
        nameCol: nameIdx >= 0 ? nameIdx : 0,
        codeCol: codeIdx >= 0 ? codeIdx : -1,
        drCol: drIdx >= 0 ? drIdx : 2,
        crCol: crIdx >= 0 ? crIdx : 3,
        typeCol: typeIdx >= 0 ? typeIdx : -1,
      });
      setStep(2);
    };
    reader.readAsText(file);
  }

  function parseAmount(s: string): number {
    // Remove commas, Rs, spaces, handle negative in parens
    const clean = s.replace(/[,\s₹Rs]/g, "").replace(/\((.+)\)/, "-$1");
    const n = parseFloat(clean) || 0;
    return Math.round(Math.abs(n) * 100); // paise, always positive
  }

  function buildPreview() {
    const parsed: ParsedAccount[] = rawRows.map(row => {
      const name = row[colMap.nameCol] ?? "";
      const code = colMap.codeCol >= 0 ? (row[colMap.codeCol] ?? "") : "";
      const drRaw = colMap.drCol >= 0 ? (row[colMap.drCol] ?? "0") : "0";
      const crRaw = colMap.crCol >= 0 ? (row[colMap.crCol] ?? "0") : "0";
      const typeRaw = colMap.typeCol >= 0 ? (row[colMap.typeCol] ?? "") : "";
      return {
        account_name: name,
        account_code: code,
        account_type: typeRaw ? typeRaw.toLowerCase() : detectType(name),
        dr_balance: drRaw,
        cr_balance: crRaw,
        dr_paise: parseAmount(drRaw),
        cr_paise: parseAmount(crRaw),
      };
    }).filter(a => a.account_name.trim() !== "");
    setAccounts(parsed);
    setStep(3);
  }

  function updateType(i: number, t: string) {
    setAccounts(a => a.map((acc, idx) => idx === i ? { ...acc, typeOverride: t } : acc));
  }

  const totalDr = accounts.reduce((s, a) => s + a.dr_paise, 0);
  const totalCr = accounts.reduce((s, a) => s + a.cr_paise, 0);
  const diff = totalDr - totalCr;

  async function runImport() {
    setImporting(true);
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();
      let success = 0;
      let errors = 0;

      for (const acc of accounts) {
        const finalType = acc.typeOverride ?? acc.account_type;
        const { error } = await sb.from("chart_of_accounts").upsert({
          firm_id: firmId,
          account_name: acc.account_name,
          account_code: acc.account_code || null,
          account_type: finalType,
          opening_balance_dr_paise: acc.dr_paise,
          opening_balance_cr_paise: acc.cr_paise,
        }, { onConflict: "firm_id,account_name" });

        if (error) {
          if (error.message.includes("opening_balance_dr_paise")) {
            setMigrationNeeded(true);
          }
          errors++;
        } else {
          success++;
        }
      }

      setImportResult({ success, errors });
      setStep(4);
    } catch {
      setErr("Error during import. Please try again.");
    }
    setImporting(false);
  }

  return (
    <div className="min-h-screen bg-gray-50 p-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-2xl font-bold text-gray-900 mb-2">Trial Balance Import</h1>
        <p className="text-sm text-gray-500 mb-6">Universal importer — Tally, Busy, QuickBooks, Zoho, Excel (export as CSV)</p>

        {/* Step indicator */}
        <div className="flex items-center gap-2 mb-8 text-sm">
          {["Upload", "Map Columns", "Review", "Import"].map((s, i) => (
            <div key={s} className="flex items-center gap-2">
              <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${step > i + 1 ? "bg-green-500 text-white" : step === i + 1 ? "bg-indigo-600 text-white" : "bg-gray-200 text-gray-500"}`}>
                {step > i + 1 ? <CheckCircle size={14} /> : i + 1}
              </div>
              <span className={step === i + 1 ? "font-semibold text-gray-900" : "text-gray-400"}>{s}</span>
              {i < 3 && <ChevronRight size={14} className="text-gray-300" />}
            </div>
          ))}
        </div>

        {err && (
          <Card className="mb-4 border-red-200 bg-red-50">
            <CardContent className="pt-4 flex gap-2">
              <AlertCircle size={16} className="text-red-600 shrink-0 mt-0.5" />
              <p className="text-sm text-red-700">{err}</p>
            </CardContent>
          </Card>
        )}

        {/* STEP 1 — Upload */}
        {step === 1 && (
          <div className="space-y-4">
            <Card>
              <CardContent className="pt-6">
                <div
                  className="border-2 border-dashed border-gray-200 rounded-xl p-12 text-center cursor-pointer hover:border-indigo-400 hover:bg-indigo-50 transition-colors"
                  onClick={() => fileRef.current?.click()}
                  onDragOver={e => { e.preventDefault(); }}
                  onDrop={e => {
                    e.preventDefault();
                    const file = e.dataTransfer.files[0];
                    if (file) {
                      const fake = { target: { files: [file] } } as unknown as React.ChangeEvent<HTMLInputElement>;
                      handleFile(fake);
                    }
                  }}
                >
                  <Upload size={32} className="mx-auto mb-3 text-gray-400" />
                  <p className="font-medium text-gray-700 mb-1">Drop your CSV here or click to browse</p>
                  <p className="text-sm text-gray-400">Supports: Tally CSV, Busy CSV, QuickBooks CSV, Zoho CSV</p>
                  <p className="text-xs text-gray-400 mt-1">Excel: File &rarr; Save As &rarr; CSV</p>
                </div>
                <input ref={fileRef} type="file" accept=".csv,.txt" className="hidden" onChange={handleFile} />
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle className="text-sm">Sample CSV Format</CardTitle></CardHeader>
              <CardContent>
                <pre className="bg-gray-900 text-green-400 p-3 rounded text-xs overflow-auto">{SAMPLE_CSV}</pre>
              </CardContent>
            </Card>
          </div>
        )}

        {/* STEP 2 — Map Columns */}
        {step === 2 && (
          <div className="space-y-4">
            <Card>
              <CardHeader><CardTitle>Map Columns</CardTitle></CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
                  {([
                    { label: "Account Name *", key: "nameCol" },
                    { label: "Account Code (optional)", key: "codeCol" },
                    { label: "Debit Balance *", key: "drCol" },
                    { label: "Credit Balance *", key: "crCol" },
                    { label: "Account Type (optional)", key: "typeCol" },
                  ] as { label: string; key: keyof ColumnMap }[]).map(({ label, key }) => (
                    <div key={key}>
                      <label className="block text-xs font-medium text-gray-700 mb-1">{label}</label>
                      <select
                        className="w-full border rounded-lg px-3 py-2 text-sm"
                        value={colMap[key]}
                        onChange={e => setColMap(m => ({ ...m, [key]: parseInt(e.target.value) }))}
                      >
                        <option value={-1}>— None —</option>
                        {headers.map((h, i) => <option key={i} value={i}>{h || `Column ${i + 1}`}</option>)}
                      </select>
                    </div>
                  ))}
                </div>

                <div>
                  <h3 className="text-sm font-medium text-gray-700 mb-2">Preview (first 5 rows)</h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs border-collapse">
                      <thead>
                        <tr className="bg-gray-100">
                          {headers.map((h, i) => <th key={i} className="border px-2 py-1 text-left">{h || `Col ${i + 1}`}</th>)}
                        </tr>
                      </thead>
                      <tbody>
                        {rawRows.slice(0, 5).map((row, ri) => (
                          <tr key={ri}>
                            {row.map((cell, ci) => <td key={ci} className="border px-2 py-1">{cell}</td>)}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div className="flex gap-2 mt-4">
                  <Button variant="outline" onClick={() => setStep(1)}>Back</Button>
                  <Button onClick={buildPreview}>Next: Review</Button>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* STEP 3 — Review */}
        {step === 3 && (
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-4">
              <Card>
                <CardContent className="pt-4">
                  <p className="text-xs text-gray-500 mb-1">Total Debit</p>
                  <p className="text-lg font-bold text-gray-900">Rs {(totalDr / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="pt-4">
                  <p className="text-xs text-gray-500 mb-1">Total Credit</p>
                  <p className="text-lg font-bold text-gray-900">Rs {(totalCr / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="pt-4">
                  <p className="text-xs text-gray-500 mb-1">Difference</p>
                  <p className={`text-lg font-bold ${Math.abs(diff) < 1 ? "text-green-700" : "text-red-600"}`}>
                    Rs {(diff / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                    {Math.abs(diff) < 1 && " ✓"}
                  </p>
                </CardContent>
              </Card>
            </div>

            <Card>
              <CardHeader>
                <CardTitle>{accounts.length} Accounts to Import</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <div className="overflow-x-auto max-h-96 overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead className="sticky top-0 bg-white">
                      <tr className="border-b text-xs font-medium text-gray-500 uppercase">
                        <th className="text-left py-2 px-4">Account Name</th>
                        <th className="text-left py-2 px-4">Code</th>
                        <th className="py-2 px-4">Type</th>
                        <th className="text-right py-2 px-4">Dr Balance</th>
                        <th className="text-right py-2 px-4">Cr Balance</th>
                      </tr>
                    </thead>
                    <tbody>
                      {accounts.map((acc, i) => (
                        <tr key={i} className="border-b hover:bg-gray-50">
                          <td className="py-2 px-4 font-medium">{acc.account_name}</td>
                          <td className="py-2 px-4 font-mono text-xs">{acc.account_code || "—"}</td>
                          <td className="py-2 px-4">
                            <select
                              className="border rounded px-1 py-0.5 text-xs"
                              value={acc.typeOverride ?? acc.account_type}
                              onChange={e => updateType(i, e.target.value)}
                            >
                              <option value="asset">Asset</option>
                              <option value="liability">Liability</option>
                              <option value="equity">Equity</option>
                              <option value="revenue">Revenue</option>
                              <option value="expense">Expense</option>
                            </select>
                          </td>
                          <td className="py-2 px-4 text-right font-mono text-xs">
                            {acc.dr_paise > 0 ? `Rs ${(acc.dr_paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}` : "—"}
                          </td>
                          <td className="py-2 px-4 text-right font-mono text-xs">
                            {acc.cr_paise > 0 ? `Rs ${(acc.cr_paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}` : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>

            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setStep(2)}>Back</Button>
              <Button onClick={runImport} disabled={importing || accounts.length === 0}>
                {importing ? "Importing..." : `Import ${accounts.length} Accounts`}
              </Button>
            </div>
          </div>
        )}

        {/* STEP 4 — Done */}
        {step === 4 && importResult && (
          <div className="space-y-4">
            <Card>
              <CardContent className="pt-8 pb-8 text-center">
                <CheckCircle size={48} className="mx-auto mb-4 text-green-500" />
                <h2 className="text-xl font-bold text-gray-900 mb-2">Import Complete</h2>
                <p className="text-gray-600 mb-1">{importResult.success} accounts imported successfully.</p>
                {importResult.errors > 0 && (
                  <p className="text-red-600">{importResult.errors} errors encountered.</p>
                )}
                <Link href="/accounting/chart-of-accounts">
                  <Button className="mt-6 flex items-center gap-1.5">
                    <LinkIcon size={14} />View Chart of Accounts
                  </Button>
                </Link>
              </CardContent>
            </Card>

            {migrationNeeded && (
              <Card className="border-amber-200 bg-amber-50">
                <CardHeader>
                  <CardTitle className="text-sm flex items-center gap-2">
                    <AlertCircle size={16} className="text-amber-600" />
                    Migration Required
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-amber-800 mb-3">
                    The <code>opening_balance_dr_paise</code> and <code>opening_balance_cr_paise</code> columns
                    are missing from <code>chart_of_accounts</code>. Run this SQL to add them:
                  </p>
                  <pre className="bg-gray-900 text-green-400 p-3 rounded text-xs overflow-auto">{MIGRATION_SQL}</pre>
                </CardContent>
              </Card>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
