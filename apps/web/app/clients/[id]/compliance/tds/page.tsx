"use client";

import { useState, useEffect, useCallback } from "react";
import { paiseFromRupeeInput, bpsFromPercentInput } from "@/lib/money/rupeeInput";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { Badge } from "@/components/ui/badge";
import { DashboardSkeleton, TableSkeleton } from "@/components/ui/skeleton";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function getToken(): Promise<string> {
  const { data: { session } } = await getSupabaseClient().auth.getSession();
  return session?.access_token ?? "";
}

async function apiFetch(path: string, opts?: RequestInit) {
  const token = await getToken();
  const res = await fetch(`${API}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts?.headers ?? {}),
    },
  });
  return res.json();
}

function rupees(paise: number) {
  return `₹${(paise / 100).toLocaleString("en-IN")}`;
}

type TDSTab = "dashboard" | "deductions" | "challans" | "returns" | "form26as" | "certificates" | "lower_deduction";

/** One thing the challan mapping could not settle — domain/tds/challan_mapping.py.
 *  `message` is the server's own wording and is rendered as it arrives; the
 *  two amounts are alternatives, one per gap code. */
/** One row of `tds_lower_deduction_certificates` (migration 359). */
interface LowerDeductionRow {
  id: string;
  vendor_id: string;
  section: string;
  certificate_no: string;
  /** Basis points — 0.5% is 50, and a NIL certificate is 0. */
  rate_bps: number | string;
  valid_from: string;
  valid_to: string;
  /** Rule 28AA(4)'s amount: a ceiling on the sum credited or paid, not on the tax. */
  ceiling_paise: number | string;
  notes: string | null;
}

interface ChallanGap {
  code: string;
  message: string;
  section?: string;
  shortfall_paise?: number;
  surplus_paise?: number;
}

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-[#F1F5F9] text-[#334155]",
  deposited: "bg-blue-100 text-blue-700",
  prepared: "bg-amber-100 text-amber-700",
  ca_approved: "bg-green-100 text-green-700",
  filed: "bg-emerald-100 text-emerald-800",
  draft: "bg-[#F1F5F9] text-[#334155]",
};

const KYC_COLORS: Record<string, string> = {
  active: "bg-green-100 text-green-700",
  pending: "bg-amber-100 text-amber-700",
  expired: "bg-red-100 text-red-700",
};

// ── Dashboard ──────────────────────────────────────────────────────────────

function TDSDashboard({ clientId }: { clientId: string }) {
  const [summary, setSummary] = useState<{
    total_challans: number; total_deposited_paise: number;
    total_returns: number; total_certificates: number;
  } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      const supabase = getSupabaseClient();
      try {
        const [
          { data: challans, error: e1 },
          { data: returns, error: e2 },
          { data: certs, error: e3 },
        ] = await Promise.all([
          selectAll(() => supabase.from("tds_challans").select("id, total_paise").eq("client_id", clientId)),
          selectAll(() => supabase.from("tds_returns").select("id").eq("client_id", clientId)),
          selectAll(() => supabase.from("tds_certificates").select("id").eq("client_id", clientId)),
        ]);
        if (cancelled) return;
        if (e1 || e2 || e3) {
          setSummary(null);
          return;
        }

        // Mirrors tds_workspace.py::tds_dashboard's summary math exactly:
        // counts of each table's rows plus a plain sum of challan amounts.
        // total_paise (not amount_paise, which tds_challans has never had —
        // migration 037) is the challan's grand-total column.
        const total_deposited_paise = (challans ?? []).reduce(
          (sum, c) => sum + ((c as { total_paise: number | null }).total_paise ?? 0), 0,
        );
        setSummary({
          total_challans: (challans ?? []).length,
          total_deposited_paise,
          total_returns: (returns ?? []).length,
          total_certificates: (certs ?? []).length,
        });
      } catch {
        if (!cancelled) setSummary(null);   // renders "Failed to load TDS dashboard."
      } finally {
        // Guarded by `cancelled` so a superseded effect does not lower the flag
        // the effect that replaced it has just raised.
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [clientId]);

  if (loading) return <DashboardSkeleton cards={4} />;
  if (!summary) return <p className="text-sm text-red-500">Failed to load TDS dashboard.</p>;

  return (
    <div className="grid grid-cols-2 gap-4">
      <div className="rounded border p-4 bg-blue-50">
        <p className="text-xs text-[#64748B]">Total Challans</p>
        <p className="text-2xl font-bold">{summary.total_challans}</p>
      </div>
      <div className="rounded border p-4 bg-green-50">
        <p className="text-xs text-[#64748B]">Total Deposited</p>
        <p className="text-2xl font-bold">{rupees(summary.total_deposited_paise)}</p>
      </div>
      <div className="rounded border p-4 bg-amber-50">
        <p className="text-xs text-[#64748B]">TDS Returns</p>
        <p className="text-2xl font-bold">{summary.total_returns}</p>
      </div>
      <div className="rounded border p-4 bg-purple-50">
        <p className="text-xs text-[#64748B]">Certificates</p>
        <p className="text-2xl font-bold">{summary.total_certificates}</p>
      </div>
    </div>
  );
}

// ── Deductions ─────────────────────────────────────────────────────────────

function DeductionsTab({ clientId }: { clientId: string }) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  // Distinguishes "fetch failed" from "no deductions recorded".
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    apiFetch(`/api/tds-workspace/deductions?client_id=${clientId}`)
      .then((r) => {
        if (r.success) { setRows(r.data); setLoadError(null); }
        else { setRows([]); setLoadError(r.error ?? "Couldn't load TDS deductions."); }
      })
      .catch(() => { setRows([]); setLoadError("Couldn't load TDS deductions. Please try again."); })
      .finally(() => setLoading(false));
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-4">
      <h3 className="font-medium">TDS Deductions Register</h3>
      {loading ? <TableSkeleton cols={6} bare /> : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-[#F8FAFC] text-left">
              <th className="px-3 py-2 border-b">Date</th>
              <th className="px-3 py-2 border-b">Party</th>
              <th className="px-3 py-2 border-b">Section</th>
              <th className="px-3 py-2 border-b">Taxable</th>
              <th className="px-3 py-2 border-b">TDS</th>
              <th className="px-3 py-2 border-b">Quarter</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={(r.id as string) ?? i} className="border-b hover:bg-[#F8FAFC]">
                <td className="px-3 py-2">{r.deduction_date as string ?? "—"}</td>
                <td className="px-3 py-2">{r.deductee_name as string ?? "—"}</td>
                <td className="px-3 py-2 font-mono text-xs">§{r.section as string}</td>
                <td className="px-3 py-2">{rupees((r.taxable_amount_paise as number) ?? 0)}</td>
                <td className="px-3 py-2">{rupees((r.tds_amount_paise as number) ?? 0)}</td>
                <td className="px-3 py-2">{r.quarter as string ?? "—"}</td>
              </tr>
            ))}
            {loadError ? (
              <tr><td colSpan={6} className="px-3 py-6 text-center">
                <p className="text-sm text-red-600 font-medium">{loadError}</p>
                <button onClick={load} className="mt-2 text-xs px-3 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
              </td></tr>
            ) : rows.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-4 text-center text-[#94A3B8]">No deductions recorded.</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── Challans ───────────────────────────────────────────────────────────────

function ChallansTab({ clientId }: { clientId: string }) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  // Distinguishes "fetch failed" from "no challans yet".
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  // amount in RUPEES, converted at the boundary — a CA depositing ₹1,24,500 of
  // TDS should type 124500, not 12450000.
  const [form, setForm] = useState({ challan_no: "", challan_date: "", bsr_code: "", section: "", amount_rupees: "", financial_year: "", quarter: "Q1" });

  const load = useCallback(() => {
    setLoading(true);
    apiFetch(`/api/tds-workspace/challans?client_id=${clientId}`)
      .then((r) => {
        if (r.success) { setRows(r.data); setLoadError(null); }
        else { setRows([]); setLoadError(r.error ?? "Couldn't load TDS challans."); }
      })
      .catch(() => { setRows([]); setLoadError("Couldn't load TDS challans. Please try again."); })
      .finally(() => setLoading(false));
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function saveNew() {
    // Rupees typed, integer paise sent, through the exact parser rather than
    // parseInt (which would read "1,24,500" as 1) or Math.round(x * 100).
    const amount = paiseFromRupeeInput(form.amount_rupees);
    if (amount === null || amount < 0) {
      alert("Amount must be a non-negative amount in rupees, e.g. 124500 or 124500.50.");
      return;
    }
    await apiFetch("/api/tds-workspace/challans", {
      method: "POST",
      body: JSON.stringify({ ...form, client_id: clientId, amount_paise: amount }),
    });
    setShowNew(false);
    setForm({ challan_no: "", challan_date: "", bsr_code: "", section: "", amount_rupees: "", financial_year: "", quarter: "Q1" });
    load();
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="font-medium">TDS Challans</h3>
        <button onClick={() => setShowNew(true)}
          className="text-sm px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">
          + New Challan
        </button>
      </div>

      {showNew && (
        <div className="border rounded p-4 bg-[#F8FAFC] space-y-3">
          <p className="text-sm font-medium">New TDS Challan</p>
          <div className="grid grid-cols-2 gap-3">
            {[
              { key: "challan_no", placeholder: "Challan No." },
              { key: "challan_date", placeholder: "Date (YYYY-MM-DD)" },
              { key: "bsr_code", placeholder: "BSR Code (7 digits)" },
              { key: "section", placeholder: "TDS Section (e.g. 194C)" },
              { key: "amount_rupees", placeholder: "Amount (₹)" },
              { key: "financial_year", placeholder: "FY (e.g. 2025-26)" },
            ].map(({ key, placeholder }) => (
              <input key={key} placeholder={placeholder}
                value={(form as Record<string, string>)[key]}
                onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                className="border rounded px-3 py-1.5 text-sm" />
            ))}
            <select value={form.quarter} onChange={(e) => setForm((f) => ({ ...f, quarter: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm">
              {["Q1", "Q2", "Q3", "Q4"].map((q) => <option key={q}>{q}</option>)}
            </select>
          </div>
          <div className="flex gap-2">
            <button onClick={saveNew} className="px-3 py-1 bg-blue-600 text-white rounded text-sm">Save</button>
            <button onClick={() => setShowNew(false)} className="px-3 py-1 border rounded text-sm">Cancel</button>
          </div>
        </div>
      )}

      {loading ? <TableSkeleton cols={7} bare /> : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-[#F8FAFC] text-left">
              <th className="px-3 py-2 border-b">Challan No.</th>
              <th className="px-3 py-2 border-b">Date</th>
              <th className="px-3 py-2 border-b">BSR Code</th>
              <th className="px-3 py-2 border-b">Section</th>
              <th className="px-3 py-2 border-b">Amount</th>
              <th className="px-3 py-2 border-b">Quarter</th>
              <th className="px-3 py-2 border-b">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id as string} className="border-b hover:bg-[#F8FAFC]">
                <td className="px-3 py-2 font-mono text-xs">{r.challan_no as string}</td>
                <td className="px-3 py-2">{r.payment_date as string}</td>
                <td className="px-3 py-2 font-mono text-xs">{r.bsr_code as string}</td>
                <td className="px-3 py-2">§{r.section as string}</td>
                <td className="px-3 py-2">{rupees((r.total_paise as number) ?? 0)}</td>
                <td className="px-3 py-2">{r.quarter as string}</td>
                <td className="px-3 py-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[r.status as string] ?? ""}`}>
                    {r.status as string}
                  </span>
                </td>
              </tr>
            ))}
            {loadError ? (
              <tr><td colSpan={7} className="px-3 py-6 text-center">
                <p className="text-sm text-red-600 font-medium">{loadError}</p>
                <button onClick={load} className="mt-2 text-xs px-3 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
              </td></tr>
            ) : rows.length === 0 && (
              <tr><td colSpan={7} className="px-3 py-4 text-center text-[#94A3B8]">No challans yet.</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── Returns ────────────────────────────────────────────────────────────────

function ReturnsTab({ clientId }: { clientId: string }) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  // Distinguishes "fetch failed" from "no TDS returns yet".
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState({ return_type: "26Q", quarter: "Q1", financial_year: "" });

  const [showCompute, setShowCompute] = useState(false);
  const [computeForm, setComputeForm] = useState({
    return_type: "26Q", quarter: "Q1", financial_year: "",
    tan: "", deductor_name: "", deductor_pan: "", deductor_address: "",
  });
  const [computing, setComputing] = useState(false);
  const [computeResult, setComputeResult] = useState<Record<string, unknown> | null>(null);
  const [computeError, setComputeError] = useState<string | null>(null);
  const [savingComputed, setSavingComputed] = useState(false);
  // One action at a time: every button that starts work waits for whichever
  // is already running. Guarding each on its own flag alone let two fire at
  // once, and the second could act on what the first was still changing.
  const actionInFlight = computing || savingComputed;

  const load = useCallback(() => {
    setLoading(true);
    apiFetch(`/api/tds-workspace/returns?client_id=${clientId}`)
      .then((r) => {
        if (r.success) { setRows(r.data); setLoadError(null); }
        else { setRows([]); setLoadError(r.error ?? "Couldn't load TDS returns."); }
      })
      .catch(() => { setRows([]); setLoadError("Couldn't load TDS returns. Please try again."); })
      .finally(() => setLoading(false));
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function saveNew() {
    await apiFetch("/api/tds-workspace/returns", {
      method: "POST",
      body: JSON.stringify({ ...form, client_id: clientId }),
    });
    setShowNew(false);
    load();
  }

  async function updateStatus(id: string, status: string) {
    await apiFetch(`/api/tds-workspace/returns/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status, ca_approved: true }),
    });
    load();
  }

  // IT Act §194 series (26Q) / §192 (24Q) — derived ENTIRELY from posted
  // purchase bills / finalized payroll runs and reconciled to the GL "TDS
  // Payable" / "TDS Payable - Salary" control accounts
  // (services/tds_return_service.py). All computation is server-side; the
  // frontend only displays the result (CLAUDE.md: zero business logic in
  // the frontend).
  async function computeFromBooks() {
    setComputing(true);
    setComputeError(null);
    setComputeResult(null);
    // One endpoint per statement, chosen by what the CA picked — never by the
    // browser inspecting the books. Rule 31A(4) routes a deduction by the
    // PAYEE's residency, and the server decides that from the vendor master.
    const path = {
      "24Q": "/api/tds/24q/from-books",
      "27Q": "/api/tds/27q/from-books",
    }[computeForm.return_type] ?? "/api/tds/26q/from-books";
    const r = await apiFetch(path, {
      method: "POST",
      body: JSON.stringify({
        client_id: clientId,
        financial_year: computeForm.financial_year,
        quarter: computeForm.quarter,
        tan: computeForm.tan,
        deductor_name: computeForm.deductor_name,
        deductor_pan: computeForm.deductor_pan,
        deductor_address: computeForm.deductor_address,
      }),
    });
    if (r.success) setComputeResult(r.data as Record<string, unknown>);
    else setComputeError(r.error ?? `Couldn't compute Form ${computeForm.return_type} from books.`);
    setComputing(false);
  }

  async function saveComputed() {
    if (!computeResult) return;
    setSavingComputed(true);
    const d = computeResult;
    await apiFetch("/api/tds-workspace/returns", {
      method: "POST",
      body: JSON.stringify({
        client_id: clientId,
        return_type: computeForm.return_type,
        quarter: d.quarter,
        financial_year: d.financial_year,
        deductee_details: d.deductees,
        total_deductions_paise: d.total_tds_deducted_paise,
        total_deposits_paise: d.total_tds_deposited_paise,
        deductee_count: d.deductee_count,
        validation_errors: d.validation_errors,
      }),
    });
    setSavingComputed(false);
    setShowCompute(false);
    setComputeResult(null);
    setComputeError(null);
    load();
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="font-medium">TDS Returns</h3>
        <div className="flex gap-2">
          <button onClick={() => setShowCompute(true)}
            className="text-sm px-3 py-1 border border-blue-300 text-blue-700 rounded hover:bg-blue-50">
            Compute from Books
          </button>
          <button onClick={() => setShowNew(true)}
            className="text-sm px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">
            + New Return
          </button>
        </div>
      </div>

      {showCompute && (
        <div className="border rounded p-4 bg-[#F8FAFC] space-y-3">
          <p className="text-sm font-medium">Compute TDS Return from Books</p>
          <p className="text-xs text-[#64748B]">
            26Q derives from posted purchase bills and vendor advances; 27Q from the
            same books, for payments to non-residents (Rule 31A(4)(b)); 24Q from
            finalized payroll runs. All three reconcile the total TDS deducted to the
            General Ledger.
          </p>
          <div className="grid grid-cols-2 gap-3">
            <select value={computeForm.return_type} onChange={(e) => setComputeForm((f) => ({ ...f, return_type: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm">
              <option value="26Q">26Q — Vendor / Non-Salary (residents)</option>
              <option value="27Q">27Q — Payments to Non-Residents</option>
              <option value="24Q">24Q — Salary</option>
            </select>
            <select value={computeForm.quarter} onChange={(e) => setComputeForm((f) => ({ ...f, quarter: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm">
              {["Q1", "Q2", "Q3", "Q4"].map((q) => <option key={q}>{q}</option>)}
            </select>
            <input placeholder="FY (e.g. 2025-26)" value={computeForm.financial_year}
              onChange={(e) => setComputeForm((f) => ({ ...f, financial_year: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm" />
            <input placeholder="TAN (10 chars)" value={computeForm.tan}
              onChange={(e) => setComputeForm((f) => ({ ...f, tan: e.target.value.toUpperCase() }))}
              className="border rounded px-3 py-1.5 text-sm font-mono" />
            <input placeholder="Deductor Name" value={computeForm.deductor_name}
              onChange={(e) => setComputeForm((f) => ({ ...f, deductor_name: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm" />
            <input placeholder="Deductor PAN" value={computeForm.deductor_pan}
              onChange={(e) => setComputeForm((f) => ({ ...f, deductor_pan: e.target.value.toUpperCase() }))}
              className="border rounded px-3 py-1.5 text-sm font-mono" />
            <input placeholder="Deductor Address" value={computeForm.deductor_address}
              onChange={(e) => setComputeForm((f) => ({ ...f, deductor_address: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm col-span-2" />
          </div>
          {computeError && <p className="text-red-600 text-sm">{computeError}</p>}
          <div className="flex gap-2">
            <button onClick={computeFromBooks}
              disabled={actionInFlight || !computeForm.financial_year || !computeForm.tan || !computeForm.deductor_name || !computeForm.deductor_pan}
              className="px-3 py-1 bg-blue-600 text-white rounded text-sm disabled:opacity-50">
              {computing ? "Computing…" : "Compute"}
            </button>
            <button onClick={() => { setShowCompute(false); setComputeResult(null); setComputeError(null); }}
              className="px-3 py-1 border rounded text-sm">Cancel</button>
          </div>

          {computeResult && (() => {
            const rec = computeResult.reconciliation as Record<string, unknown>;
            const matched = Boolean(rec?.matched);
            const accountFound = Boolean(rec?.account_found);
            return (
              <div className="border-t pt-3 space-y-2">
                <div className={`text-sm px-3 py-2 rounded ${matched ? "bg-green-50 text-green-700" : "bg-amber-50 text-amber-800"}`}>
                  {!accountFound
                    ? "⚠ Couldn't find the TDS Payable control account in the Chart of Accounts — reconciliation skipped."
                    : matched ? "✓ Reconciled to the General Ledger"
                    : "⚠ Does not reconcile to the General Ledger — review before saving"}
                  {accountFound && !matched && (
                    <span className="block mt-1 text-xs">
                      Books: {rupees((rec.books_paise as number) ?? 0)} vs Ledger: {rupees((rec.ledger_paise as number) ?? 0)}
                      {" "}(diff {rupees((rec.difference_paise as number) ?? 0)})
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-3 gap-3 text-sm">
                  <div><p className="text-xs text-[#64748B]">Deductees</p><p className="font-medium">{computeResult.deductee_count as number}</p></div>
                  <div><p className="text-xs text-[#64748B]">TDS Deducted</p><p className="font-medium">{rupees(computeResult.total_tds_deducted_paise as number)}</p></div>
                  <div><p className="text-xs text-[#64748B]">TDS Deposited</p><p className="font-medium">{rupees(computeResult.total_tds_deposited_paise as number)}</p></div>
                </div>
                {/* 27Q reports tax, SURCHARGE and CESS in three columns, because
                    §195 charges at the rates in force under Part II of the First
                    Schedule with §115A and those carry a surcharge ladder and a
                    4% cess the resident series does not. Shown only where they
                    exist — 26Q and 24Q have no such columns. */}
                {computeForm.return_type === "27Q" && (
                  <div className="grid grid-cols-3 gap-3 text-sm">
                    <div><p className="text-xs text-[#64748B]">Surcharge</p><p className="font-medium">{rupees((computeResult.total_surcharge_paise as number) ?? 0)}</p></div>
                    <div><p className="text-xs text-[#64748B]">Cess</p><p className="font-medium">{rupees((computeResult.total_cess_paise as number) ?? 0)}</p></div>
                    <div>
                      <p className="text-xs text-[#64748B]">Nil remittances</p>
                      <p className="font-medium">{(computeResult.nil_deduction_count as number) ?? 0}</p>
                    </div>
                  </div>
                )}
                {((computeResult.validation_errors as string[]) ?? []).length > 0 && (
                  <div className="space-y-1">
                    {(computeResult.validation_errors as string[]).map((e, i) => (
                      <p key={i} className="text-xs text-red-600">⚠ {e}</p>
                    ))}
                  </div>
                )}
                {/* WHAT THE CHALLAN MAPPING COULD NOT SETTLE (TDS-06). Not a
                    validation error — the return is assembled and the figures
                    are right — but a deductee left without a challan is a 26AS
                    entry that will read 'U' (unmatched) and a §201(1A) exposure,
                    and it has to be seen BEFORE filing rather than after a
                    notice. The sentences are the server's
                    (domain/tds/challan_mapping.py); a screen that reworded them
                    would be a second place describing one gap. */}
                {(() => {
                  // WHAT 26Q LEFT OUT, AND WHERE IT WENT. The server has always
                  // reported this and no screen read it: a total that quietly
                  // drops between one quarter and the next is what nobody
                  // notices until a notice arrives. It now names a return that
                  // exists (TDS-09).
                  const ex = computeResult.excluded_non_resident as
                    { bill_count?: number; tds_paise?: number; reason?: string } | undefined;
                  if (!ex?.bill_count) return null;
                  return (
                    <p className="text-xs text-blue-800 bg-blue-50 border border-blue-200 rounded px-3 py-2">
                      {ex.bill_count} payment{ex.bill_count === 1 ? "" : "s"} to a
                      non-resident, withholding {rupees(ex.tds_paise ?? 0)}, {" "}
                      {ex.bill_count === 1 ? "is" : "are"} not on this return. {ex.reason}
                    </p>
                  );
                })()}
                {((computeResult.challan_gaps as ChallanGap[]) ?? []).length > 0 && (
                  <div className="space-y-1 bg-amber-50 border border-amber-200 rounded px-3 py-2">
                    {(computeResult.challan_gaps as ChallanGap[]).map((g, i) => (
                      <p key={i} className="text-xs text-amber-800">
                        ⚠ <span className="font-medium">
                          {g.section ? `§${g.section}: ` : ""}
                        </span>
                        {g.message}
                        {typeof g.shortfall_paise === "number" && g.shortfall_paise > 0
                          ? ` Not covered: ${rupees(g.shortfall_paise)}.` : ""}
                        {typeof g.surplus_paise === "number" && g.surplus_paise > 0
                          ? ` Unaccounted on the challans: ${rupees(g.surplus_paise)}.` : ""}
                      </p>
                    ))}
                  </div>
                )}
                <button onClick={saveComputed} disabled={actionInFlight}
                  className="px-3 py-1 bg-green-600 text-white rounded text-sm disabled:opacity-50">
                  {savingComputed ? "Saving…" : "Save as Draft"}
                </button>
              </div>
            );
          })()}
        </div>
      )}

      {showNew && (
        <div className="border rounded p-4 bg-[#F8FAFC] space-y-3">
          <p className="text-sm font-medium">New TDS Return</p>
          <div className="grid grid-cols-3 gap-3">
            <select value={form.return_type} onChange={(e) => setForm((f) => ({ ...f, return_type: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm">
              {["24Q", "26Q", "27Q"].map((t) => <option key={t}>{t}</option>)}
            </select>
            <select value={form.quarter} onChange={(e) => setForm((f) => ({ ...f, quarter: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm">
              {["Q1", "Q2", "Q3", "Q4"].map((q) => <option key={q}>{q}</option>)}
            </select>
            <input placeholder="FY (e.g. 2025-26)" value={form.financial_year}
              onChange={(e) => setForm((f) => ({ ...f, financial_year: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm" />
          </div>
          <div className="flex gap-2">
            <button onClick={saveNew} className="px-3 py-1 bg-blue-600 text-white rounded text-sm">Save</button>
            <button onClick={() => setShowNew(false)} className="px-3 py-1 border rounded text-sm">Cancel</button>
          </div>
        </div>
      )}

      {loading ? <TableSkeleton cols={6} bare /> : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-[#F8FAFC] text-left">
              <th className="px-3 py-2 border-b">Type</th>
              <th className="px-3 py-2 border-b">Quarter</th>
              <th className="px-3 py-2 border-b">FY</th>
              <th className="px-3 py-2 border-b">Due Date</th>
              <th className="px-3 py-2 border-b">Status</th>
              <th className="px-3 py-2 border-b">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id as string} className="border-b hover:bg-[#F8FAFC]">
                <td className="px-3 py-2 font-medium">{r.return_type as string}</td>
                <td className="px-3 py-2">{r.quarter as string}</td>
                <td className="px-3 py-2">{r.financial_year as string}</td>
                <td className="px-3 py-2 text-xs">{r.due_date as string ?? "—"}</td>
                <td className="px-3 py-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[r.status as string] ?? ""}`}>
                    {r.status as string}
                  </span>
                </td>
                <td className="px-3 py-2 space-x-2">
                  {r.status === "pending" && (
                    <button onClick={() => updateStatus(r.id as string, "prepared")}
                      className="text-xs px-2 py-0.5 border rounded hover:bg-[#F1F5F9]">Prepare</button>
                  )}
                  {r.status === "prepared" && (
                    <button onClick={() => updateStatus(r.id as string, "ca_approved")}
                      className="text-xs px-2 py-0.5 border rounded hover:bg-green-50 text-green-700">CA Approve</button>
                  )}
                </td>
              </tr>
            ))}
            {loadError ? (
              <tr><td colSpan={6} className="px-3 py-6 text-center">
                <p className="text-sm text-red-600 font-medium">{loadError}</p>
                <button onClick={load} className="mt-2 text-xs px-3 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
              </td></tr>
            ) : rows.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-4 text-center text-[#94A3B8]">No TDS returns yet.</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── 26AS Reconciliation ────────────────────────────────────────────────────

function Form26ASTab({ clientId }: { clientId: string }) {
  const [fy, setFy] = useState("");
  const [jsonText, setJsonText] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function upload() {
    setLoading(true);
    setError(null);
    try {
      const raw_data = JSON.parse(jsonText);
      const resp = await apiFetch("/api/tds-workspace/form26as/upload", {
        method: "POST",
        body: JSON.stringify({ client_id: clientId, financial_year: fy, raw_data }),
      });
      if (resp.success) setResult(resp.data);
      else setError(resp.error ?? "Upload failed");
    } catch {
      setError("Invalid JSON. Please paste valid Form 26AS JSON.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <h3 className="font-medium">Form 26AS Reconciliation</h3>
      <div className="space-y-3">
        <input placeholder="Financial Year (e.g. 2025-26)" value={fy}
          onChange={(e) => setFy(e.target.value)}
          className="w-full border rounded px-3 py-1.5 text-sm" />
        <textarea placeholder='Paste 26AS JSON with "tds_entries" and "book_deductions" arrays'
          value={jsonText} onChange={(e) => setJsonText(e.target.value)}
          rows={8} className="w-full border rounded px-3 py-2 text-sm font-mono" />
        {error && <p className="text-red-600 text-sm">{error}</p>}
        <button onClick={upload} disabled={loading || !fy || !jsonText}
          className="px-4 py-2 bg-blue-600 text-white rounded text-sm disabled:opacity-50">
          {loading ? "Reconciling…" : "Reconcile"}
        </button>
      </div>

      {result && (
        <div className="border rounded p-4 space-y-2">
          <p className="font-medium text-sm">Reconciliation Result</p>
          {(() => {
            const recon = result.reconciliation_result as Record<string, unknown>;
            const summary = recon?.summary as Record<string, number>;
            const mismatched = recon?.mismatched as Record<string, unknown>[];
            return (
              <div className="space-y-2 text-sm">
                <div className="flex gap-4">
                  <span className="text-green-700">✓ Matched: {summary?.matched_count ?? 0}</span>
                  <span className="text-amber-600">⚠ Mismatched: {summary?.mismatch_count ?? 0}</span>
                  <span className="text-red-600">✗ Missing: {summary?.missing_count ?? 0}</span>
                </div>
                {(mismatched?.length ?? 0) > 0 && mismatched.map((m, i) => (
                  <div key={i} className="text-xs text-[#334155] border rounded p-2">
                    PAN: {(m.key as string[])?.[0]} §{(m.key as string[])?.[1]} —
                    Book: {rupees(m.book_paise as number)}, 26AS: {rupees(m.form26as_paise as number)},
                    Diff: {rupees(m.diff_paise as number)}
                  </div>
                ))}
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
}

// ── Certificates ───────────────────────────────────────────────────────────

function CertificatesTab({ clientId }: { clientId: string }) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  // Distinguishes "fetch failed" from "no certificates generated".
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  // "16A", not "Form 16A". migration 037's CHECK on tds_certificates accepts
  // '16','16A','16B','16C' and nothing else, so every draft this screen ever
  // generated was rejected by the database — and the router's `except
  // Exception` turned that into an HTTP 200 saying success: false, which
  // saveNew did not read (TDS-04). The label the CA sees comes back from the
  // server, in the FY's own vocabulary.
  const [form, setForm] = useState({ deductee_pan: "", deductee_name: "", financial_year: "", certificate_type: "16A", section: "", tds_amount_rupees: "" });
  const [saveError, setSaveError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    apiFetch(`/api/tds-workspace/certificates?client_id=${clientId}`)
      .then((r) => {
        if (r.success) { setRows(r.data); setLoadError(null); }
        else { setRows([]); setLoadError(r.error ?? "Couldn't load TDS certificates."); }
      })
      .catch(() => { setRows([]); setLoadError("Couldn't load TDS certificates. Please try again."); })
      .finally(() => setLoading(false));
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function saveNew() {
    const tdsAmount = paiseFromRupeeInput(form.tds_amount_rupees);
    if (tdsAmount === null || tdsAmount < 0) {
      alert("TDS amount must be a non-negative amount in rupees, e.g. 12450 or 12450.50.");
      return;
    }
    // CHECK res.success. This router answers a refusal as HTTP 200 with
    // {success: false, error}, so an unchecked call closes the panel and
    // reloads an unchanged list — which is exactly how a constraint violation
    // looked like a successful save for as long as this screen has existed.
    setSaveError(null);
    try {
      const res = await apiFetch("/api/tds-workspace/certificates", {
        method: "POST",
        body: JSON.stringify({ ...form, client_id: clientId, tds_amount_paise: tdsAmount }),
      });
      if (!res.success) { setSaveError(res.error ?? "Could not generate the certificate draft."); return; }
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Could not generate the certificate draft.");
      return;
    }
    setShowNew(false);
    load();
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="font-medium">TDS Certificates (Form 16/16A)</h3>
        <button onClick={() => setShowNew(true)}
          className="text-sm px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">
          + Generate Draft
        </button>
      </div>
      <div className="rounded border p-3 bg-amber-50 text-xs text-amber-800">
        ⚠ Certificates are draft only. CA must review and sign before issuance. IT Act §203.
      </div>

      {showNew && (
        <div className="border rounded p-4 bg-[#F8FAFC] space-y-3">
          <p className="text-sm font-medium">Generate Certificate Draft</p>
          <div className="grid grid-cols-2 gap-3">
            {[
              { key: "deductee_pan", placeholder: "Deductee PAN" },
              { key: "deductee_name", placeholder: "Deductee Name" },
              { key: "financial_year", placeholder: "FY (e.g. 2025-26)" },
              { key: "section", placeholder: "Section (e.g. 194C)" },
              { key: "tds_amount_rupees", placeholder: "TDS Amount (₹)" },
            ].map(({ key, placeholder }) => (
              <input key={key} placeholder={placeholder}
                value={(form as Record<string, string>)[key]}
                onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                className="border rounded px-3 py-1.5 text-sm" />
            ))}
            <select value={form.certificate_type}
              onChange={(e) => setForm((f) => ({ ...f, certificate_type: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm">
              {/* The VALUE is the stored key; the label is what a CA calls it.
                  From FY 2026-27 the server returns Form 130 / Form 131 for
                  these same keys (CBDT Notification 22/2026), which is why the
                  table below renders certificate_form and not this text. */}
              <option value="16">Form 16 — salary</option>
              <option value="16A">Form 16A — non-salary</option>
            </select>
          </div>
          {saveError && <p className="text-sm text-red-600">{saveError}</p>}
          <div className="flex gap-2">
            <button onClick={saveNew} className="px-3 py-1 bg-blue-600 text-white rounded text-sm">Generate Draft</button>
            <button onClick={() => setShowNew(false)} className="px-3 py-1 border rounded text-sm">Cancel</button>
          </div>
        </div>
      )}

      {loading ? <TableSkeleton cols={6} bare /> : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-[#F8FAFC] text-left">
              <th className="px-3 py-2 border-b">Type</th>
              <th className="px-3 py-2 border-b">Deductee</th>
              <th className="px-3 py-2 border-b">PAN</th>
              <th className="px-3 py-2 border-b">FY</th>
              <th className="px-3 py-2 border-b">TDS</th>
              <th className="px-3 py-2 border-b">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id as string} className="border-b hover:bg-[#F8FAFC]">
                {/* The form's name in ITS OWN period. The register holds
                    several years at once and the stored '16A' is Form 16A for
                    2025-26 and Form 131 for 2026-27; the server derives it per
                    row from domain/tds/vocabulary.py. The note says what ELSE
                    changed — Form 131 is quarterly where 16A was annual. */}
                <td className="px-3 py-2">
                  Form {(r.certificate_form as string) ?? (r.certificate_type as string)}
                  {r.certificate_note ? (
                    <span className="block text-[11px] text-amber-700">{r.certificate_note as string}</span>
                  ) : null}
                </td>
                <td className="px-3 py-2">{r.deductee_name as string}</td>
                <td className="px-3 py-2 font-mono text-xs">{r.deductee_pan as string}</td>
                <td className="px-3 py-2">{r.financial_year as string}</td>
                <td className="px-3 py-2">{rupees((r.tds_deducted_paise as number) ?? 0)}</td>
                <td className="px-3 py-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${KYC_COLORS["pending"]}`}>
                    Draft — CA Review Required
                  </span>
                </td>
              </tr>
            ))}
            {loadError ? (
              <tr><td colSpan={6} className="px-3 py-6 text-center">
                <p className="text-sm text-red-600 font-medium">{loadError}</p>
                <button onClick={load} className="mt-2 text-xs px-3 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
              </td></tr>
            ) : rows.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-4 text-center text-[#94A3B8]">No certificates generated.</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

const TABS: { id: TDSTab; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "deductions", label: "Deductions" },
  { id: "challans", label: "Challans" },
  { id: "returns", label: "Returns" },
  { id: "form26as", label: "26AS Recon" },
  { id: "certificates", label: "Certificates" },
  // The two are opposite directions and the labels say so. "Certificates"
  // holds Form 16/16A — what the CLIENT issues to the people it deducted
  // from. This one holds §197 certificates the client RECEIVES from its
  // vendors, which lower what the client withholds.
  { id: "lower_deduction", label: "§197 Certificates" },
];

export default function TDSWorkspacePage() {
  const { clientId } = useClientNav();
  const [tab, setTab] = useState<TDSTab>("dashboard");

  if (!clientId || clientId === "_placeholder") {
    return <p className="text-sm text-[#64748B] p-6">Select a client to view TDS workspace.</p>;
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">TDS Compliance Workspace</h2>
        <Badge variant="outline" className="text-amber-700 border-amber-300 bg-amber-50 text-xs">
          CA Review Required before filing
        </Badge>
      </div>

      <div className="flex gap-1 border-b">
        {TABS.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t.id
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-[#64748B] hover:text-[#334155]"
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      <div>
        {tab === "dashboard" && <TDSDashboard clientId={clientId} />}
        {tab === "deductions" && <DeductionsTab clientId={clientId} />}
        {tab === "challans" && <ChallansTab clientId={clientId} />}
        {tab === "returns" && <ReturnsTab clientId={clientId} />}
        {tab === "form26as" && <Form26ASTab clientId={clientId} />}
        {tab === "certificates" && <CertificatesTab clientId={clientId} />}
        {tab === "lower_deduction" && <LowerDeductionTab clientId={clientId} />}
      </div>
    </div>
  );
}


/** IT Act §197 lower-deduction certificates, per vendor per section.
 *
 *  WHY A SCREEN AND NOT A FIELD ON THE VENDOR
 *      §197(1) lets the Assessing Officer certify a lower rate "or no
 *      deduction of tax", and Rule 28AA(4) makes the certificate an AMOUNT and
 *      a PERIOD as well as a rate. A bare percentage on the vendor master
 *      carries none of that, which is why PUR-06 deleted `vendors.tds_rate_bps`
 *      from the vendor form rather than honouring it: a CA typed 1%, saw "1.0%"
 *      in the list, and every bill deducted 2%.
 *
 *  NOTHING IS COMPUTED HERE. The engine decides which certificate is in force,
 *  how much of its ceiling is left and what that means for a bill
 *  (services/vendor_tds.py with domain/tds/lower_deduction.py). This records
 *  the four facts and shows them back.
 */
function LowerDeductionTab({ clientId }: { clientId: string }) {
  const [rows, setRows] = useState<LowerDeductionRow[]>([]);
  const [vendors, setVendors] = useState<{ id: string; name: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    vendor_id: "", section: "", certificate_no: "",
    rate_percent: "", valid_from: "", valid_to: "", ceiling_rupees: "",
  });
  // WHICH SECTIONS THIS SCREEN MAY OFFER IS A SERVER QUESTION, and it was a
  // hardcoded list here until the backend guard caught it. Two facts decide it
  // — §197(1)'s own list of provisions, and whether the RATE ENGINE holds the
  // section at all — and both live in apps/api. Offering §194M because §197
  // reaches it would let a CA record a certificate against a section no bill
  // can ever be computed for, which is exactly what
  // tests/test_a_section_the_engine_cannot_answer_for_is_refused.py exists to
  // stop on the vendor master.
  const [sections, setSections] = useState<string[]>([]);
  const [notPriced, setNotPriced] = useState<string[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    const sb = getSupabaseClient();
    try {
      const [certs, vends, secs] = await Promise.all([
        selectAll(() => sb.from("tds_lower_deduction_certificates")
          .select("id, vendor_id, section, certificate_no, rate_bps, valid_from, valid_to, ceiling_paise, notes")
          .eq("client_id", clientId).order("valid_from", { ascending: false }).order("id")),
        selectAll(() => sb.from("vendors").select("id, name")
          .eq("client_id", clientId).eq("is_active", true).order("name").order("id")),
        apiFetch("/api/tds/sections"),
      ]);
      if (certs.error) throw certs.error;
      setRows((certs.data as LowerDeductionRow[]) ?? []);
      setVendors((vends.data as { id: string; name: string }[]) ?? []);
      const payload = secs?.success
        ? (secs.data as {
            sections?: { section: string; section_197_eligible?: boolean }[];
            section_197_not_priced?: string[];
          })
        : null;
      const eligible = (payload?.sections ?? [])
        .filter((s) => s.section_197_eligible).map((s) => s.section);
      setSections(eligible);
      setNotPriced(payload?.section_197_not_priced ?? []);
      setForm((f) => (f.section || eligible.length === 0 ? f : { ...f, section: eligible[0] }));
      setLoadError(null);
    } catch {
      setRows([]);
      setLoadError("Couldn't load §197 certificates. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function saveNew() {
    setSaveError(null);
    // bpsFromPercentInput is the ONE parser for a typed percentage, the same
    // rule lib/money/rupeeInput.ts states for amounts: 0.5 must become 50 bps
    // and "0.5%" or "half" must become nothing at all.
    const rateBps = bpsFromPercentInput(form.rate_percent);
    const ceiling = paiseFromRupeeInput(form.ceiling_rupees);
    if (!form.vendor_id) { setSaveError("Choose the vendor the certificate is for."); return; }
    if (!form.section) { setSaveError("Choose the section the certificate was issued under."); return; }
    if (!form.certificate_no.trim()) { setSaveError("The certificate number is what Form 26Q reports — it is required."); return; }
    if (rateBps === null || rateBps < 0) { setSaveError("Enter the certified rate as a percentage, e.g. 0.5 — a nil certificate is 0."); return; }
    if (ceiling === null || ceiling <= 0) {
      setSaveError("Rule 28AA(4) issues a certificate for a specified AMOUNT. Enter the amount it applies up to.");
      return;
    }
    if (!form.valid_from || !form.valid_to || form.valid_to < form.valid_from) {
      setSaveError("Enter the validity period. Rule 28AA(4) caps it at the financial year.");
      return;
    }
    setSaving(true);
    let failure: string | null = null;
    try {
      // The role-guarded write policies of migration 359 are the only check on
      // this path: PostgREST reaches the table directly and rbac() never runs.
      const { error } = await getSupabaseClient()
        .from("tds_lower_deduction_certificates").insert({
          client_id: clientId, vendor_id: form.vendor_id,
          section: form.section, certificate_no: form.certificate_no.trim(),
          rate_bps: rateBps, valid_from: form.valid_from, valid_to: form.valid_to,
          ceiling_paise: ceiling,
        });
      if (error) {
        failure = error.message.includes("uq_tds_ldc")
          ? "That certificate number is already recorded for this vendor and section."
          : `Couldn't save the certificate: ${error.message}`;
      }
    } catch (e) {
      failure = e instanceof Error ? e.message : "Couldn't save the certificate.";
    } finally {
      setSaving(false);
    }
    if (failure) { setSaveError(failure); return; }
    setShowNew(false);
    setForm({ vendor_id: "", section: "194C", certificate_no: "", rate_percent: "",
              valid_from: "", valid_to: "", ceiling_rupees: "" });
    load();
  }

  const vendorName = (id: string) => vendors.find((v) => v.id === id)?.name ?? "—";

  if (loading) return <TableSkeleton />;

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <div>
          <h3 className="font-medium">§197 Lower-Deduction Certificates</h3>
          <p className="text-xs text-[#64748B] mt-0.5">
            What a vendor&apos;s Assessing Officer certified: the rate, the certificate
            number, the period, and the amount it applies up to (Rule 28AA(4)). Bills and
            advances to that vendor withhold at the certified rate until the amount is used up.
          </p>
        </div>
        <button onClick={() => setShowNew((s) => !s)}
          className="text-sm px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 whitespace-nowrap">
          + Record Certificate
        </button>
      </div>

      {loadError && <p className="text-sm text-red-600">{loadError}</p>}

      {/* NAMED RATHER THAN SILENTLY ABSENT. §197(1) reaches these too, and this
          product cannot price a bill under them — so a certificate recorded
          against one could never be applied. Saying so is the difference
          between a gap and a mystery. §195 is on the list for a second reason
          as well: even where a certificate is on file, the engine deliberately
          does not combine a certified rate with the §115A / Part II / DTAA
          comparison §195 already requires, and says so on the document. */}
      {notPriced.length > 0 && (
        <p className="text-xs text-[#64748B] bg-[#F8FAFC] border rounded px-3 py-2">
          §197 also reaches {notPriced.map((s) => `§${s}`).join(", ")}, which this
          product does not price — a certificate recorded against one could not be
          applied to a bill, so it is not offered here.
        </p>
      )}

      {showNew && (
        <div className="border rounded p-4 bg-[#F8FAFC] space-y-3">
          {saveError && <p className="text-sm text-red-600">{saveError}</p>}
          <div className="grid grid-cols-3 gap-3">
            <select value={form.vendor_id} onChange={(e) => setForm((f) => ({ ...f, vendor_id: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm">
              <option value="">Vendor…</option>
              {vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
            <select value={form.section} onChange={(e) => setForm((f) => ({ ...f, section: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm">
              {sections.length === 0 && <option value="">Section…</option>}
              {sections.map((s) => <option key={s} value={s}>§{s}</option>)}
            </select>
            <input placeholder="Certificate no." value={form.certificate_no}
              onChange={(e) => setForm((f) => ({ ...f, certificate_no: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm" />
            <input placeholder="Certified rate % (0 for nil)" value={form.rate_percent}
              onChange={(e) => setForm((f) => ({ ...f, rate_percent: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm" />
            <input type="date" value={form.valid_from}
              onChange={(e) => setForm((f) => ({ ...f, valid_from: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm" />
            <input type="date" value={form.valid_to}
              onChange={(e) => setForm((f) => ({ ...f, valid_to: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm" />
            <input placeholder="Amount it applies up to (₹)" value={form.ceiling_rupees}
              onChange={(e) => setForm((f) => ({ ...f, ceiling_rupees: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm col-span-2" />
          </div>
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowNew(false)}
              className="text-sm px-3 py-1 border rounded">Cancel</button>
            <button onClick={saveNew} disabled={saving}
              className="text-sm px-3 py-1 bg-green-600 text-white rounded disabled:opacity-50">
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      )}

      {rows.length === 0 && !loadError ? (
        <p className="text-sm text-[#64748B]">
          No §197 certificates recorded. Without one, every bill withholds at the full
          section rate — which is right unless a vendor has produced a certificate.
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-[#64748B] border-b">
              <th className="py-2">Vendor</th><th>Section</th><th>Certificate</th>
              <th className="text-right">Rate</th><th>Valid</th>
              <th className="text-right">Up to</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className="border-b last:border-0">
                <td className="py-2">{vendorName(c.vendor_id)}</td>
                <td>§{c.section}</td>
                <td className="font-mono text-[11px]">{c.certificate_no}</td>
                <td className="text-right tabular-nums">
                  {Number(c.rate_bps) === 0 ? "Nil" : `${Number(c.rate_bps) / 100}%`}
                </td>
                <td className="text-xs">{c.valid_from} → {c.valid_to}</td>
                <td className="text-right tabular-nums">{rupees(Number(c.ceiling_paise ?? 0))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
