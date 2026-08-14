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
import { parseCSV, buildParsedAccounts, type ParsedAccount, type ColumnMap } from "@/lib/accounting/trialBalanceParser";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { useClientPicker } from "@/lib/workspace/useClientPicker";
import { api } from "@/lib/api";

const SAMPLE_CSV = `Account Name,Account Code,Debit Balance,Credit Balance,Account Type
Cash in Hand,1001,50000,0,Asset
Bank - HDFC Current,1002,250000,0,Asset
Sundry Debtors,1003,180000,0,Asset
Capital Account,3001,0,500000,Equity
Sales Account,4001,0,450000,Revenue
Purchase Account,5001,300000,0,Expense`;

export default function TrialBalanceImportPage() {
  // A trial balance belongs to ONE client — it becomes that client's opening
  // journal. The old firm-wide import had no client at all, which is part of
  // why it could never have posted anything meaningful.
  const { clients, clientId: selectedClientId, setClientId: setSelectedClientId } = useClientPicker();
  const [openingDate, setOpeningDate] = useState("");
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  const [rawRows, setRawRows] = useState<string[][]>([]);
  const [headers, setHeaders] = useState<string[]>([]);
  const [colMap, setColMap] = useState<ColumnMap>({ nameCol: 0, codeCol: -1, drCol: 2, crCol: 3, typeCol: -1 });
  const [accounts, setAccounts] = useState<ParsedAccount[]>([]);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<{
    posted?: boolean; reason?: string; journal_entry_id?: string; opening_date?: string;
    accounts?: number; adjustment_lines?: number; total_debit_paise?: number;
  } | null>(null);
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

  function buildPreview() {
    setAccounts(buildParsedAccounts(rawRows, colMap));
    setStep(3);
  }

  function updateType(i: number, t: string) {
    setAccounts(a => a.map((acc, idx) => idx === i ? { ...acc, typeOverride: t } : acc));
  }

  const totalDr = accounts.reduce((s, a) => s + a.dr_paise, 0);
  const totalCr = accounts.reduce((s, a) => s + a.cr_paise, 0);
  const diff = totalDr - totalCr;

  async function runImport() {
    if (!selectedClientId) {
      setErr("Select the client this trial balance belongs to.");
      return;
    }
    setImporting(true);
    setErr("");
    try {
      // The backend posts ONE balanced opening journal for these lines. It is
      // the only thing that makes a trial balance real — the reporting engine
      // reads journals, not account-master fields — and it refuses an
      // unbalanced trial balance rather than posting lopsided entries.
      const resp = await api.accounting.importTrialBalance({
        client_id: selectedClientId,
        opening_date: openingDate || null,
        rows: accounts.map(acc => ({
          account_name: acc.account_name,
          account_type: acc.typeOverride ?? acc.account_type,
          debit_paise: acc.dr_paise,
          credit_paise: acc.cr_paise,
          account_code: acc.account_code || null,
        })),
      });
      setImportResult(resp.data);
      setStep(4);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error during import. Please try again.");
    }
    setImporting(false);
  }

  return (
    <div className="min-h-screen bg-[#F8FAFC] p-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-2xl font-bold text-[#0F172A] mb-2">Trial Balance Import</h1>
        <p className="text-sm text-[#64748B] mb-6">Universal importer — Tally, Busy, QuickBooks, Zoho, Excel (export as CSV)</p>

        {/* A trial balance is one client's opening position and posts to that
            client's ledger, so the client is chosen before anything else. */}
        <Card className="mb-6">
          <CardContent className="pt-5 pb-5 flex flex-wrap items-end gap-4">
            <div className="flex-1 min-w-[220px]">
              <label className="block text-xs font-medium text-[#475569] mb-1">Client *</label>
              <ClientLookup clients={clients} value={selectedClientId} onChange={setSelectedClientId} />
            </div>
            <div className="min-w-[180px]">
              <label className="block text-xs font-medium text-[#475569] mb-1">Opening date</label>
              <input
                type="date"
                value={openingDate}
                onChange={e => setOpeningDate(e.target.value)}
                className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm"
              />
              <p className="text-[11px] text-[#94A3B8] mt-1">
                Defaults to the client&apos;s financial-year start (1 April).
              </p>
            </div>
          </CardContent>
        </Card>

        {selectedClientId && (
        <>
        {/* Step indicator */}
        <div className="flex items-center gap-2 mb-8 text-sm">
          {["Upload", "Map Columns", "Review", "Import"].map((s, i) => (
            <div key={s} className="flex items-center gap-2">
              <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${step > i + 1 ? "bg-green-500 text-white" : step === i + 1 ? "bg-blue-500 text-white" : "bg-white/[0.08] text-[#64748B]"}`}>
                {step > i + 1 ? <CheckCircle size={14} /> : i + 1}
              </div>
              <span className={step === i + 1 ? "font-semibold text-[#0F172A]" : "text-[#94A3B8]"}>{s}</span>
              {i < 3 && <ChevronRight size={14} className="text-[#CBD5E1]" />}
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
                  className="border-2 border-dashed border-[#E2E8F0] rounded-xl p-12 text-center cursor-pointer hover:border-blue-500/20 hover:bg-blue-500/[0.08] transition-colors"
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
                  <Upload size={32} className="mx-auto mb-3 text-[#94A3B8]" />
                  <p className="font-medium text-[#334155] mb-1">Drop your CSV here or click to browse</p>
                  <p className="text-sm text-[#94A3B8]">Supports: Tally CSV, Busy CSV, QuickBooks CSV, Zoho CSV</p>
                  <p className="text-xs text-[#94A3B8] mt-1">Excel: File &rarr; Save As &rarr; CSV</p>
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
                      <label className="block text-xs font-medium text-[#334155] mb-1">{label}</label>
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
                  <h3 className="text-sm font-medium text-[#334155] mb-2">Preview (first 5 rows)</h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs border-collapse">
                      <thead>
                        <tr className="bg-[#F1F5F9]">
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
                  <p className="text-xs text-[#64748B] mb-1">Total Debit</p>
                  <p className="text-lg font-bold text-[#0F172A]">Rs {(totalDr / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="pt-4">
                  <p className="text-xs text-[#64748B] mb-1">Total Credit</p>
                  <p className="text-lg font-bold text-[#0F172A]">Rs {(totalCr / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="pt-4">
                  <p className="text-xs text-[#64748B] mb-1">Difference</p>
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
                      <tr className="border-b text-xs font-medium text-[#64748B] uppercase">
                        <th className="text-left py-2 px-4">Account Name</th>
                        <th className="text-left py-2 px-4">Code</th>
                        <th className="py-2 px-4">Type</th>
                        <th className="text-right py-2 px-4">Dr Balance</th>
                        <th className="text-right py-2 px-4">Cr Balance</th>
                      </tr>
                    </thead>
                    <tbody>
                      {accounts.map((acc, i) => (
                        <tr key={i} className="border-b hover:bg-[#F8FAFC]">
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
                <h2 className="text-xl font-bold text-[#0F172A] mb-2">
                  {importResult.posted ? "Posted to the ledger" : "Already up to date"}
                </h2>
                {importResult.posted ? (
                  <>
                    <p className="text-[#475569] mb-1">
                      {importResult.accounts} accounts, posted as one balanced opening
                      journal of {importResult.adjustment_lines} line
                      {importResult.adjustment_lines === 1 ? "" : "s"}
                      {importResult.opening_date ? ` dated ${importResult.opening_date}` : ""}.
                    </p>
                    <p className="text-xs text-[#94A3B8]">
                      These balances are now in the General Ledger, so the trial
                      balance and balance sheet reflect them.
                    </p>
                  </>
                ) : (
                  <p className="text-[#475569] mb-1">
                    {importResult.reason ?? "Nothing to post."} Re-importing the same
                    trial balance does not duplicate it.
                  </p>
                )}
                <div className="flex items-center justify-center gap-2 mt-6">
                  <Link href="/reports/trial-balance">
                    <Button className="flex items-center gap-1.5">
                      <LinkIcon size={14} />View Trial Balance
                    </Button>
                  </Link>
                  <Link href="/accounting/account-groups">
                    <Button variant="outline" className="flex items-center gap-1.5">
                      <LinkIcon size={14} />Chart of Accounts
                    </Button>
                  </Link>
                </div>
              </CardContent>
            </Card>
          </div>
        )}
        </>
        )}
      </div>
    </div>
  );
}
