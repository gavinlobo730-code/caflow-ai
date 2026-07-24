"use client";

import { useState, useEffect, useCallback } from "react";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { toLocalISO } from "@/lib/dateMath";
import { Badge } from "@/components/ui/badge";
import { DashboardSkeleton, TableSkeleton } from "@/components/ui/skeleton";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Helpers ────────────────────────────────────────────────────────────────

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

type GSTTab = "dashboard" | "gstr1" | "gstr3b" | "gstr2b" | "history" | "gstr9";

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-[#F1F5F9] text-[#334155]",
  validated: "bg-blue-100 text-blue-700",
  ca_approved: "bg-green-100 text-green-700",
  submitted: "bg-emerald-100 text-emerald-800",
};

// ── Dashboard ──────────────────────────────────────────────────────────────

function GSTDashboard({ clientId }: { clientId: string }) {
  const [data, setData] = useState<{
    gstr1Count: number; gstr3bCount: number; gstr1Due: string; gstr3bDue: string;
  } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      const supabase = getSupabaseClient();
      const [{ data: g1, error: e1 }, { data: g3b, error: e2 }] = await Promise.all([
        selectAll(() => supabase.from("gstr1_returns").select("id").eq("client_id", clientId)),
        selectAll(() => supabase.from("gstr3b_returns").select("id").eq("client_id", clientId)),
      ]);
      if (cancelled) return;
      if (e1 || e2) {
        setData(null);
        setLoading(false);
        return;
      }

      // Due-date math mirrors gst_workspace.py::gst_dashboard, which resolves
      // the CURRENT calendar period (today's month/year) and computes:
      //   CGST Act §37 — GSTR-1 due 11th of the month following the period
      //   CGST Act §39 — GSTR-3B due 20th of the month following the period
      // (services/compliance_engine.py::gstr1_due_date/gstr3b_due_date).
      const today = new Date();
      let nextMonth = today.getMonth() + 2; // getMonth() is 0-indexed; +1 for "next", +1 to 1-index
      let nextYear = today.getFullYear();
      if (nextMonth > 12) {
        nextMonth -= 12;
        nextYear += 1;
      }
      const dueDateOf = (day: number) => toLocalISO(new Date(nextYear, nextMonth - 1, day));

      setData({
        gstr1Count: (g1 ?? []).length,
        gstr3bCount: (g3b ?? []).length,
        gstr1Due: dueDateOf(11),
        gstr3bDue: dueDateOf(20),
      });
      setLoading(false);
    })();
    return () => { cancelled = true; };
  }, [clientId]);

  if (loading) return <DashboardSkeleton cards={4} />;
  if (!data) return <p className="text-sm text-red-500">Failed to load GST dashboard.</p>;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div className="rounded border p-4 bg-blue-50">
          <p className="text-xs text-[#64748B]">GSTR-1 due date</p>
          <p className="font-semibold">{data.gstr1Due}</p>
        </div>
        <div className="rounded border p-4 bg-amber-50">
          <p className="text-xs text-[#64748B]">GSTR-3B due date</p>
          <p className="font-semibold">{data.gstr3bDue}</p>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4 text-sm">
        <div className="rounded border p-4">
          <p className="font-medium">GSTR-1 returns</p>
          <p className="text-2xl font-bold mt-1">{data.gstr1Count}</p>
        </div>
        <div className="rounded border p-4">
          <p className="font-medium">GSTR-3B returns</p>
          <p className="text-2xl font-bold mt-1">{data.gstr3bCount}</p>
        </div>
      </div>
    </div>
  );
}

// ── GSTR-1 ─────────────────────────────────────────────────────────────────

function GSTR1Tab({ clientId }: { clientId: string }) {
  const [returns, setReturns] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  // Distinguishes "fetch failed" from "no GSTR-1 returns yet" — a masked
  // failure previously rendered identically to a genuinely empty register.
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [period, setPeriod] = useState("");
  const [gstin, setGstin] = useState("");
  const [saving, setSaving] = useState(false);

  const [showCompute, setShowCompute] = useState(false);
  const [computePeriod, setComputePeriod] = useState("");
  const [computing, setComputing] = useState(false);
  const [computeResult, setComputeResult] = useState<Record<string, unknown> | null>(null);
  const [computeError, setComputeError] = useState<string | null>(null);
  const [savingComputed, setSavingComputed] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    apiFetch(`/api/gst-workspace/returns?client_id=${clientId}`)
      .then((r) => {
        if (r.success) {
          setReturns((r.data as { gstr1: Record<string, unknown>[] }).gstr1);
          setLoadError(null);
        } else {
          setReturns([]);
          setLoadError(r.error ?? "Couldn't load GSTR-1 returns.");
        }
      })
      .catch(() => {
        setReturns([]);
        setLoadError("Couldn't load GSTR-1 returns. Please try again.");
      })
      .finally(() => setLoading(false));
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function saveNew() {
    setSaving(true);
    await apiFetch("/api/gst-workspace/gstr1", {
      method: "POST",
      body: JSON.stringify({ client_id: clientId, period, gstin }),
    });
    setShowNew(false);
    setPeriod("");
    setGstin("");
    setSaving(false);
    load();
  }

  async function updateStatus(id: string, status: string) {
    await apiFetch(`/api/gst-workspace/gstr1/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status, ca_approved: true }),
    });
    load();
  }

  // CGST Act §37 — GSTR-1 derived ENTIRELY from posted sales invoices + issued
  // credit/debit notes and reconciled to the General Ledger (services/
  // gst_return_service.py::gstr1_from_books). All computation happens server-
  // side; the frontend only displays the result (CLAUDE.md: zero business
  // logic in the frontend).
  async function computeFromBooks() {
    setComputing(true);
    setComputeError(null);
    setComputeResult(null);
    const r = await apiFetch("/api/gst/gstr1/from-books", {
      method: "POST",
      body: JSON.stringify({ client_id: clientId, period: computePeriod }),
    });
    if (r.success) setComputeResult(r.data as Record<string, unknown>);
    else setComputeError(r.error ?? "Couldn't compute GSTR-1 from books.");
    setComputing(false);
  }

  async function saveComputed() {
    if (!computeResult) return;
    setSavingComputed(true);
    const d = computeResult;
    await apiFetch("/api/gst-workspace/gstr1", {
      method: "POST",
      body: JSON.stringify({
        client_id: clientId,
        period: d.period,
        gstin: d.gstin,
        payload_json: d.payload,
        summary_json: d.summary,
        total_taxable_paise: d.taxable_total_paise,
        total_igst_paise: d.total_igst_paise,
        total_cgst_paise: d.total_cgst_paise,
        total_sgst_paise: d.total_sgst_paise,
        total_cess_paise: d.total_cess_paise,
      }),
    });
    setSavingComputed(false);
    setShowCompute(false);
    setComputeResult(null);
    setComputePeriod("");
    setComputeError(null);
    load();
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="font-medium">GSTR-1 Returns</h3>
        <div className="flex gap-2">
          <button onClick={() => setShowCompute(true)}
            className="text-sm px-3 py-1 border border-blue-300 text-blue-700 rounded hover:bg-blue-50">
            Compute from Books
          </button>
          <button onClick={() => setShowNew(true)}
            className="text-sm px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">
            + New GSTR-1
          </button>
        </div>
      </div>

      {showCompute && (
        <div className="border rounded p-4 bg-[#F8FAFC] space-y-3">
          <p className="text-sm font-medium">Compute GSTR-1 from Books</p>
          <p className="text-xs text-[#64748B]">
            Derives GSTR-1 entirely from posted sales invoices and issued credit/debit notes,
            and reconciles the output tax to the General Ledger. No manual entry.
          </p>
          <input placeholder="Period (MMYYYY e.g. 042025)" value={computePeriod}
            onChange={(e) => setComputePeriod(e.target.value)}
            className="w-full border rounded px-3 py-1.5 text-sm" />
          {computeError && <p className="text-red-600 text-sm">{computeError}</p>}
          <div className="flex gap-2">
            <button onClick={computeFromBooks} disabled={computing || !computePeriod}
              className="px-3 py-1 bg-blue-600 text-white rounded text-sm disabled:opacity-50">
              {computing ? "Computing…" : "Compute"}
            </button>
            <button onClick={() => { setShowCompute(false); setComputeResult(null); setComputeError(null); }}
              className="px-3 py-1 border rounded text-sm">Cancel</button>
          </div>

          {computeResult && (() => {
            const rec = computeResult.reconciliation as Record<string, unknown>;
            const netOut = rec?.net_output_gst as Record<string, number>;
            const reconciled = Boolean(rec?.reconciled);
            return (
              <div className="border-t pt-3 space-y-2">
                <div className={`text-sm px-3 py-2 rounded ${reconciled ? "bg-green-50 text-green-700" : "bg-amber-50 text-amber-800"}`}>
                  {reconciled ? "✓ Reconciled to the General Ledger" : "⚠ Does not reconcile to the General Ledger — review before saving"}
                  {!reconciled && netOut && (
                    <span className="block mt-1 text-xs">
                      Books: {rupees(netOut.books_paise ?? 0)} vs Ledger: {rupees(netOut.ledger_paise ?? 0)}
                      {" "}(diff {rupees(netOut.difference_paise ?? 0)})
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-3 gap-3 text-sm">
                  <div><p className="text-xs text-[#64748B]">Invoices</p><p className="font-medium">{computeResult.invoice_count as number}</p></div>
                  <div><p className="text-xs text-[#64748B]">Taxable Total</p><p className="font-medium">{rupees(computeResult.taxable_total_paise as number)}</p></div>
                  <div><p className="text-xs text-[#64748B]">Tax Total</p><p className="font-medium">{rupees(computeResult.tax_total_paise as number)}</p></div>
                </div>
                <button onClick={saveComputed} disabled={savingComputed}
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
          <p className="text-sm font-medium">New GSTR-1</p>
          <input placeholder="Period (MMYYYY e.g. 042025)" value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="w-full border rounded px-3 py-1.5 text-sm" />
          <input placeholder="GSTIN" value={gstin}
            onChange={(e) => setGstin(e.target.value)}
            className="w-full border rounded px-3 py-1.5 text-sm" />
          <div className="flex gap-2">
            <button onClick={saveNew} disabled={saving || !period || !gstin}
              className="px-3 py-1 bg-blue-600 text-white rounded text-sm disabled:opacity-50">
              {saving ? "Saving…" : "Save Draft"}
            </button>
            <button onClick={() => setShowNew(false)}
              className="px-3 py-1 border rounded text-sm">Cancel</button>
          </div>
        </div>
      )}

      {loading ? <TableSkeleton cols={5} bare /> : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-[#F8FAFC] text-left">
              <th className="px-3 py-2 border-b">Period</th>
              <th className="px-3 py-2 border-b">GSTIN</th>
              <th className="px-3 py-2 border-b">Taxable</th>
              <th className="px-3 py-2 border-b">Status</th>
              <th className="px-3 py-2 border-b">Actions</th>
            </tr>
          </thead>
          <tbody>
            {returns.map((r) => (
              <tr key={r.id as string} className="border-b hover:bg-[#F8FAFC]">
                <td className="px-3 py-2">{r.period as string}</td>
                <td className="px-3 py-2 text-xs">{r.gstin as string}</td>
                <td className="px-3 py-2">{rupees((r.total_taxable_paise as number) ?? 0)}</td>
                <td className="px-3 py-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[r.status as string] ?? ""}`}>
                    {r.status as string}
                  </span>
                </td>
                <td className="px-3 py-2 space-x-2">
                  {r.status === "draft" && (
                    <button onClick={() => updateStatus(r.id as string, "validated")}
                      className="text-xs px-2 py-0.5 border rounded hover:bg-[#F1F5F9]">Validate</button>
                  )}
                  {r.status === "validated" && (
                    <button onClick={() => updateStatus(r.id as string, "ca_approved")}
                      className="text-xs px-2 py-0.5 border rounded hover:bg-green-50 text-green-700">CA Approve</button>
                  )}
                </td>
              </tr>
            ))}
            {loadError ? (
              <tr><td colSpan={5} className="px-3 py-6 text-center">
                <p className="text-sm text-red-600 font-medium">{loadError}</p>
                <button onClick={load} className="mt-2 text-xs px-3 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
              </td></tr>
            ) : returns.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-4 text-center text-[#94A3B8]">No GSTR-1 returns yet.</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── GSTR-3B ────────────────────────────────────────────────────────────────

function GSTR3BTab({ clientId }: { clientId: string }) {
  const [returns, setReturns] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  // Distinguishes "fetch failed" from "no GSTR-3B returns yet".
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [period, setPeriod] = useState("");
  const [gstin, setGstin] = useState("");
  const [saving, setSaving] = useState(false);

  const [showCompute, setShowCompute] = useState(false);
  const [computePeriod, setComputePeriod] = useState("");
  const [computing, setComputing] = useState(false);
  const [computeResult, setComputeResult] = useState<Record<string, unknown> | null>(null);
  const [computeError, setComputeError] = useState<string | null>(null);
  const [savingComputed, setSavingComputed] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    apiFetch(`/api/gst-workspace/returns?client_id=${clientId}`)
      .then((r) => {
        if (r.success) {
          setReturns((r.data as { gstr3b: Record<string, unknown>[] }).gstr3b);
          setLoadError(null);
        } else {
          setReturns([]);
          setLoadError(r.error ?? "Couldn't load GSTR-3B returns.");
        }
      })
      .catch(() => {
        setReturns([]);
        setLoadError("Couldn't load GSTR-3B returns. Please try again.");
      })
      .finally(() => setLoading(false));
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function saveNew() {
    setSaving(true);
    await apiFetch("/api/gst-workspace/gstr3b", {
      method: "POST",
      body: JSON.stringify({ client_id: clientId, period, gstin }),
    });
    setShowNew(false);
    setPeriod("");
    setGstin("");
    setSaving(false);
    load();
  }

  async function updateStatus(id: string, status: string) {
    await apiFetch(`/api/gst-workspace/gstr3b/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status, ca_approved: true }),
    });
    load();
  }

  // CGST Act §39 — GSTR-3B derived ENTIRELY from posted sales/purchase
  // documents (incl. issued credit/debit notes on both sides) and reconciled
  // to the General Ledger's GST control accounts (services/
  // gst_return_service.py::gstr3b_from_books). CA REVIEW REQUIRED before
  // filing — this only computes and previews a draft.
  async function computeFromBooks() {
    setComputing(true);
    setComputeError(null);
    setComputeResult(null);
    const r = await apiFetch("/api/gst/gstr3b/from-books", {
      method: "POST",
      body: JSON.stringify({ client_id: clientId, period: computePeriod }),
    });
    if (r.success) setComputeResult(r.data as Record<string, unknown>);
    else setComputeError(r.error ?? "Couldn't compute GSTR-3B from books.");
    setComputing(false);
  }

  async function saveComputed() {
    if (!computeResult) return;
    setSavingComputed(true);
    const d = computeResult;
    await apiFetch("/api/gst-workspace/gstr3b", {
      method: "POST",
      body: JSON.stringify({
        client_id: clientId,
        period: d.period,
        gstin: d.gstin,
        payload_json: d.payload,
        summary_json: d.working,
        tax_liability_paise: d.tax_liability_paise,
        itc_claimed_paise: d.itc_claimed_paise,
        net_tax_paise: d.net_tax_paise,
      }),
    });
    setSavingComputed(false);
    setShowCompute(false);
    setComputeResult(null);
    setComputePeriod("");
    setComputeError(null);
    load();
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="font-medium">GSTR-3B Returns</h3>
        <div className="flex gap-2">
          <button onClick={() => setShowCompute(true)}
            className="text-sm px-3 py-1 border border-blue-300 text-blue-700 rounded hover:bg-blue-50">
            Compute from Books
          </button>
          <button onClick={() => setShowNew(true)}
            className="text-sm px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">
            + New GSTR-3B
          </button>
        </div>
      </div>

      {showCompute && (
        <div className="border rounded p-4 bg-[#F8FAFC] space-y-3">
          <p className="text-sm font-medium">Compute GSTR-3B from Books</p>
          <p className="text-xs text-[#64748B]">
            Derives GSTR-3B entirely from posted sales/purchase documents (including issued
            credit/debit notes) and reconciles output tax and ITC to the General Ledger.
          </p>
          <input placeholder="Period (MMYYYY e.g. 042025)" value={computePeriod}
            onChange={(e) => setComputePeriod(e.target.value)}
            className="w-full border rounded px-3 py-1.5 text-sm" />
          {computeError && <p className="text-red-600 text-sm">{computeError}</p>}
          <div className="flex gap-2">
            <button onClick={computeFromBooks} disabled={computing || !computePeriod}
              className="px-3 py-1 bg-blue-600 text-white rounded text-sm disabled:opacity-50">
              {computing ? "Computing…" : "Compute"}
            </button>
            <button onClick={() => { setShowCompute(false); setComputeResult(null); setComputeError(null); }}
              className="px-3 py-1 border rounded text-sm">Cancel</button>
          </div>

          {computeResult && (() => {
            const rec = computeResult.reconciliation as Record<string, unknown>;
            const output = rec?.output_gst as Record<string, number>;
            const itc = rec?.itc as Record<string, number>;
            const reconciled = Boolean(rec?.reconciled);
            return (
              <div className="border-t pt-3 space-y-2">
                <div className={`text-sm px-3 py-2 rounded ${reconciled ? "bg-green-50 text-green-700" : "bg-amber-50 text-amber-800"}`}>
                  {reconciled ? "✓ Reconciled to the General Ledger" : "⚠ Does not reconcile to the General Ledger — review before saving"}
                  {!reconciled && (
                    <div className="mt-1 text-xs space-y-0.5">
                      {output && !output.matched && (
                        <p>Output GST — Books: {rupees(output.books_paise ?? 0)} vs Ledger: {rupees(output.ledger_paise ?? 0)}</p>
                      )}
                      {itc && !itc.matched && (
                        <p>ITC — Books: {rupees(itc.books_paise ?? 0)} vs Ledger: {rupees(itc.ledger_paise ?? 0)}</p>
                      )}
                    </div>
                  )}
                </div>
                <div className="grid grid-cols-3 gap-3 text-sm">
                  <div><p className="text-xs text-[#64748B]">Tax Liability</p><p className="font-medium">{rupees(computeResult.tax_liability_paise as number)}</p></div>
                  <div><p className="text-xs text-[#64748B]">ITC Claimed</p><p className="font-medium">{rupees(computeResult.itc_claimed_paise as number)}</p></div>
                  <div><p className="text-xs text-[#64748B]">Net Tax</p><p className="font-medium">{rupees(computeResult.net_tax_paise as number)}</p></div>
                </div>
                <button onClick={saveComputed} disabled={savingComputed}
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
          <p className="text-sm font-medium">New GSTR-3B</p>
          <input placeholder="Period (MMYYYY)" value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="w-full border rounded px-3 py-1.5 text-sm" />
          <input placeholder="GSTIN" value={gstin}
            onChange={(e) => setGstin(e.target.value)}
            className="w-full border rounded px-3 py-1.5 text-sm" />
          <div className="flex gap-2">
            <button onClick={saveNew} disabled={saving || !period || !gstin}
              className="px-3 py-1 bg-blue-600 text-white rounded text-sm disabled:opacity-50">
              {saving ? "Saving…" : "Save Draft"}
            </button>
            <button onClick={() => setShowNew(false)}
              className="px-3 py-1 border rounded text-sm">Cancel</button>
          </div>
        </div>
      )}

      {loading ? <TableSkeleton cols={6} bare /> : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-[#F8FAFC] text-left">
              <th className="px-3 py-2 border-b">Period</th>
              <th className="px-3 py-2 border-b">Tax Liability</th>
              <th className="px-3 py-2 border-b">ITC Claimed</th>
              <th className="px-3 py-2 border-b">Net Tax</th>
              <th className="px-3 py-2 border-b">Status</th>
              <th className="px-3 py-2 border-b">Actions</th>
            </tr>
          </thead>
          <tbody>
            {returns.map((r) => (
              <tr key={r.id as string} className="border-b hover:bg-[#F8FAFC]">
                <td className="px-3 py-2">{r.period as string}</td>
                <td className="px-3 py-2">{rupees((r.tax_liability_paise as number) ?? 0)}</td>
                <td className="px-3 py-2">{rupees((r.itc_claimed_paise as number) ?? 0)}</td>
                <td className="px-3 py-2">{rupees((r.net_tax_paise as number) ?? 0)}</td>
                <td className="px-3 py-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[r.status as string] ?? ""}`}>
                    {r.status as string}
                  </span>
                </td>
                <td className="px-3 py-2 space-x-2">
                  {r.status === "draft" && (
                    <button onClick={() => updateStatus(r.id as string, "validated")}
                      className="text-xs px-2 py-0.5 border rounded hover:bg-[#F1F5F9]">Validate</button>
                  )}
                  {r.status === "validated" && (
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
            ) : returns.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-4 text-center text-[#94A3B8]">No GSTR-3B returns yet.</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── GSTR-2B ────────────────────────────────────────────────────────────────

function GSTR2BTab({ clientId }: { clientId: string }) {
  const [period, setPeriod] = useState("");
  const [jsonText, setJsonText] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function upload() {
    setLoading(true);
    setError(null);
    try {
      const raw_data = JSON.parse(jsonText);
      const resp = await apiFetch("/api/gst-workspace/gstr2b/upload", {
        method: "POST",
        body: JSON.stringify({ client_id: clientId, period, raw_data }),
      });
      if (resp.success) setResult(resp.data);
      else setError(resp.error ?? "Upload failed");
    } catch {
      setError("Invalid JSON. Please paste valid GSTR-2B JSON.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <h3 className="font-medium">GSTR-2B Reconciliation</h3>
      <div className="space-y-3">
        <input placeholder="Period (MMYYYY e.g. 042025)" value={period}
          onChange={(e) => setPeriod(e.target.value)}
          className="w-full border rounded px-3 py-1.5 text-sm" />
        <textarea placeholder="Paste GSTR-2B JSON here (include book_invoices array for reconciliation)"
          value={jsonText} onChange={(e) => setJsonText(e.target.value)}
          rows={8} className="w-full border rounded px-3 py-2 text-sm font-mono" />
        {error && <p className="text-red-600 text-sm">{error}</p>}
        <button onClick={upload} disabled={loading || !period || !jsonText}
          className="px-4 py-2 bg-blue-600 text-white rounded text-sm disabled:opacity-50">
          {loading ? "Reconciling…" : "Upload & Reconcile"}
        </button>
      </div>

      {result && (
        <div className="border rounded p-4 space-y-3">
          <p className="font-medium text-sm">Reconciliation Result</p>
          {(() => {
            const recon = result.reconciliation_result as Record<string, unknown>;
            const summary = recon?.summary as Record<string, number>;
            const mismatched = recon?.mismatched as unknown[];
            const missing = recon?.missing_in_2b as unknown[];
            return (
              <div className="space-y-2">
                <div className="flex gap-4 text-sm">
                  <span className="text-green-700">✓ Matched: {summary?.matched_count ?? 0}</span>
                  <span className="text-amber-600">⚠ Mismatched: {summary?.mismatch_count ?? 0}</span>
                  <span className="text-red-600">✗ Missing: {summary?.missing_count ?? 0}</span>
                </div>
                {(mismatched?.length ?? 0) > 0 && (
                  <div>
                    <p className="text-sm font-medium text-amber-700">Amount mismatches:</p>
                    {(mismatched as Record<string, unknown>[]).map((m, i) => (
                      <div key={i} className="text-xs text-[#334155] mt-1">
                        {JSON.stringify(m.key)} — Book: {rupees(m.book_paise as number)}, 2B: {rupees(m.gstr2b_paise as number)}
                      </div>
                    ))}
                  </div>
                )}
                {(missing?.length ?? 0) > 0 && (
                  <div>
                    <p className="text-sm font-medium text-red-700">Missing in GSTR-2B:</p>
                    {(missing as Record<string, unknown>[]).map((m, i) => (
                      <div key={i} className="text-xs text-[#334155] mt-1">{JSON.stringify(m.key)}</div>
                    ))}
                  </div>
                )}
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
}

// ── Filing History ─────────────────────────────────────────────────────────

function FilingHistoryTab({ clientId }: { clientId: string }) {
  const [data, setData] = useState<{ gstr1_filed: Record<string, unknown>[]; gstr3b_filed: Record<string, unknown>[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    apiFetch(`/api/gst-workspace/filing-history?client_id=${clientId}`)
      .then((r) => {
        if (r.success) { setData(r.data); setLoadError(null); }
        else { setData(null); setLoadError(r.error ?? "Failed to load filing history."); }
      })
      .catch(() => { setData(null); setLoadError("Failed to load filing history. Please try again."); })
      .finally(() => setLoading(false));
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <TableSkeleton cols={4} bare />;
  if (!data) return (
    <div className="text-center py-6 space-y-2">
      <p className="text-sm text-red-500">{loadError ?? "Failed to load filing history."}</p>
      <button onClick={load} className="text-xs px-3 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
    </div>
  );

  const all = ([
    ...(data.gstr1_filed ?? []).map((r) => ({ ...r, type: "GSTR-1" })),
    ...(data.gstr3b_filed ?? []).map((r) => ({ ...r, type: "GSTR-3B" })),
  ] as Record<string, unknown>[]).sort((a, b) =>
    String(b.created_at ?? "").localeCompare(String(a.created_at ?? ""))
  );

  return (
    <div className="space-y-4">
      <h3 className="font-medium">Filing History</h3>
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-[#F8FAFC] text-left">
            <th className="px-3 py-2 border-b">Type</th>
            <th className="px-3 py-2 border-b">Period</th>
            <th className="px-3 py-2 border-b">ARN</th>
            <th className="px-3 py-2 border-b">Status</th>
          </tr>
        </thead>
        <tbody>
          {all.map((r) => (
            <tr key={r.id as string} className="border-b hover:bg-[#F8FAFC]">
              <td className="px-3 py-2 font-medium">{r.type as string}</td>
              <td className="px-3 py-2">{r.period as string}</td>
              <td className="px-3 py-2 text-xs">{(r.arn as string) ?? "—"}</td>
              <td className="px-3 py-2">
                <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[r.status as string] ?? ""}`}>
                  {r.status as string}
                </span>
              </td>
            </tr>
          ))}
          {all.length === 0 && (
            <tr><td colSpan={4} className="px-3 py-4 text-center text-[#94A3B8]">No filed returns yet.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ── GSTR-9 ─────────────────────────────────────────────────────────────────

function GSTR9Tab() {
  return (
    <div className="space-y-4">
      <h3 className="font-medium">GSTR-9 Annual Return</h3>
      <div className="rounded border p-4 bg-amber-50 text-sm text-amber-800">
        <p className="font-medium">⚠ CA Review Required</p>
        <p className="mt-1">GSTR-9 is generated as a read-only draft. The CA must review all data before filing.
          CGST Act §44 — Annual return must be filed by 31st December.</p>
      </div>
      <p className="text-sm text-[#475569]">
        GSTR-9 is auto-computed from your GSTR-1 and GSTR-3B returns for the financial year.
        Navigate to GSTR-1 and GSTR-3B tabs to review monthly returns first.
      </p>
      <p className="text-xs text-[#94A3B8]">Draft generation from filed monthly returns will be available once GSTR-1/3B returns are CA approved.</p>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

// GSTR-9 is intentionally hidden for Closed Beta (Beta-readiness Part 1):
// GSTR9Tab() below has no computation logic behind it (no gstr9_builder in
// apps/api/domain/gst, unlike GSTR-1/GSTR-3B) — it only ever rendered a
// static "not available yet" message. GSTR-9's own due-date obligation is
// still tracked correctly via the Compliance workspace/dashboard; only this
// decorative preparation tab is hidden. Component kept, not deleted, so it
// can be wired to a real builder and re-added to TABS later.
const TABS: { id: GSTTab; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "gstr1", label: "GSTR-1" },
  { id: "gstr3b", label: "GSTR-3B" },
  { id: "gstr2b", label: "GSTR-2B Recon" },
  { id: "history", label: "Filing History" },
];

export default function GSTWorkspacePage() {
  const { clientId } = useClientNav();
  const [tab, setTab] = useState<GSTTab>("dashboard");

  if (!clientId || clientId === "_placeholder") {
    return <p className="text-sm text-[#64748B] p-6">Select a client to view GST workspace.</p>;
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">GST Compliance Workspace</h2>
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
        {tab === "dashboard" && <GSTDashboard clientId={clientId} />}
        {tab === "gstr1" && <GSTR1Tab clientId={clientId} />}
        {tab === "gstr3b" && <GSTR3BTab clientId={clientId} />}
        {tab === "gstr2b" && <GSTR2BTab clientId={clientId} />}
        {tab === "history" && <FilingHistoryTab clientId={clientId} />}
        {tab === "gstr9" && <GSTR9Tab />}
      </div>
    </div>
  );
}
