"use client";

import { useState, useEffect, useCallback } from "react";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";
import { Badge } from "@/components/ui/badge";

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

function crore(paise: number) {
  const cr = paise / 10000000;
  return `₹${cr.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} Cr`;
}

type MCATab = "companies" | "directors" | "annual" | "events" | "history";

const FILING_STATUS_COLORS: Record<string, string> = {
  not_started: "bg-white/[0.06] text-white/65",
  in_progress: "bg-blue-100 text-blue-700",
  filed: "bg-emerald-100 text-emerald-800",
  overdue: "bg-red-100 text-red-700",
};

const KYC_COLORS: Record<string, string> = {
  active: "bg-green-100 text-green-700",
  pending: "bg-amber-100 text-amber-700",
  expired: "bg-red-100 text-red-700",
};

// ── Company Master ─────────────────────────────────────────────────────────

function CompaniesTab({ clientId }: { clientId: string }) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState({
    cin: "", company_name: "", incorporation_date: "", registered_address: "",
    authorized_capital_paise: "", paid_up_capital_paise: "", company_type: "PVT",
  });

  const load = useCallback(() => {
    setLoading(true);
    apiFetch(`/api/mca-workspace/companies?client_id=${clientId}`)
      .then((r) => setRows(r.success ? r.data : []))
      .finally(() => setLoading(false));
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function saveNew() {
    await apiFetch("/api/mca-workspace/companies", {
      method: "POST",
      body: JSON.stringify({
        ...form,
        client_id: clientId,
        authorized_capital_paise: parseInt(form.authorized_capital_paise) || 0,
        paid_up_capital_paise: parseInt(form.paid_up_capital_paise) || 0,
      }),
    });
    setShowNew(false);
    load();
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="font-medium">Company Master</h3>
        <button onClick={() => setShowNew(true)}
          className="text-sm px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">
          + Add Company
        </button>
      </div>

      {showNew && (
        <div className="border rounded p-4 bg-[#0e1017] space-y-3">
          <p className="text-sm font-medium">Register Company</p>
          <div className="grid grid-cols-2 gap-3">
            {[
              { key: "cin", placeholder: "CIN (e.g. U74999MH2020PTC123456)" },
              { key: "company_name", placeholder: "Company Name" },
              { key: "incorporation_date", placeholder: "Incorporation Date (YYYY-MM-DD)" },
              { key: "authorized_capital_paise", placeholder: "Authorised Capital (paise)" },
              { key: "paid_up_capital_paise", placeholder: "Paid-up Capital (paise)" },
            ].map(({ key, placeholder }) => (
              <input key={key} placeholder={placeholder}
                value={(form as Record<string, string>)[key]}
                onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                className="border rounded px-3 py-1.5 text-sm" />
            ))}
            <input placeholder="Registered Address" value={form.registered_address}
              onChange={(e) => setForm((f) => ({ ...f, registered_address: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm col-span-2" />
            <select value={form.company_type} onChange={(e) => setForm((f) => ({ ...f, company_type: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm">
              {["PVT", "PUB", "OPC", "LLP"].map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
          <div className="flex gap-2">
            <button onClick={saveNew} className="px-3 py-1 bg-blue-600 text-white rounded text-sm">Save</button>
            <button onClick={() => setShowNew(false)} className="px-3 py-1 border rounded text-sm">Cancel</button>
          </div>
        </div>
      )}

      {loading ? <p className="text-sm text-white/40">Loading…</p> : (
        <div className="space-y-3">
          {rows.map((c) => (
            <div key={c.id as string} className="border rounded p-4 space-y-1">
              <div className="flex justify-between items-start">
                <p className="font-medium">{c.company_name as string}</p>
                <span className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded">{c.company_type as string}</span>
              </div>
              <p className="text-xs text-white/40 font-mono">{c.cin as string}</p>
              {!!c.incorporation_date && <p className="text-xs text-white/40">Incorporated: {c.incorporation_date as string}</p>}
              <div className="flex gap-6 text-xs text-white/55 mt-2">
                <span>Auth. Capital: {crore((c.authorized_capital_paise as number) ?? 0)}</span>
                <span>Paid-up: {crore((c.paid_up_capital_paise as number) ?? 0)}</span>
              </div>
              {!!c.registered_address && <p className="text-xs text-white/40 mt-1">{c.registered_address as string}</p>}
            </div>
          ))}
          {rows.length === 0 && <p className="text-center text-white/30 text-sm py-4">No companies registered.</p>}
        </div>
      )}
    </div>
  );
}

// ── Directors ──────────────────────────────────────────────────────────────

function DirectorsTab({ clientId }: { clientId: string }) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState({ din: "", name: "", designation: "Director", date_of_appointment: "", pan: "" });

  const load = useCallback(() => {
    setLoading(true);
    apiFetch(`/api/mca-workspace/directors?client_id=${clientId}`)
      .then((r) => setRows(r.success ? r.data : []))
      .finally(() => setLoading(false));
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function saveNew() {
    await apiFetch("/api/mca-workspace/directors", {
      method: "POST",
      body: JSON.stringify({ ...form, client_id: clientId }),
    });
    setShowNew(false);
    load();
  }

  async function updateKYC(id: string, kyc_status: string) {
    await apiFetch(`/api/mca-workspace/directors/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ kyc_status }),
    });
    load();
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="font-medium">Directors / DIN Register</h3>
        <button onClick={() => setShowNew(true)}
          className="text-sm px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">
          + Add Director
        </button>
      </div>

      {showNew && (
        <div className="border rounded p-4 bg-[#0e1017] space-y-3">
          <p className="text-sm font-medium">Add Director</p>
          <div className="grid grid-cols-2 gap-3">
            {[
              { key: "din", placeholder: "DIN (8 digits)" },
              { key: "name", placeholder: "Full Name" },
              { key: "pan", placeholder: "PAN" },
              { key: "date_of_appointment", placeholder: "Date of Appointment (YYYY-MM-DD)" },
            ].map(({ key, placeholder }) => (
              <input key={key} placeholder={placeholder}
                value={(form as Record<string, string>)[key]}
                onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                className="border rounded px-3 py-1.5 text-sm" />
            ))}
            <select value={form.designation} onChange={(e) => setForm((f) => ({ ...f, designation: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm">
              {["Managing Director", "Whole-time Director", "Director", "Independent Director", "Nominee Director"].map((d) => (
                <option key={d}>{d}</option>
              ))}
            </select>
          </div>
          <div className="flex gap-2">
            <button onClick={saveNew} className="px-3 py-1 bg-blue-600 text-white rounded text-sm">Save</button>
            <button onClick={() => setShowNew(false)} className="px-3 py-1 border rounded text-sm">Cancel</button>
          </div>
        </div>
      )}

      {loading ? <p className="text-sm text-white/40">Loading…</p> : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-[#0e1017] text-left">
              <th className="px-3 py-2 border-b">DIN</th>
              <th className="px-3 py-2 border-b">Name</th>
              <th className="px-3 py-2 border-b">Designation</th>
              <th className="px-3 py-2 border-b">Appointment</th>
              <th className="px-3 py-2 border-b">KYC</th>
              <th className="px-3 py-2 border-b">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id as string} className="border-b hover:bg-[#0e1017]">
                <td className="px-3 py-2 font-mono text-xs">{r.din as string}</td>
                <td className="px-3 py-2">{r.name as string}</td>
                <td className="px-3 py-2 text-xs">{r.designation as string}</td>
                <td className="px-3 py-2 text-xs">{r.date_of_appointment as string}</td>
                <td className="px-3 py-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${KYC_COLORS[r.kyc_status as string] ?? ""}`}>
                    {r.kyc_status as string}
                  </span>
                </td>
                <td className="px-3 py-2">
                  {r.kyc_status !== "active" && (
                    <button onClick={() => updateKYC(r.id as string, "active")}
                      className="text-xs px-2 py-0.5 border rounded hover:bg-green-50 text-green-700">
                      Mark KYC Active
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-4 text-center text-white/30">No directors added.</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── Filings (Annual or Event) ──────────────────────────────────────────────

function FilingsTab({ clientId, category }: { clientId: string; category: "annual" | "event" }) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState({ form_type: "", financial_year: "", due_date: "", description: "" });

  const annualForms = ["AOC-4", "MGT-7", "ADT-1"];
  const eventForms = ["DIR-12", "INC-22", "SH-7", "CHG-1", "CHG-4"];
  const formOptions = category === "annual" ? annualForms : eventForms;

  const load = useCallback(() => {
    setLoading(true);
    apiFetch(`/api/mca-workspace/filings?client_id=${clientId}`)
      .then((r) => {
        const all: Record<string, unknown>[] = r.success ? r.data : [];
        setRows(all.filter((f) => f.category === category));
      })
      .finally(() => setLoading(false));
  }, [clientId, category]);

  useEffect(() => { load(); }, [load]);

  async function saveNew() {
    await apiFetch("/api/mca-workspace/filings", {
      method: "POST",
      body: JSON.stringify({ ...form, client_id: clientId }),
    });
    setShowNew(false);
    load();
  }

  async function updateStatus(id: string, status: string) {
    await apiFetch(`/api/mca-workspace/filings/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status, ca_approved: true }),
    });
    load();
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="font-medium">{category === "annual" ? "Annual" : "Event"} Filings</h3>
        <button onClick={() => setShowNew(true)}
          className="text-sm px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">
          + New Filing
        </button>
      </div>

      {showNew && (
        <div className="border rounded p-4 bg-[#0e1017] space-y-3">
          <p className="text-sm font-medium">Create Filing</p>
          <div className="grid grid-cols-2 gap-3">
            <select value={form.form_type} onChange={(e) => setForm((f) => ({ ...f, form_type: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm">
              <option value="">Select Form</option>
              {formOptions.map((f) => <option key={f}>{f}</option>)}
            </select>
            <input placeholder="Financial Year (e.g. 2025-26)" value={form.financial_year}
              onChange={(e) => setForm((f) => ({ ...f, financial_year: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm" />
            <input placeholder="Due Date (YYYY-MM-DD)" value={form.due_date}
              onChange={(e) => setForm((f) => ({ ...f, due_date: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm" />
            <input placeholder="Description (optional)" value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              className="border rounded px-3 py-1.5 text-sm" />
          </div>
          <div className="flex gap-2">
            <button onClick={saveNew} disabled={!form.form_type}
              className="px-3 py-1 bg-blue-600 text-white rounded text-sm disabled:opacity-50">Save</button>
            <button onClick={() => setShowNew(false)} className="px-3 py-1 border rounded text-sm">Cancel</button>
          </div>
        </div>
      )}

      {loading ? <p className="text-sm text-white/40">Loading…</p> : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-[#0e1017] text-left">
              <th className="px-3 py-2 border-b">Form</th>
              <th className="px-3 py-2 border-b">FY</th>
              <th className="px-3 py-2 border-b">Due Date</th>
              <th className="px-3 py-2 border-b">Status</th>
              <th className="px-3 py-2 border-b">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id as string} className="border-b hover:bg-[#0e1017]">
                <td className="px-3 py-2 font-medium">{r.form_type as string}</td>
                <td className="px-3 py-2">{r.financial_year as string ?? "—"}</td>
                <td className="px-3 py-2 text-xs">{r.due_date as string ?? "—"}</td>
                <td className="px-3 py-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${FILING_STATUS_COLORS[r.status as string] ?? ""}`}>
                    {(r.status as string)?.replace("_", " ")}
                  </span>
                </td>
                <td className="px-3 py-2 space-x-2">
                  {r.status === "not_started" && (
                    <button onClick={() => updateStatus(r.id as string, "in_progress")}
                      className="text-xs px-2 py-0.5 border rounded hover:bg-white/[0.06]">Start</button>
                  )}
                  {r.status === "in_progress" && (
                    <button onClick={() => updateStatus(r.id as string, "filed")}
                      className="text-xs px-2 py-0.5 border rounded hover:bg-green-50 text-green-700">
                      Mark Filed (CA)
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-4 text-center text-white/30">No {category} filings.</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── Filing History ─────────────────────────────────────────────────────────

function FilingHistoryTab({ clientId }: { clientId: string }) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    apiFetch(`/api/mca-workspace/filing-history?client_id=${clientId}`)
      .then((r) => setRows(r.success ? r.data : []))
      .finally(() => setLoading(false));
  }, [clientId]);

  return (
    <div className="space-y-4">
      <h3 className="font-medium">Filing History</h3>
      {loading ? <p className="text-sm text-white/40">Loading…</p> : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-[#0e1017] text-left">
              <th className="px-3 py-2 border-b">Form</th>
              <th className="px-3 py-2 border-b">FY</th>
              <th className="px-3 py-2 border-b">SRN</th>
              <th className="px-3 py-2 border-b">Filed Date</th>
              <th className="px-3 py-2 border-b">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id as string} className="border-b hover:bg-[#0e1017]">
                <td className="px-3 py-2 font-medium">{r.form_type as string}</td>
                <td className="px-3 py-2">{r.financial_year as string ?? "—"}</td>
                <td className="px-3 py-2 font-mono text-xs">{r.srn as string ?? "—"}</td>
                <td className="px-3 py-2 text-xs">{r.filing_date as string ?? "—"}</td>
                <td className="px-3 py-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${FILING_STATUS_COLORS[r.status as string] ?? ""}`}>
                    {r.status as string}
                  </span>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-4 text-center text-white/30">No filed records.</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

const TABS: { id: MCATab; label: string }[] = [
  { id: "companies", label: "Company Master" },
  { id: "directors", label: "Directors" },
  { id: "annual", label: "Annual Filings" },
  { id: "events", label: "Event Filings" },
  { id: "history", label: "Filing History" },
];

export default function MCAWorkspacePage() {
  const { clientId } = useClientNav();
  const [tab, setTab] = useState<MCATab>("companies");

  if (!clientId || clientId === "_placeholder") {
    return <p className="text-sm text-white/40 p-6">Select a client to view MCA workspace.</p>;
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">MCA Compliance Workspace</h2>
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
                : "border-transparent text-white/40 hover:text-white/65"
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      <div>
        {tab === "companies" && <CompaniesTab clientId={clientId} />}
        {tab === "directors" && <DirectorsTab clientId={clientId} />}
        {tab === "annual" && <FilingsTab clientId={clientId} category="annual" />}
        {tab === "events" && <FilingsTab clientId={clientId} category="event" />}
        {tab === "history" && <FilingHistoryTab clientId={clientId} />}
      </div>
    </div>
  );
}
