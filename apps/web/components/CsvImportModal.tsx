"use client";

/**
 * Generic CSV import modal with:
 * - Downloadable template
 * - File upload + parse
 * - Row-level validation
 * - Preview before import
 * - Bulk insert via callback
 */

import { useState, useRef } from "react";
import { X, Download, Upload, AlertCircle, CheckCircle, Loader } from "lucide-react";
import * as XLSX from "xlsx";

export interface CsvColumn {
  key: string;          // CSV header name (must match template)
  label: string;        // display label
  required: boolean;
  hint?: string;        // shown in template header row comment
}

export interface ImportRow {
  [key: string]: string;
}

export interface ParsedRow {
  index: number;
  data: ImportRow;
  errors: string[];     // field-level validation errors
}

interface Props {
  title: string;
  columns: CsvColumn[];
  templateFilename: string;
  onImport: (rows: ImportRow[]) => Promise<{ imported: number; errors: string[] }>;
  onClose: () => void;
  /** Optional extra validation per row, returns error strings */
  validateRow?: (row: ImportRow) => string[];
}

function parseCsvLine(line: string): string[] {
  const result: string[] = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') { cur += '"'; i++; }
      else inQuotes = !inQuotes;
    } else if (ch === "," && !inQuotes) {
      result.push(cur.trim());
      cur = "";
    } else {
      cur += ch;
    }
  }
  result.push(cur.trim());
  return result;
}

function parseCsv(text: string, columns: CsvColumn[]): ParsedRow[] {
  const lines = text.split(/\r?\n/).filter(l => l.trim());
  if (lines.length < 2) return [];

  // First non-comment line is header
  const headerLine = lines.find(l => !l.startsWith("#")) ?? lines[0];
  const headerIdx = lines.indexOf(headerLine);
  const headers = parseCsvLine(headerLine).map(h => h.toLowerCase().trim());

  const rows: ParsedRow[] = [];
  for (let i = headerIdx + 1; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim() || line.startsWith("#")) continue;
    const values = parseCsvLine(line);
    const data: ImportRow = {};
    headers.forEach((h, idx) => { data[h] = values[idx] ?? ""; });

    const errors: string[] = [];
    for (const col of columns) {
      if (col.required && !data[col.key.toLowerCase()]) {
        errors.push(`"${col.label}" is required`);
      }
    }

    rows.push({ index: i - headerIdx, data, errors });
  }
  return rows;
}

export default function CsvImportModal({ title, columns, templateFilename, onImport, onClose, validateRow }: Props) {
  const [step, setStep] = useState<"upload" | "preview" | "importing" | "done">("upload");
  const [rows, setRows] = useState<ParsedRow[]>([]);
  const [result, setResult] = useState<{ imported: number; errors: string[] } | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  function downloadTemplate() {
    // Build worksheet: row 1 = headers, row 2 = hints, row 3 = example placeholder
    const headerRow = columns.map(c => c.key);
    const hintRow = columns.map(c => c.hint ?? (c.required ? "REQUIRED" : "optional"));
    const exampleRow = columns.map(c => c.hint ?? "");

    const ws = XLSX.utils.aoa_to_sheet([headerRow, hintRow, exampleRow]);

    // Style header row bold + blue fill using column widths
    ws["!cols"] = columns.map(() => ({ wch: 22 }));

    // Mark required columns with a note in the hint row
    columns.forEach((col, i) => {
      const cell = ws[XLSX.utils.encode_cell({ r: 0, c: i })];
      if (cell) {
        cell.s = {
          font: { bold: true, color: { rgb: col.required ? "C00000" : "1F3864" } },
          fill: { fgColor: { rgb: col.required ? "FFE6E6" : "DCE6F1" } },
        };
      }
    });

    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Template");

    // Add an Instructions sheet
    const instructions = [
      ["PracticeSync AI — Import Template"],
      [""],
      ["INSTRUCTIONS:"],
      ["1. Do NOT modify the header row (Row 1)"],
      ["2. Delete Row 2 (hints) before uploading"],
      ["3. Enter your data from Row 3 onwards"],
      ["4. Save as CSV (comma-separated) before uploading"],
      [""],
      ["Column Guide:"],
      ...columns.map(c => [c.key, c.required ? "REQUIRED" : "optional", c.hint ?? c.label]),
    ];
    const wsInfo = XLSX.utils.aoa_to_sheet(instructions);
    wsInfo["!cols"] = [{ wch: 28 }, { wch: 12 }, { wch: 50 }];
    XLSX.utils.book_append_sheet(wb, wsInfo, "Instructions");

    XLSX.writeFile(wb, templateFilename.replace(".csv", ".xlsx"));
  }

  function handleFile(file: File) {
    setFileError(null);
    if (!file.name.endsWith(".csv")) {
      setFileError("Please upload a .csv file");
      return;
    }
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target?.result as string;
      let parsed = parseCsv(text, columns);
      // Run custom validation if provided
      if (validateRow) {
        parsed = parsed.map(r => ({
          ...r,
          errors: [...r.errors, ...validateRow(r.data)],
        }));
      }
      if (parsed.length === 0) {
        setFileError("No data rows found. Make sure your file has at least one data row after the header.");
        return;
      }
      setRows(parsed);
      setStep("preview");
    };
    reader.readAsText(file);
  }

  async function handleImport() {
    const validRows = rows.filter(r => r.errors.length === 0).map(r => r.data);
    if (validRows.length === 0) return;
    setStep("importing");
    const res = await onImport(validRows);
    setResult(res);
    setStep("done");
  }

  const validCount = rows.filter(r => r.errors.length === 0).length;
  const errorCount = rows.filter(r => r.errors.length > 0).length;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-3xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#F1F5F9]">
          <h2 className="text-base font-semibold text-[#0F172A]">{title}</h2>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">

          {/* Step 1 — Upload */}
          {step === "upload" && (
            <div className="space-y-4">
              {/* Template download */}
              <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 flex items-start gap-3">
                <Download className="w-4 h-4 text-blue-600 shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="text-sm font-medium text-blue-900">Step 1 — Download the template</p>
                  <p className="text-xs text-blue-600 mt-0.5">Fill in your data and save as CSV. Required fields are marked.</p>
                  <button
                    onClick={downloadTemplate}
                    className="mt-2 text-xs px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
                  >
                    Download Template CSV
                  </button>
                </div>
              </div>

              {/* Template column reference */}
              <div className="bg-[#F8FAFC] rounded-xl border border-[#F1F5F9] overflow-hidden">
                <div className="px-4 py-2 border-b border-[#F1F5F9]">
                  <p className="text-xs font-semibold text-[#64748B] uppercase tracking-wide">Template Columns</p>
                </div>
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-[#F1F5F9]">
                      <th className="px-4 py-2 text-left font-medium text-[#64748B]">Column</th>
                      <th className="px-4 py-2 text-left font-medium text-[#64748B]">Required</th>
                      <th className="px-4 py-2 text-left font-medium text-[#64748B]">Notes</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.03]">
                    {columns.map(col => (
                      <tr key={col.key}>
                        <td className="px-4 py-2 font-mono text-[#0F172A]">{col.key}</td>
                        <td className="px-4 py-2">
                          {col.required
                            ? <span className="text-red-600 font-medium">Required</span>
                            : <span className="text-[#94A3B8]">Optional</span>}
                        </td>
                        <td className="px-4 py-2 text-[#64748B]">{col.hint ?? col.label}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Upload area */}
              <div>
                <p className="text-sm font-medium text-[#334155] mb-2">Step 2 — Upload your filled CSV</p>
                <div
                  onClick={() => fileRef.current?.click()}
                  onDragOver={e => e.preventDefault()}
                  onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) handleFile(f); }}
                  className="border-2 border-dashed border-[#E2E8F0] rounded-xl p-8 text-center cursor-pointer hover:border-blue-300 hover:bg-blue-50/30 transition-colors"
                >
                  <Upload className="w-8 h-8 text-[#CBD5E1] mx-auto mb-2" />
                  <p className="text-sm text-[#475569]">Click to browse or drag & drop your CSV file</p>
                  <p className="text-xs text-[#94A3B8] mt-1">Only .csv files are supported</p>
                </div>
                <input ref={fileRef} type="file" accept=".csv" className="hidden"
                  onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f); }} />
                {fileError && (
                  <p className="text-xs text-red-600 mt-2 flex items-center gap-1">
                    <AlertCircle className="w-3 h-3" /> {fileError}
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Step 2 — Preview */}
          {step === "preview" && (
            <div className="space-y-4">
              {/* Summary bar */}
              <div className="flex items-center gap-4 bg-[#F8FAFC] rounded-xl px-4 py-3">
                <div className="flex items-center gap-1.5 text-sm text-green-700">
                  <CheckCircle className="w-4 h-4" />
                  <span><strong>{validCount}</strong> valid rows</span>
                </div>
                {errorCount > 0 && (
                  <div className="flex items-center gap-1.5 text-sm text-red-600">
                    <AlertCircle className="w-4 h-4" />
                    <span><strong>{errorCount}</strong> rows with errors (will be skipped)</span>
                  </div>
                )}
              </div>

              {/* Preview table */}
              <div className="overflow-x-auto rounded-xl border border-[#F1F5F9]">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-[#F8FAFC] border-b border-[#F1F5F9]">
                      <th className="px-3 py-2 text-left text-[#64748B]">#</th>
                      {columns.map(c => (
                        <th key={c.key} className="px-3 py-2 text-left text-[#64748B]">{c.label}</th>
                      ))}
                      <th className="px-3 py-2 text-left text-[#64748B]">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.03]">
                    {rows.map(row => (
                      <tr key={row.index} className={row.errors.length > 0 ? "bg-red-50" : ""}>
                        <td className="px-3 py-2 text-[#94A3B8] tabular-nums">{row.index}</td>
                        {columns.map(c => (
                          <td key={c.key} className="px-3 py-2 text-[#334155] max-w-[120px] truncate" title={row.data[c.key.toLowerCase()]}>
                            {row.data[c.key.toLowerCase()] || <span className="text-[#CBD5E1]">—</span>}
                          </td>
                        ))}
                        <td className="px-3 py-2">
                          {row.errors.length > 0
                            ? <span className="text-red-600" title={row.errors.join("; ")}>⚠ {row.errors[0]}</span>
                            : <span className="text-green-600">✓ OK</span>
                          }
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <button
                onClick={() => { setRows([]); setStep("upload"); }}
                className="text-xs text-[#64748B] hover:text-[#334155] underline"
              >
                ← Upload a different file
              </button>
            </div>
          )}

          {/* Step 3 — Importing */}
          {step === "importing" && (
            <div className="py-16 text-center space-y-3">
              <Loader className="w-8 h-8 text-blue-600 mx-auto animate-spin" />
              <p className="text-sm text-[#475569]">Importing {validCount} rows…</p>
            </div>
          )}

          {/* Step 4 — Done */}
          {step === "done" && result && (
            <div className="py-8 space-y-4">
              <div className="text-center">
                <CheckCircle className="w-12 h-12 text-green-500 mx-auto mb-3" />
                <p className="text-lg font-semibold text-[#0F172A]">{result.imported} rows imported successfully</p>
                {result.errors.length > 0 && (
                  <p className="text-sm text-red-600 mt-1">{result.errors.length} rows failed</p>
                )}
              </div>
              {result.errors.length > 0 && (
                <div className="bg-red-50 border border-red-100 rounded-xl px-4 py-3 space-y-1 max-h-40 overflow-y-auto">
                  {result.errors.map((e, i) => (
                    <p key={i} className="text-xs text-red-600">{e}</p>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-[#F1F5F9] flex justify-between items-center">
          <button onClick={onClose} className="text-sm text-[#64748B] hover:text-[#334155]">
            {step === "done" ? "Close" : "Cancel"}
          </button>
          {step === "preview" && validCount > 0 && (
            <button
              onClick={handleImport}
              className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700"
            >
              Import {validCount} row{validCount !== 1 ? "s" : ""}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
