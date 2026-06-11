"use client";

import { useState, useEffect, useCallback } from "react";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";
import { Badge } from "@/components/ui/badge";

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
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch(`/api/gst-workspace/?client_id=${clientId}`)
      .then((r) => setData(r.success ? r.data : null))
      .finally(() => setLoading(false));
  }, [clientId]);

  if (loading) return <p className="text-sm text-[#64748B]">Loading…</p>;
  if (!data) return <p className="text-sm text-red-500">Failed to load GST dashboard.</p>;

  const due = data.upcoming_due_dates as Record<string, string>;
  const g1 = (data.gstr1_returns as unknown[]) ?? [];
  const g3b = (data.gstr3b_returns as unknown[]) ?? [];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div className="rounded border p-4 bg-blue-50">
          <p className="text-xs text-[#64748B]">GSTR-1 due date</p>
          <p className="font-semibold">{due?.gstr1 ?? "—"}</p>
        </div>
        <div className="rounded border p-4 bg-amber-50">
          <p className="text-xs text-[#64748B]">GSTR-3B due date</p>
          <p className="font-semibold">{due?.gstr3b ?? "—"}</p>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4 text-sm">
        <div className="rounded border p-4">
          <p className="font-medium">GSTR-1 returns</p>
          <p className="text-2xl font-bold mt-1">{g1.length}</p>
        </div>
        <div className="rounded border p-4">
          <p className="font-medium">GSTR-3B returns</p>
          <p className="text-2xl font-bold mt-1">{g3b.length}</p>
        </div>
      </div>
    </div>
  );
}

// ── GSTR-1 ─────────────────────────────────────────────────────────────────

function GSTR1Tab({ clientId }: { clientId: string }) {
  const [returns, setReturns] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [period, setPeriod] = useState("");
  const [gstin, setGstin] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    apiFetch(`/api/gst-workspace/returns?client_id=${clientId}`)
      .then((r) => setReturns(r.success ? (r.data as { gstr1: Record<string, unknown>[] }).gstr1 : []))
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

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="font-medium">GSTR-1 Returns</h3>
        <button onClick={() => setShowNew(true)}
          className="text-sm px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">
          + New GSTR-1
        </button>
      </div>

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

      {loading ? <p className="text-sm text-[#64748B]">Loading…</p> : (
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
            {returns.length === 0 && (
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
  const [showNew, setShowNew] = useState(false);
  const [period, setPeriod] = useState("");
  const [gstin, setGstin] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    apiFetch(`/api/gst-workspace/returns?client_id=${clientId}`)
      .then((r) => setReturns(r.success ? (r.data as { gstr3b: Record<string, unknown>[] }).gstr3b : []))
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

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="font-medium">GSTR-3B Returns</h3>
        <button onClick={() => setShowNew(true)}
          className="text-sm px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">
          + New GSTR-3B
        </button>
      </div>

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

      {loading ? <p className="text-sm text-[#64748B]">Loading…</p> : (
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
            {returns.length === 0 && (
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

  useEffect(() => {
    apiFetch(`/api/gst-workspace/filing-history?client_id=${clientId}`)
      .then((r) => setData(r.success ? r.data : null))
      .finally(() => setLoading(false));
  }, [clientId]);

  if (loading) return <p className="text-sm text-[#64748B]">Loading…</p>;
  if (!data) return <p className="text-sm text-red-500">Failed to load filing history.</p>;

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

const TABS: { id: GSTTab; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "gstr1", label: "GSTR-1" },
  { id: "gstr3b", label: "GSTR-3B" },
  { id: "gstr2b", label: "GSTR-2B Recon" },
  { id: "history", label: "Filing History" },
  { id: "gstr9", label: "GSTR-9" },
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
