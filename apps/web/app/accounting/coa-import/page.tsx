"use client";

import { useState, useRef } from "react";
import Link from "next/link";
import { ChevronLeft, Upload, CheckCircle, AlertCircle, X, FileText } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";

type AccountType = "Asset" | "Liability" | "Equity" | "Revenue" | "Expense";
const VALID_TYPES = new Set<AccountType>(["Asset", "Liability", "Equity", "Revenue", "Expense"]);

interface ImportRow {
  account_code: string;
  account_name: string;
  account_type: AccountType;
  account_subtype: string;
  parent_group: string;
  sub_group: string;
  tax_category: string;
  schedule_iii_mapping: string;
}

interface ImportError { row: number; message: string; }
interface ImportResult { inserted: number; skipped: number; errors: ImportError[]; }

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).maybeSingle();
  if (!data?.firm_id) throw new Error("No firm found");
  return data.firm_id as string;
}

function parseCSV(text: string): string[][] {
  return text.trim().split(/\r?\n/).map(line => {
    const cols: string[] = [];
    let cur = "";
    let inQ = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') { inQ = !inQ; }
      else if (ch === "," && !inQ) { cols.push(cur.trim()); cur = ""; }
      else { cur += ch; }
    }
    cols.push(cur.trim());
    return cols;
  });
}

// Normalise header names from Tally / Busy / Zoho / QuickBooks / generic
function normaliseHeader(h: string): string {
  const s = h.toLowerCase().replace(/[^a-z0-9]/g, "");
  if (s.includes("code") || s === "ledgerid") return "account_code";
  if (s.includes("name") || s === "ledgername" || s === "account") return "account_name";
  if (s.includes("type") || s === "accounttype" || s === "category") return "account_type";
  if (s.includes("subtype") || s === "subcategory" || s === "accountsubtype") return "account_subtype";
  if (s.includes("parentgroup") || s === "group" || s === "maingroup") return "parent_group";
  if (s.includes("subgroup") || s === "undergroup") return "sub_group";
  if (s.includes("tax") || s === "taxcategory" || s === "gsttax") return "tax_category";
  if (s.includes("schedule") || s.includes("s3") || s.includes("iii")) return "schedule_iii_mapping";
  return s;
}

function normaliseType(raw: string): AccountType | null {
  const s = raw.trim().toLowerCase();
  if (s.includes("asset")) return "Asset";
  if (s.includes("liabilit")) return "Liability";
  if (s.includes("equit") || s.includes("capital")) return "Equity";
  if (s.includes("reven") || s.includes("income") || s.includes("sales")) return "Revenue";
  if (s.includes("expens") || s.includes("cost")) return "Expense";
  const t = raw.trim() as AccountType;
  return VALID_TYPES.has(t) ? t : null;
}

export default function CoaImportPage() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [preview, setPreview] = useState<ImportRow[]>([]);
  const [parseErrors, setParseErrors] = useState<ImportError[]>([]);
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [step, setStep] = useState<"upload" | "preview" | "done">("upload");

  function handleFile(file: File) {
    setFileName(file.name);
    setResult(null);
    setStep("upload");
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target?.result as string;
      const rows = parseCSV(text);
      if (rows.length < 2) { setParseErrors([{ row: 0, message: "File is empty or has only headers" }]); return; }

      const rawHeaders = rows[0].map(normaliseHeader);
      const errors: ImportError[] = [];
      const parsed: ImportRow[] = [];

      for (let i = 1; i < rows.length; i++) {
        const cols = rows[i];
        if (cols.every(c => !c)) continue; // skip blank rows
        const obj: Record<string, string> = {};
        rawHeaders.forEach((h, idx) => { obj[h] = cols[idx] ?? ""; });

        if (!obj.account_code?.trim()) { errors.push({ row: i + 1, message: "Missing account code" }); continue; }
        if (!obj.account_name?.trim()) { errors.push({ row: i + 1, message: `Row ${i + 1}: Missing account name` }); continue; }

        const type = normaliseType(obj.account_type ?? "");
        if (!type) { errors.push({ row: i + 1, message: `Row ${i + 1}: Invalid account type "${obj.account_type}"` }); continue; }

        parsed.push({
          account_code: obj.account_code.trim(),
          account_name: obj.account_name.trim(),
          account_type: type,
          account_subtype: obj.account_subtype?.trim() ?? "",
          parent_group: obj.parent_group?.trim() ?? "",
          sub_group: obj.sub_group?.trim() ?? "",
          tax_category: obj.tax_category?.trim() ?? "",
          schedule_iii_mapping: obj.schedule_iii_mapping?.trim() ?? "",
        });
      }

      // Duplicate code check within file
      const codeSeen = new Map<string, number>();
      for (let i = 0; i < parsed.length; i++) {
        const code = parsed[i].account_code.toUpperCase();
        if (codeSeen.has(code)) {
          errors.push({ row: i + 2, message: `Duplicate account code "${code}" (also on row ${codeSeen.get(code)})` });
        } else {
          codeSeen.set(code, i + 2);
        }
      }

      setParseErrors(errors);
      setPreview(parsed);
      if (parsed.length > 0) setStep("preview");
    };
    reader.readAsText(file);
  }

  async function runImport() {
    if (!preview.length) return;
    setImporting(true);
    try {
      const fid = await getFirmId();
      const sb = getSupabaseClient();

      // Fetch existing codes
      const { data: existing } = await sb
        .from("chart_of_accounts")
        .select("account_code")
        .eq("firm_id", fid)
        .is("client_id", null);
      const existingCodes = new Set((existing ?? []).map(a => a.account_code.toUpperCase()));

      const toInsert = preview.filter(r => !existingCodes.has(r.account_code.toUpperCase()));
      const skipped = preview.length - toInsert.length;
      const errors: ImportError[] = [];

      if (toInsert.length > 0) {
        const { error: err } = await sb.from("chart_of_accounts").insert(
          toInsert.map(r => ({
            firm_id: fid,
            client_id: null,
            account_code: r.account_code,
            account_name: r.account_name,
            account_type: r.account_type,
            account_subtype: r.account_subtype || null,
            parent_group: r.parent_group || null,
            sub_group: r.sub_group || null,
            tax_category: r.tax_category || null,
            schedule_iii_mapping: r.schedule_iii_mapping || null,
            is_active: true,
          }))
        );
        if (err) errors.push({ row: 0, message: err.message });
      }

      setResult({ inserted: toInsert.length - errors.length, skipped, errors });
      setStep("done");
    } catch (e) {
      setResult({ inserted: 0, skipped: 0, errors: [{ row: 0, message: e instanceof Error ? e.message : "Import failed" }] });
      setStep("done");
    } finally {
      setImporting(false);
    }
  }

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-5">
      <div className="flex items-center gap-3">
        <Link href="/accounting/chart-of-accounts" className="text-[#94A3B8] hover:text-[#475569]">
          <ChevronLeft size={18} />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">Import Chart of Accounts</h1>
          <p className="text-xs text-[#64748B] mt-0.5">Import from Tally, Busy, Zoho Books, QuickBooks or any Excel/CSV</p>
        </div>
      </div>

      {/* Format guide */}
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 text-xs text-blue-800 space-y-1">
        <p className="font-semibold">Expected columns (CSV/Excel):</p>
        <p className="font-mono text-[10px] text-blue-700">account_code, account_name, account_type, account_subtype, parent_group, sub_group, tax_category, schedule_iii_mapping</p>
        <p className="mt-1">• <strong>account_type</strong> must be one of: Asset, Liability, Equity, Revenue, Expense</p>
        <p>• Tally exports (Ledger Name, Under, Account Type) are auto-detected</p>
        <p>• Duplicate codes are skipped — safe to re-import</p>
      </div>

      {/* Upload zone */}
      {step === "upload" && (
        <div
          onClick={() => fileRef.current?.click()}
          className="border-2 border-dashed border-[#CBD5E1] rounded-xl p-10 text-center cursor-pointer hover:border-blue-400 hover:bg-blue-50/30 transition-colors"
        >
          <Upload size={28} className="mx-auto text-[#94A3B8] mb-3" />
          <p className="text-sm font-medium text-[#334155]">Click to upload CSV or Excel file</p>
          <p className="text-xs text-[#94A3B8] mt-1">Supports .csv, .txt (Excel paste)</p>
          <input ref={fileRef} type="file" accept=".csv,.txt,.tsv" className="hidden" onChange={e => { if (e.target.files?.[0]) handleFile(e.target.files[0]); }} />
        </div>
      )}

      {/* Parse errors */}
      {parseErrors.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 space-y-1">
          <p className="text-xs font-semibold text-red-800">{parseErrors.length} validation error{parseErrors.length !== 1 ? "s" : ""} found</p>
          {parseErrors.slice(0, 10).map((e, i) => (
            <p key={i} className="text-xs text-red-700">Row {e.row}: {e.message}</p>
          ))}
          {parseErrors.length > 10 && <p className="text-xs text-red-500">…and {parseErrors.length - 10} more</p>}
        </div>
      )}

      {/* Preview */}
      {step === "preview" && preview.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-[#334155]">
              <FileText size={14} className="inline mr-1.5" />{fileName} — {preview.length} rows ready to import
            </p>
            <button onClick={() => { setStep("upload"); setPreview([]); setFileName(null); setParseErrors([]); }} className="text-xs text-[#94A3B8] hover:text-[#475569] flex items-center gap-1">
              <X size={12} /> Clear
            </button>
          </div>
          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden max-h-72 overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-[#F8FAFC]">
                <tr className="text-[10px] text-[#94A3B8] border-b border-[#F1F5F9]">
                  <th className="px-4 py-2 text-left font-medium w-16">Code</th>
                  <th className="px-3 py-2 text-left font-medium">Name</th>
                  <th className="px-3 py-2 text-left font-medium">Type</th>
                  <th className="px-3 py-2 text-left font-medium">Group</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {preview.map((row, i) => (
                  <tr key={i} className="hover:bg-[#F8FAFC]">
                    <td className="px-4 py-2 font-mono text-[10px] text-[#94A3B8]">{row.account_code}</td>
                    <td className="px-3 py-2 font-medium text-[#0F172A]">{row.account_name}</td>
                    <td className="px-3 py-2 text-[#64748B]">{row.account_type}</td>
                    <td className="px-3 py-2 text-[#64748B]">{row.parent_group || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex gap-2">
            <button onClick={() => { setStep("upload"); setPreview([]); setFileName(null); }} className="text-sm text-[#475569] border border-[#E2E8F0] px-4 py-2 rounded-md hover:bg-[#F8FAFC]">
              Cancel
            </button>
            <button onClick={runImport} disabled={importing} className="text-sm bg-blue-600 text-white px-5 py-2 rounded-md hover:bg-blue-700 disabled:opacity-50">
              {importing ? "Importing…" : `Import ${preview.length} Accounts`}
            </button>
          </div>
        </div>
      )}

      {/* Result */}
      {step === "done" && result && (
        <div className="space-y-4">
          <div className={`rounded-xl border p-5 ${result.errors.length === 0 ? "bg-green-50 border-green-200" : "bg-amber-50 border-amber-200"}`}>
            <div className="flex items-center gap-2 mb-3">
              {result.errors.length === 0
                ? <CheckCircle size={18} className="text-green-600" />
                : <AlertCircle size={18} className="text-amber-600" />
              }
              <span className="text-sm font-semibold text-[#334155]">Import Complete</span>
            </div>
            <div className="text-xs space-y-1 text-[#475569]">
              <p>✅ {result.inserted} account{result.inserted !== 1 ? "s" : ""} imported</p>
              {result.skipped > 0 && <p>⏭ {result.skipped} skipped (duplicate codes already exist)</p>}
              {result.errors.length > 0 && <p>❌ {result.errors.length} error{result.errors.length !== 1 ? "s" : ""}</p>}
            </div>
          </div>
          {result.errors.length > 0 && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-4 space-y-1">
              {result.errors.map((e, i) => <p key={i} className="text-xs text-red-700">{e.message}</p>)}
            </div>
          )}
          <div className="flex gap-2">
            <Link href="/accounting/chart-of-accounts" className="text-sm bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700">
              View Chart of Accounts
            </Link>
            <button onClick={() => { setStep("upload"); setPreview([]); setFileName(null); setResult(null); setParseErrors([]); }} className="text-sm text-[#475569] border border-[#E2E8F0] px-4 py-2 rounded-md hover:bg-[#F8FAFC]">
              Import Another File
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
