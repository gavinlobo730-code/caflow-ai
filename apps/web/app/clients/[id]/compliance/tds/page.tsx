"use client";

import { useState, useEffect, useCallback } from "react";
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

type TDSTab = "dashboard" | "deductions" | "challans" | "returns" | "form26as" | "certificates";

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
        setLoading(false);
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
      setLoading(false);
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
  const [form, setForm] = useState({ challan_no: "", challan_date: "", bsr_code: "", section: "", amount_paise: "", financial_year: "", quarter: "Q1" });

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
    await apiFetch("/api/tds-workspace/challans", {
      method: "POST",
      body: JSON.stringify({ ...form, client_id: clientId, amount_paise: parseInt(form.amount_paise) || 0 }),
    });
    setShowNew(false);
    setForm({ challan_no: "", challan_date: "", bsr_code: "", section: "", amount_paise: "", financial_year: "", quarter: "Q1" });
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
              { key: "amount_paise", placeholder: "Amount in paise (₹1 = 100)" },
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

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="font-medium">TDS Returns</h3>
        <button onClick={() => setShowNew(true)}
          className="text-sm px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">
          + New Return
        </button>
      </div>

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
  const [form, setForm] = useState({ deductee_pan: "", deductee_name: "", financial_year: "", certificate_type: "Form 16A", section: "", tds_amount_paise: "" });

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
    await apiFetch("/api/tds-workspace/certificates", {
      method: "POST",
      body: JSON.stringify({ ...form, client_id: clientId, tds_amount_paise: parseInt(form.tds_amount_paise) || 0 }),
    });
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
              { key: "tds_amount_paise", placeholder: "TDS Amount (paise)" },
            ].map(({ key, placeholder }) => (
              <input key={key} placeholder={placeholder}
                value={(form as Record<string, string>)[key]}
                onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                className="border rounded px-3 py-1.5 text-sm" />
            ))}
            <select value={form.certificate_type}
              onChange={(e) => setForm((f) => ({ ...f, certificate_type: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm">
              <option>Form 16</option>
              <option>Form 16A</option>
            </select>
          </div>
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
                <td className="px-3 py-2">{r.certificate_type as string}</td>
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
      </div>
    </div>
  );
}
