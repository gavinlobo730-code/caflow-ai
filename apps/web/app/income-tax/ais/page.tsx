"use client";

/**
 * AIS review — IT Act §285BB, the Annual Information Statement.
 *
 * The department's statement of what OTHERS reported about the taxpayer. A CA
 * reviews it before filing an ITR because it is what a §143(1)(a) adjustment
 * is raised from and what a §143(3) scrutiny starts with.
 *
 * WHAT THIS PAGE USED TO BE
 *   805 lines holding a JSON parser, a books-comparison grid and the whole
 *   reconciliation in React state, with no call to anything. It was gone on
 *   refresh — and its own footer said the working was "stored locally in your
 *   browser only", which was not true either: it was stored nowhere.
 *
 *   It also asserted two things nothing knew. A BLANK books box meant "Not in
 *   Books", which fed an "Est. Undeclared Amount" and lit a red discrepancy
 *   banner — so an uploaded, unreviewed statement reported every line as
 *   undeclared income. And it showed "Est. Tax Impact (30%)" in rupees, with
 *   no knowledge of the client's regime, entity type or slab.
 *
 * WHAT IT IS NOW
 *   A view over /api/ais. The file's TEXT is posted; the server parses it
 *   (domain/income_tax/ais.py), keeps it (migration 352) and derives every
 *   status from the two figures. There is no parser in this file, and there
 *   is no tax figure anywhere on the screen.
 *
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
 * # Nothing here reaches the income-tax portal. AIS is downloaded by hand from
 * # incometax.gov.in, and feedback on a wrong line is submitted there.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import * as XLSX from "xlsx";
import { api, type AISLine, type AISStatement } from "@/lib/api";
import { useClientPicker } from "@/lib/workspace/useClientPicker";
import { assessmentYearChoices, financialYearForAy } from "@/lib/income-tax/assessmentYear";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { todayLocalISO } from "@/lib/dateMath";
import {
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Download,
  FileText,
  HelpCircle,
  Plus,
  Trash2,
  Upload,
} from "lucide-react";

function formatRupees(paise: number): string {
  const rupees = Math.floor(Math.abs(paise) / 100);
  const rest = Math.abs(paise) % 100;
  const sign = paise < 0 ? "-" : "";
  return `${sign}₹${rupees.toLocaleString("en-IN")}.${String(rest).padStart(2, "0")}`;
}

/** Blank means the CA has not answered. It is NOT nil, and the two go to the
 *  server as different requests — null and 0. */
function booksInputToPaise(text: string): number | null | "invalid" {
  if (text.trim() === "") return null;
  const paise = paiseFromRupeeInput(text);
  return paise === null ? "invalid" : paise;
}

const STATUS_LABEL: Record<AISLine["status"], string> = {
  not_reviewed: "Not reviewed",
  matched: "Agreed",
  amount_mismatch: "Differs",
  not_in_books: "Not in books",
  explained: "Explained",
};

function StatusBadge({ status }: { status: AISLine["status"] }) {
  const base = "inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium";
  if (status === "matched")
    return <span className={`${base} bg-green-100 text-green-700`}><CheckCircle2 className="w-3 h-3" /> Agreed</span>;
  if (status === "explained")
    return <span className={`${base} bg-blue-100 text-blue-700`}><CheckCircle2 className="w-3 h-3" /> Explained</span>;
  if (status === "not_in_books")
    return <span className={`${base} bg-red-100 text-red-700`}><AlertCircle className="w-3 h-3" /> Not in books</span>;
  if (status === "amount_mismatch")
    return <span className={`${base} bg-amber-100 text-amber-700`}><AlertTriangle className="w-3 h-3" /> Differs</span>;
  // Not a finding. It is the absence of one, and it reads that way.
  return <span className={`${base} bg-[#F1F5F9] text-[#64748B]`}><HelpCircle className="w-3 h-3" /> Not reviewed</span>;
}

const BLANK_MANUAL = { transaction_type: "Salary", payer: "", amount: "", tds: "" };

export default function AISPage() {
  const { clients, clientId, setClientId } = useClientPicker();
  const years = useMemo(() => assessmentYearChoices(), []);
  const [assessmentYear, setAssessmentYear] = useState(years[1] ?? years[0] ?? "");

  const [statement, setStatement] = useState<AISStatement | null>(null);
  const [types, setTypes] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [books, setBooks] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [showManual, setShowManual] = useState(false);
  const [manual, setManual] = useState(BLANK_MANUAL);
  const fileRef = useRef<HTMLInputElement>(null);

  const client = clients.find((c) => c.id === clientId);

  useEffect(() => {
    api.ais.meta()
      .then((r) => setTypes(r.data?.transaction_types ?? []))
      .catch(() => setTypes([]));
  }, []);

  /** Load the whole statement — lines, workings and summary in one call, so
   *  the table and the totals can never describe different data. */
  const load = useCallback(async () => {
    if (!clientId || !assessmentYear) { setStatement(null); return; }
    setLoading(true);
    setError(null);
    try {
      const res = await api.ais.statement(clientId, assessmentYear);
      setStatement(res.data);
      const nextBooks: Record<string, string> = {};
      const nextNotes: Record<string, string> = {};
      for (const line of res.data?.records ?? []) {
        nextBooks[line.id] = line.books_amount_paise === null
          ? "" : (line.books_amount_paise / 100).toFixed(2);
        nextNotes[line.id] = line.note ?? "";
      }
      setBooks(nextBooks);
      setNotes(nextNotes);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the statement.");
      setStatement(null);
    } finally {
      setLoading(false);
    }
  }, [clientId, assessmentYear]);

  useEffect(() => { void load(); }, [load]);

  // ── Upload ───────────────────────────────────────────────────────────────

  const handleFile = useCallback((file: File) => {
    if (!clientId) { setError("Pick the client this statement belongs to first."); return; }
    setError(null);
    setMessage(null);
    const reader = new FileReader();
    reader.onload = async (e) => {
      const raw = String(e.target?.result ?? "");
      setBusy(true);
      try {
        // The browser sends the TEXT. It does not parse it — there is one
        // parser, in domain/income_tax/ais.py, and it is the tested one.
        const res = await api.ais.upload({
          client_id: clientId, assessment_year: assessmentYear,
          raw, file_name: file.name,
        });
        setStatement(res.data);
        setMessage(`${res.data?.records?.length ?? 0} lines read from ${file.name}.`);
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not read that file.");
      } finally {
        setBusy(false);
      }
    };
    reader.readAsText(file);
  }, [clientId, assessmentYear, load]);

  // ── One line's working ───────────────────────────────────────────────────

  async function saveWorking(line: AISLine, status?: string | null) {
    const parsed = booksInputToPaise(books[line.id] ?? "");
    if (parsed === "invalid") {
      setError("That is not a rupee amount. Type it like 125000 or 125000.50.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await api.ais.saveWorking(line.id, {
        client_id: clientId,
        books_amount_paise: parsed,
        status: status ?? null,
        note: (notes[line.id] ?? "").trim() || null,
      });
      await load();
    } catch (e) {
      // The server's refusals name what to do next, so they are shown as
      // written rather than replaced with a generic message.
      setError(e instanceof Error ? e.message : "Could not save that.");
    } finally {
      setBusy(false);
    }
  }

  async function addManual() {
    if (!statement?.upload) return;
    const amount = paiseFromRupeeInput(manual.amount);
    const tds = manual.tds.trim() === "" ? 0 : paiseFromRupeeInput(manual.tds);
    if (amount === null || tds === null) {
      setError("Amount and TDS must be rupee amounts, like 125000 or 125000.50.");
      return;
    }
    setBusy(true);
    try {
      await api.ais.addRecord({
        client_id: clientId,
        upload_id: statement.upload.id,
        transaction_type: manual.transaction_type,
        payer: manual.payer.trim(),
        amount_paise: amount,
        tds_deducted_paise: tds,
      });
      setManual(BLANK_MANUAL);
      setError(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add that line.");
    } finally {
      setBusy(false);
    }
  }

  async function removeLine(line: AISLine) {
    setBusy(true);
    try {
      await api.ais.deleteRecord(line.id);
      setError(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not remove that line.");
    } finally {
      setBusy(false);
    }
  }

  // ── Export ───────────────────────────────────────────────────────────────

  const exportRows = useMemo(() => (statement?.records ?? []).map((r) => ({
    Client: client?.client_name ?? "",
    "Assessment Year": assessmentYear,
    "Information category": r.information_label ?? "",
    Type: r.transaction_type,
    "Payer / Deductor": r.payer ?? "",
    Source: r.source === "json" ? "AIS (published)" : "Added by the firm",
    "AIS Amount (₹)": (r.amount_paise / 100).toFixed(2),
    "TDS Deducted (₹)": (r.tds_deducted_paise / 100).toFixed(2),
    // "Not reviewed" is written out as words, never as a zero: a zero in this
    // column is a claim about the books.
    "Amount in Books (₹)": r.books_amount_paise === null
      ? "Not reviewed" : (r.books_amount_paise / 100).toFixed(2),
    "Difference (₹)": r.books_amount_paise === null
      ? "" : ((r.amount_paise - r.books_amount_paise) / 100).toFixed(2),
    Status: STATUS_LABEL[r.status],
    Note: r.note ?? "",
  })), [statement, client, assessmentYear]);

  function exportCSV() {
    if (!exportRows.length) return;
    const header = Object.keys(exportRows[0]);
    const csv = [
      header.join(","),
      ...exportRows.map((row) => header
        .map((h) => `"${String((row as Record<string, string>)[h]).replace(/"/g, '""')}"`)
        .join(",")),
    ].join("\n");
    const blob = new Blob(["﻿" + csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `AIS_${client?.client_name ?? "Client"}_AY${assessmentYear}_${todayLocalISO()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function exportXLSX() {
    if (!exportRows.length) return;
    const ws = XLSX.utils.json_to_sheet(exportRows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "AIS review");
    XLSX.writeFile(wb, `AIS_${client?.client_name ?? "Client"}_AY${assessmentYear}_${todayLocalISO()}.xlsx`);
  }

  const summary = statement?.summary;
  const lines = statement?.records ?? [];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Link href="/income-tax" className="inline-flex items-center gap-1 text-xs text-[#94A3B8] hover:text-[#475569] mb-2 transition-colors">
            <ArrowLeft className="w-3.5 h-3.5" /> Income Tax
          </Link>
          <h1 className="text-xl font-semibold text-[#0F172A]">AIS review</h1>
          <p className="text-sm text-[#64748B] mt-0.5">
            Annual Information Statement — IT Act §285BB
          </p>
        </div>
        {lines.length > 0 && (
          <div className="flex gap-2">
            <button onClick={exportCSV} className="flex items-center gap-2 px-4 py-2 bg-white border border-[#E2E8F0] text-[#334155] text-sm font-medium rounded-lg hover:bg-[#F8FAFC] transition-colors">
              <Download className="w-4 h-4" /> CSV
            </button>
            <button onClick={exportXLSX} className="flex items-center gap-2 px-4 py-2 bg-white border border-[#E2E8F0] text-[#334155] text-sm font-medium rounded-lg hover:bg-[#F8FAFC] transition-colors">
              <Download className="w-4 h-4" /> Excel
            </button>
          </div>
        )}
      </div>

      {/* Client and assessment year */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] px-5 py-4 grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-[#334155] mb-1.5">Client</label>
          <select
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">Select a client…</option>
            {clients.map((c) => <option key={c.id} value={c.id}>{c.client_name}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-[#334155] mb-1.5">
            Assessment year
          </label>
          <select
            value={assessmentYear}
            onChange={(e) => setAssessmentYear(e.target.value)}
            className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {years.map((y) => <option key={y} value={y}>AY {y}</option>)}
          </select>
          {/* The two labels look identical, so the one being reviewed is
              spelled out rather than left to be inferred. */}
          <p className="text-xs text-[#94A3B8] mt-1">
            Income of FY {financialYearForAy(assessmentYear) || "—"}
          </p>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />
          <p className="text-xs text-red-700">{error}</p>
        </div>
      )}
      {message && !error && (
        <div className="bg-green-50 border border-green-200 rounded-xl px-4 py-3 flex items-start gap-2">
          <CheckCircle2 className="w-4 h-4 text-green-600 shrink-0 mt-0.5" />
          <p className="text-xs text-green-700">{message}</p>
        </div>
      )}

      {/* Upload */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50">
          <h2 className="text-sm font-semibold text-[#0F172A]">Step 1 — Upload the AIS JSON</h2>
          <p className="text-xs text-[#94A3B8] mt-0.5">
            Download from <span className="font-mono">incometax.gov.in</span> → AIS → Download JSON
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
              if (file) handleFile(file);
              e.target.value = "";
            }}
          />
          <div
            onClick={() => { if (clientId) fileRef.current?.click(); }}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) handleFile(f); }}
            className={`border-2 border-dashed rounded-xl p-8 text-center transition-colors ${
              clientId ? "border-[#E2E8F0] cursor-pointer hover:border-blue-300 hover:bg-blue-50/30"
                       : "border-[#F1F5F9] cursor-not-allowed"}`}
          >
            <Upload className="w-8 h-8 text-[#CBD5E1] mx-auto mb-3" />
            <p className="text-sm font-medium text-[#475569]">
              {clientId ? "Click to upload or drag & drop the AIS JSON"
                        : "Pick a client first"}
            </p>
            <p className="text-xs text-[#94A3B8] mt-1">
              The file is read on the server and kept against this client and year.
            </p>
          </div>
        </div>
      </div>

      {/* What the statement itself says */}
      {statement?.upload && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] px-5 py-4 space-y-3">
          <div className="flex flex-wrap gap-x-8 gap-y-2 text-xs">
            <div>
              <span className="text-[#94A3B8]">PAN on the statement</span>
              <p className="font-mono text-sm text-[#0F172A]">
                {statement.upload.pan ?? "—"}
              </p>
            </div>
            <div>
              <span className="text-[#94A3B8]">Name on the statement</span>
              <p className="text-sm text-[#0F172A]">{statement.upload.taxpayer_name ?? "—"}</p>
            </div>
            <div>
              <span className="text-[#94A3B8]">File</span>
              <p className="text-sm text-[#0F172A]">{statement.upload.file_name ?? "—"}</p>
            </div>
            <div>
              <span className="text-[#94A3B8]">Lines</span>
              <p className="text-sm text-[#0F172A]">{statement.upload.record_count}</p>
            </div>
          </div>
          {statement.upload.problems?.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
              <p className="text-xs font-semibold text-amber-800 mb-1">
                This file did not read completely
              </p>
              <ul className="text-xs text-amber-700 list-disc pl-4 space-y-0.5">
                {statement.upload.problems.map((p, i) => <li key={i}>{p}</li>)}
              </ul>
            </div>
          )}
          {statement.uploads.length > 1 && (
            <p className="text-xs text-[#64748B]">
              {statement.uploads.length} statements have been uploaded for AY {assessmentYear}.
              The most recent is shown; a line identical to one already worked on keeps its working.
            </p>
          )}
        </div>
      )}

      {/* The lines */}
      {lines.length > 0 && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-[#0F172A]">Step 2 — What the books carry</h2>
              <p className="text-xs text-[#94A3B8] mt-0.5">
                Leave a line blank until it has been looked at. A blank is not a nil.
              </p>
            </div>
            <span className="text-xs text-[#64748B] font-medium">
              {lines.length} lines · AIS total {formatRupees(summary?.total_amount_paise ?? 0)}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-[#F8FAFC] text-xs text-[#64748B] font-medium uppercase tracking-wider">
                  <th className="px-5 py-2.5 text-left">Information category</th>
                  <th className="px-4 py-2.5 text-left">Payer / Deductor</th>
                  <th className="px-4 py-2.5 text-right">AIS amount</th>
                  <th className="px-4 py-2.5 text-right">TDS</th>
                  <th className="px-4 py-2.5 text-right">In the books</th>
                  <th className="px-4 py-2.5 text-right">Difference</th>
                  <th className="px-4 py-2.5 text-left">Status</th>
                  <th className="px-4 py-2.5 text-left">Note</th>
                  <th className="px-4 py-2.5"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {lines.map((line) => {
                  const diff = line.books_amount_paise === null
                    ? null : line.amount_paise - line.books_amount_paise;
                  return (
                    <tr key={line.id} className="hover:bg-[#F8FAFC]/50 transition-colors align-top">
                      <td className="px-5 py-3">
                        <p className="font-medium text-[#0F172A] text-xs">{line.transaction_type}</p>
                        <p className="text-[11px] text-[#94A3B8] max-w-xs truncate">
                          {line.information_label}
                        </p>
                        <span className={`mt-1 inline-block text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                          line.source === "json" ? "bg-purple-50 text-purple-700"
                                                 : "bg-[#F1F5F9] text-[#475569]"}`}>
                          {line.source === "json" ? "AIS (published)" : "Added by the firm"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-[#475569] text-xs max-w-xs truncate">{line.payer}</td>
                      <td className="px-4 py-3 text-right text-[#0F172A] font-medium text-xs">
                        {formatRupees(line.amount_paise)}
                      </td>
                      <td className="px-4 py-3 text-right text-[#475569] text-xs">
                        {line.tds_deducted_paise > 0
                          ? formatRupees(line.tds_deducted_paise)
                          : <span className="text-[#CBD5E1]">—</span>}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <input
                          type="text"
                          inputMode="decimal"
                          placeholder="Not reviewed"
                          value={books[line.id] ?? ""}
                          onChange={(e) => setBooks((p) => ({ ...p, [line.id]: e.target.value }))}
                          onBlur={() => { void saveWorking(line); }}
                          className="w-32 border border-[#E2E8F0] rounded-lg px-2 py-1 text-xs text-[#0F172A] text-right focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                      </td>
                      <td className="px-4 py-3 text-right text-xs font-medium">
                        {diff === null ? <span className="text-[#CBD5E1]">—</span>
                          : diff === 0 ? <span className="text-green-600">₹0.00</span>
                          : <span className="text-amber-600">{formatRupees(diff)}</span>}
                      </td>
                      <td className="px-4 py-3 space-y-1">
                        <StatusBadge status={line.status} />
                        <div>
                          <button
                            onClick={() => { setBooks((p) => ({ ...p, [line.id]: "" })); void saveWorking(line, "not_in_books"); }}
                            disabled={busy}
                            className="text-[10px] text-red-600 hover:underline disabled:opacity-40"
                          >
                            Mark not in books
                          </button>
                          {line.status === "amount_mismatch" && (
                            <button
                              onClick={() => { void saveWorking(line, "explained"); }}
                              disabled={busy}
                              className="ml-2 text-[10px] text-blue-600 hover:underline disabled:opacity-40"
                            >
                              Explained
                            </button>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <input
                          type="text"
                          placeholder="Why the difference is acceptable"
                          value={notes[line.id] ?? ""}
                          onChange={(e) => setNotes((p) => ({ ...p, [line.id]: e.target.value }))}
                          onBlur={() => { void saveWorking(line); }}
                          className="w-44 border border-[#E2E8F0] rounded-lg px-2 py-1 text-xs text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                      </td>
                      <td className="px-4 py-3">
                        {line.source === "manual" && (
                          <button
                            onClick={() => { void removeLine(line); }}
                            disabled={busy}
                            className="text-[#CBD5E1] hover:text-red-500 transition-colors disabled:opacity-40"
                            aria-label="Remove this line"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* A line the file does not carry */}
          <div className="px-5 py-4 border-t border-gray-50">
            <button
              onClick={() => setShowManual((v) => !v)}
              className="inline-flex items-center gap-1.5 text-xs text-blue-600 hover:text-blue-700 font-medium transition-colors"
            >
              <Plus className="w-3.5 h-3.5" /> {showManual ? "Hide" : "Add a line the statement does not carry"}
            </button>
            {showManual && (
              <div className="mt-3 grid grid-cols-2 md:grid-cols-5 gap-3 items-end">
                <div>
                  <label className="block text-xs font-medium text-[#334155] mb-1.5">Type</label>
                  <select
                    value={manual.transaction_type}
                    onChange={(e) => setManual((p) => ({ ...p, transaction_type: e.target.value }))}
                    className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm"
                  >
                    {types.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#334155] mb-1.5">Payer / Deductor</label>
                  <input
                    type="text"
                    value={manual.payer}
                    onChange={(e) => setManual((p) => ({ ...p, payer: e.target.value }))}
                    className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#334155] mb-1.5">Amount (₹)</label>
                  <input
                    type="text"
                    inputMode="decimal"
                    value={manual.amount}
                    onChange={(e) => setManual((p) => ({ ...p, amount: e.target.value }))}
                    className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#334155] mb-1.5">TDS (₹)</label>
                  <input
                    type="text"
                    inputMode="decimal"
                    value={manual.tds}
                    onChange={(e) => setManual((p) => ({ ...p, tds: e.target.value }))}
                    className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm"
                  />
                </div>
                <button
                  onClick={() => { void addManual(); }}
                  disabled={busy || !manual.payer.trim() || !manual.amount.trim()}
                  className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 transition-colors"
                >
                  Add
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* What is open */}
      {summary && lines.length > 0 && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50">
            <h2 className="text-sm font-semibold text-[#0F172A]">Step 3 — What is still open</h2>
          </div>
          <div className="px-5 py-5 grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-[#F8FAFC] rounded-xl p-4">
              <p className="text-xs text-[#64748B] font-medium uppercase tracking-wide mb-1">Total on the AIS</p>
              <p className="text-lg font-semibold text-[#0F172A]">{formatRupees(summary.total_amount_paise)}</p>
              <p className="text-[11px] text-[#94A3B8] mt-1">TDS {formatRupees(summary.total_tds_paise)}</p>
            </div>
            <div className="bg-[#F8FAFC] rounded-xl p-4">
              <p className="text-xs text-[#64748B] font-medium uppercase tracking-wide mb-1">Not yet reviewed</p>
              <p className="text-lg font-semibold text-[#334155]">
                {summary.not_reviewed_count} of {summary.line_count}
              </p>
              <p className="text-[11px] text-[#94A3B8] mt-1">No conclusion is drawn about these.</p>
            </div>
            <div className="bg-red-50 rounded-xl p-4">
              <p className="text-xs text-red-600 font-medium uppercase tracking-wide mb-1">Not in the books</p>
              <p className="text-lg font-semibold text-red-700">{formatRupees(summary.not_in_books_paise)}</p>
            </div>
            <div className="bg-amber-50 rounded-xl p-4">
              <p className="text-xs text-amber-600 font-medium uppercase tracking-wide mb-1">Books short by</p>
              <p className="text-lg font-semibold text-amber-700">{formatRupees(summary.shortfall_paise)}</p>
            </div>
          </div>

          {/* The refusal, printed. It is the server's sentence, not this
              screen's — the same words wherever the figure is asked for. */}
          <div className="px-5 pb-5">
            <div className="bg-blue-50 border border-blue-100 rounded-xl px-4 py-3 flex items-start gap-2">
              <HelpCircle className="w-4 h-4 text-blue-600 shrink-0 mt-0.5" />
              <p className="text-xs text-blue-700">{summary.tax_impact_refused}</p>
            </div>
          </div>

          {summary.not_reviewed_count > 0 && (
            <div className="px-5 pb-5">
              <div className="bg-[#F8FAFC] border border-[#E2E8F0] rounded-xl px-4 py-3 text-xs text-[#475569]">
                {summary.not_reviewed_count} line{summary.not_reviewed_count === 1 ? "" : "s"} still
                to look at. The two figures above cover only the lines already reviewed.
              </div>
            </div>
          )}
          {summary.not_reviewed_count === 0 && summary.open_paise === 0 && (
            <div className="px-5 pb-5">
              <div className="bg-green-50 border border-green-200 rounded-xl px-4 py-3 flex items-start gap-3">
                <CheckCircle2 className="w-4 h-4 text-green-600 shrink-0 mt-0.5" />
                <p className="text-xs text-green-700">
                  Every line on this statement has been reviewed and agrees with the books
                  or is explained. AIS is not the only source of income — this says nothing
                  about receipts no one reported.
                </p>
              </div>
            </div>
          )}
        </div>
      )}

      {!loading && lines.length === 0 && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] px-5 py-14 text-center space-y-3">
          <FileText className="w-10 h-10 text-gray-200 mx-auto" />
          <p className="text-sm font-medium text-[#475569]">
            {clientId ? `No AIS uploaded for AY ${assessmentYear}` : "Pick a client to begin"}
          </p>
          <p className="text-xs text-[#94A3B8] max-w-sm mx-auto">
            Upload the AIS JSON downloaded from the income-tax portal. Everything read
            from it is kept against this client and year.
          </p>
        </div>
      )}

      <div className="bg-blue-50 border border-blue-100 rounded-xl px-5 py-3">
        <p className="text-xs text-blue-700">
          <span className="font-semibold">Note:</span> the statement and this review are kept
          on your firm&apos;s own database and can be re-opened later. Nothing is transmitted
          to the income-tax portal from here — where an AIS line itself is wrong, submit
          feedback on it at <span className="font-mono">incometax.gov.in</span>.
        </p>
      </div>
    </div>
  );
}
