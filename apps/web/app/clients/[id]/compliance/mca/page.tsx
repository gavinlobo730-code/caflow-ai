"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { useClientEntityType } from "@/lib/clients/useClientEntityType";
import { isCompaniesActCompany, mcaRegime, mcaScopeNote } from "@/lib/entityObligations";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { Badge } from "@/components/ui/badge";
import { ListSkeleton, TableSkeleton } from "@/components/ui/skeleton";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import FilingDemoWizard, { fetchFilingDemoCapabilities } from "@/components/FilingDemoWizard";

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
  not_started: "bg-[#F1F5F9] text-[#334155]",
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
  // Distinguishes "fetch failed" from "no companies registered" — the
  // Supabase query's error field used to be destructured away entirely.
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState({
    cin: "", company_name: "", incorporation_date: "", registered_address: "",
    authorized_capital_rupees: "", paid_up_capital_rupees: "", company_type: "PVT",
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const supabase = getSupabaseClient();
      const { data, error } = await selectAll(() => supabase
        .from("mca_companies")
        .select("id, company_name, cin, incorp_date, registered_office, authorized_capital_paise, paid_up_capital_paise, company_category")
        .eq("client_id", clientId));
      if (error) throw error;
      setRows((data as Record<string, unknown>[]) ?? []);
      setLoadError(null);
    } catch (e) {
      setRows([]);
      setLoadError(e instanceof Error ? e.message : "Couldn't load companies.");
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function saveNew() {
    const cinUp = form.cin.trim().toUpperCase();
    if (cinUp && !/^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$/.test(cinUp)) {
      alert("Invalid CIN. Format: U74999MH2020PTC123456 (21 chars, starts with L or U). Companies Act 2013.");
      return;
    }
    const authorised = paiseFromRupeeInput(form.authorized_capital_rupees);
    const paidUp = paiseFromRupeeInput(form.paid_up_capital_rupees);
    if (authorised === null || paidUp === null) {
      alert("Authorised and paid-up capital must be amounts in rupees, e.g. 2500000.");
      return;
    }
    if (paidUp > authorised) {
      // Companies Act 2013 s.2(64)/s.2(84): paid-up capital is the portion of
      // the issued capital actually paid, so it cannot exceed what is
      // authorised. Catching it here is cheaper than an MCA rejection.
      alert("Paid-up capital cannot exceed authorised capital.");
      return;
    }
    await apiFetch("/api/mca-workspace/companies", {
      method: "POST",
      body: JSON.stringify({
        ...form,
        cin: cinUp,
        client_id: clientId,
        // Rupees typed, integer paise sent. paiseFromRupeeInput rather than
        // parseInt or Math.round(x * 100): it is exact by construction and
        // returns null for anything that is not an amount, so "25 lakh" is
        // refused instead of becoming ₹25.
        authorized_capital_paise: authorised,
        paid_up_capital_paise: paidUp,
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
        <div className="border rounded p-4 bg-[#F8FAFC] space-y-3">
          <p className="text-sm font-medium">Register Company</p>
          <div className="grid grid-cols-2 gap-3">
            {(([
              { key: "cin", placeholder: "CIN (e.g. U74999MH2020PTC123456)", maxLength: 21 },
              { key: "company_name", placeholder: "Company Name" },
              { key: "incorporation_date", placeholder: "Incorporation Date (YYYY-MM-DD)" },
              // In RUPEES, converted at the boundary below. These asked for
              // paise, so a CA registering ₹25,00,000 of authorised capital had
              // to type 250000000 — and one wrong zero files the company's
              // capital out by a factor of ten.
              { key: "authorized_capital_rupees", placeholder: "Authorised Capital (₹)" },
              { key: "paid_up_capital_rupees", placeholder: "Paid-up Capital (₹)" },
            ] as { key: string; placeholder: string; maxLength?: number }[]).map(({ key, placeholder, maxLength }) => (
              <input key={key} placeholder={placeholder} maxLength={maxLength}
                value={(form as Record<string, string>)[key]}
                onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                className="border rounded px-3 py-1.5 text-sm" />
            )))}
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

      {loading ? <ListSkeleton rows={3} /> : loadError ? (
        <div className="text-center py-6 space-y-2">
          <p className="text-sm text-red-600 font-medium">{loadError}</p>
          <button onClick={load} className="text-xs px-3 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
        </div>
      ) : (
        <div className="space-y-3">
          {rows.map((c) => (
            <div key={c.id as string} className="border rounded p-4 space-y-1">
              <div className="flex justify-between items-start">
                <p className="font-medium">{c.company_name as string}</p>
                <span className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded">{c.company_category as string}</span>
              </div>
              <p className="text-xs text-[#64748B] font-mono">{c.cin as string}</p>
              {!!c.incorp_date && <p className="text-xs text-[#64748B]">Incorporated: {c.incorp_date as string}</p>}
              <div className="flex gap-6 text-xs text-[#475569] mt-2">
                <span>Auth. Capital: {crore((c.authorized_capital_paise as number) ?? 0)}</span>
                <span>Paid-up: {crore((c.paid_up_capital_paise as number) ?? 0)}</span>
              </div>
              {!!c.registered_office && <p className="text-xs text-[#64748B] mt-1">{c.registered_office as string}</p>}
            </div>
          ))}
          {rows.length === 0 && <p className="text-center text-[#94A3B8] text-sm py-4">No companies registered.</p>}
        </div>
      )}
    </div>
  );
}

// ── Directors ──────────────────────────────────────────────────────────────

function DirectorsTab({ clientId }: { clientId: string }) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  // Distinguishes "fetch failed" from "no directors added".
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState({ din: "", name: "", designation: "Director", date_of_appointment: "", pan: "" });

  const load = useCallback(() => {
    setLoading(true);
    apiFetch(`/api/mca-workspace/directors?client_id=${clientId}`)
      .then((r) => {
        if (r.success) { setRows(r.data); setLoadError(null); }
        else { setRows([]); setLoadError(r.error ?? "Couldn't load directors."); }
      })
      .catch(() => { setRows([]); setLoadError("Couldn't load directors. Please try again."); })
      .finally(() => setLoading(false));
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function saveNew() {
    if (form.din && !/^\d{8}$/.test(form.din)) {
      alert("DIN must be exactly 8 digits. IT Act / Companies Act 2013.");
      return;
    }
    if (form.pan && !/^[A-Z]{5}[0-9]{4}[A-Z]$/.test(form.pan)) {
      alert("PAN format must be ABCDE1234F (5 letters + 4 digits + 1 letter). IT Act §139A.");
      return;
    }
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
        <div className="border rounded p-4 bg-[#F8FAFC] space-y-3">
          <p className="text-sm font-medium">Add Director</p>
          <div className="grid grid-cols-2 gap-3">
            {(([
              { key: "din", placeholder: "DIN (8 digits)", maxLength: 8 },
              { key: "name", placeholder: "Full Name" },
              { key: "pan", placeholder: "PAN (e.g. ABCDE1234F)", maxLength: 10, uppercase: true },
              { key: "date_of_appointment", placeholder: "Date of Appointment (YYYY-MM-DD)" },
            ] as { key: string; placeholder: string; maxLength?: number; uppercase?: boolean }[]).map(({ key, placeholder, maxLength, uppercase }) => (
              <input key={key} placeholder={placeholder} maxLength={maxLength}
                value={(form as Record<string, string>)[key]}
                onChange={(e) => setForm((f) => ({ ...f, [key]: uppercase ? e.target.value.toUpperCase() : e.target.value }))}
                className="border rounded px-3 py-1.5 text-sm" />
            )))}
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

      {loading ? <TableSkeleton cols={6} bare /> : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-[#F8FAFC] text-left">
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
              <tr key={r.id as string} className="border-b hover:bg-[#F8FAFC]">
                <td className="px-3 py-2 font-mono text-xs">{r.din as string}</td>
                <td className="px-3 py-2">{r.director_name as string}</td>
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
            {loadError ? (
              <tr><td colSpan={6} className="px-3 py-6 text-center">
                <p className="text-sm text-red-600 font-medium">{loadError}</p>
                <button onClick={load} className="mt-2 text-xs px-3 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
              </td></tr>
            ) : rows.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-4 text-center text-[#94A3B8]">No directors added.</td></tr>
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
  // Distinguishes "fetch failed" from "no filings of this category yet".
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState({ form_type: "", financial_year: "", due_date: "", description: "" });
  const [confirmFiling, setConfirmFiling] = useState<Record<string, unknown> | null>(null);
  const [srn, setSrn] = useState("");
  const [filingDate, setFilingDate] = useState("");
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const annualForms = ["AOC-4", "MGT-7", "ADT-1"];
  const eventForms = ["DIR-12", "INC-22", "SH-7", "CHG-1", "CHG-4"];
  const formOptions = category === "annual" ? annualForms : eventForms;

  // The generic filing walk-through (services/filing_demo/mca) — annual
  // forms only, and offered only where the server says the demo exists (the
  // dead-control rule: a button whose endpoint would refuse must be absent).
  const demoForms = ["AOC-4", "MGT-7", "MGT-7A", "ADT-1"];
  const [demoFlows, setDemoFlows] = useState<string[]>([]);
  const [demo, setDemo] = useState<{ id: string } | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    apiFetch(`/api/mca-workspace/filings?client_id=${clientId}`)
      .then((r) => {
        if (r.success) {
          const all: Record<string, unknown>[] = r.data;
          setRows(all.filter((f) => f.category === category));
          setLoadError(null);
        } else {
          setRows([]);
          setLoadError(r.error ?? "Couldn't load filings.");
        }
      })
      .catch(() => { setRows([]); setLoadError("Couldn't load filings. Please try again."); })
      .finally(() => setLoading(false));
  }, [clientId, category]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    // Event forms have no walk-through, so the event tab never probes.
    if (category !== "annual") return;
    let cancelled = false;
    fetchFilingDemoCapabilities().then((c) => {
      if (!cancelled) setDemoFlows(c.enabled ? c.flows : []);
    });
    return () => { cancelled = true; };
  }, [category]);

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

  // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: marking a filing as "filed" requires
  // an explicit SRN and confirmation, mirroring the Mark-as-Filed workflow used
  // by the GSTR-1/GSTR-3B/TDS/ITR filing pages.
  function openConfirmFiling(row: Record<string, unknown>) {
    setConfirmFiling(row);
    setSrn("");
    setFilingDate(new Date().toISOString().slice(0, 10));
    setConfirmError(null);
  }

  async function confirmMarkFiled() {
    if (!confirmFiling) return;
    if (!srn.trim()) {
      setConfirmError("SRN is required");
      return;
    }
    if (!filingDate) {
      setConfirmError("Filing date is required");
      return;
    }
    setConfirming(true);
    setConfirmError(null);
    try {
      const res = await apiFetch(`/api/mca-workspace/filings/${confirmFiling.id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status: "filed", ca_approved: true, srn: srn.trim(), filing_date: filingDate }),
      });
      if (!res.success) throw new Error(res.error ?? "Failed to update status");
      setConfirmFiling(null);
      load();
    } catch (err) {
      setConfirmError(err instanceof Error ? err.message : "Failed to update status");
    } finally {
      setConfirming(false);
    }
  }

  return (
    <div className="space-y-4">
      {demo && (
        <FilingDemoWizard
          flow="mca"
          clientId={clientId}
          refData={{ filing_id: demo.id }}
          onClose={() => setDemo(null)}
        />
      )}
      <div className="flex justify-between items-center">
        <h3 className="font-medium">{category === "annual" ? "Annual" : "Event"} Filings</h3>
        <button onClick={() => setShowNew(true)}
          className="text-sm px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">
          + New Filing
        </button>
      </div>

      {showNew && (
        <div className="border rounded p-4 bg-[#F8FAFC] space-y-3">
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

      {loading ? <TableSkeleton cols={5} bare /> : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-[#F8FAFC] text-left">
              <th className="px-3 py-2 border-b">Form</th>
              <th className="px-3 py-2 border-b">FY</th>
              <th className="px-3 py-2 border-b">Due Date</th>
              <th className="px-3 py-2 border-b">Status</th>
              <th className="px-3 py-2 border-b">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id as string} className="border-b hover:bg-[#F8FAFC]">
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
                      className="text-xs px-2 py-0.5 border rounded hover:bg-[#F1F5F9]">Start</button>
                  )}
                  {r.status === "in_progress" && (
                    <button onClick={() => openConfirmFiling(r)}
                      className="text-xs px-2 py-0.5 border rounded hover:bg-green-50 text-green-700">
                      Mark Filed (CA)
                    </button>
                  )}
                  {/* Annual forms not yet filed, and only where the server
                      says the walk-through exists — the dead-control rule. */}
                  {category === "annual" && r.status !== "filed" &&
                    demoFlows.includes("mca") && demoForms.includes(r.form_type as string) && (
                    <button onClick={() => setDemo({ id: r.id as string })}
                      className="text-xs px-2 py-0.5 border border-amber-300 rounded hover:bg-amber-50 text-amber-800">
                      File (demo)
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {loadError ? (
              <tr><td colSpan={5} className="px-3 py-6 text-center">
                <p className="text-sm text-red-600 font-medium">{loadError}</p>
                <button onClick={load} className="mt-2 text-xs px-3 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
              </td></tr>
            ) : rows.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-4 text-center text-[#94A3B8]">No {category} filings.</td></tr>
            )}
          </tbody>
        </table>
      )}

      {confirmFiling && (
        <div className="border rounded p-4 bg-amber-50 border-amber-200 space-y-3">
          <div>
            <p className="text-sm font-medium">Confirm Filing — {confirmFiling.form_type as string}</p>
            <p className="text-xs text-amber-700 mt-1">
              This records an already-filed ROC form. PracticeSync does NOT auto-submit to the MCA21
              portal. Verify the SRN before confirming.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <input placeholder="SRN (required)" value={srn}
              onChange={(e) => setSrn(e.target.value)}
              className="border rounded px-3 py-1.5 text-sm font-mono" />
            <input type="date" value={filingDate}
              onChange={(e) => setFilingDate(e.target.value)}
              className="border rounded px-3 py-1.5 text-sm" />
          </div>
          {confirmError && <p className="text-xs text-red-600">{confirmError}</p>}
          <div className="flex gap-2">
            <button onClick={confirmMarkFiled} disabled={confirming}
              className="px-3 py-1 bg-green-600 text-white rounded text-sm disabled:opacity-50">
              {confirming ? "Saving…" : "Confirm Filing"}
            </button>
            <button onClick={() => setConfirmFiling(null)} className="px-3 py-1 border rounded text-sm">Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Filing History ─────────────────────────────────────────────────────────

function FilingHistoryTab({ clientId }: { clientId: string }) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  // Distinguishes "fetch failed" from "no filed records".
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    apiFetch(`/api/mca-workspace/filing-history?client_id=${clientId}`)
      .then((r) => {
        if (r.success) { setRows(r.data); setLoadError(null); }
        else { setRows([]); setLoadError(r.error ?? "Couldn't load filing history."); }
      })
      .catch(() => { setRows([]); setLoadError("Couldn't load filing history. Please try again."); })
      .finally(() => setLoading(false));
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-4">
      <h3 className="font-medium">Filing History</h3>
      {loading ? <TableSkeleton cols={5} bare /> : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-[#F8FAFC] text-left">
              <th className="px-3 py-2 border-b">Form</th>
              <th className="px-3 py-2 border-b">FY</th>
              <th className="px-3 py-2 border-b">SRN</th>
              <th className="px-3 py-2 border-b">Filed Date</th>
              <th className="px-3 py-2 border-b">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id as string} className="border-b hover:bg-[#F8FAFC]">
                <td className="px-3 py-2 font-medium">{r.form_type as string}</td>
                <td className="px-3 py-2">{r.financial_year as string ?? "—"}</td>
                <td className="px-3 py-2 font-mono text-xs">{r.srn as string ?? "—"}</td>
                <td className="px-3 py-2 text-xs">{r.filed_date as string ?? "—"}</td>
                <td className="px-3 py-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${FILING_STATUS_COLORS[r.status as string] ?? ""}`}>
                    {r.status as string}
                  </span>
                </td>
              </tr>
            ))}
            {loadError ? (
              <tr><td colSpan={5} className="px-3 py-6 text-center">
                <p className="text-sm text-red-600 font-medium">{loadError}</p>
                <button onClick={load} className="mt-2 text-xs px-3 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
              </td></tr>
            ) : rows.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-4 text-center text-[#94A3B8]">No filed records.</td></tr>
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

/**
 * What this page says to a client that cannot file the Companies Act forms.
 *
 * "No companies registered" was the old answer for a proprietorship, and it
 * reads like missing data — as though somebody had forgotten to add the
 * company. The obligation does not exist, so the page says which regime the
 * client is actually in and why. lib/entityObligations.ts is the authority
 * for both the classification and this wording.
 */
function McaOutOfScope({ clientId, entityType }: { clientId: string; entityType: string | null }) {
  const regime = mcaRegime(entityType);
  const note = mcaScopeNote(entityType);
  return (
    <div className="p-6 space-y-6">
      <h2 className="text-xl font-semibold">MCA / ROC Compliance</h2>
      <div className="max-w-2xl space-y-3 rounded-lg border border-[#E2E8F0] bg-[#F8FAFC] p-5">
        <p className="text-sm font-medium text-[#0F172A]">
          {regime === "llp-act"
            ? "An LLP does not file the Companies Act annual forms."
            : "This client has no filings with the Ministry of Corporate Affairs."}
        </p>
        <p className="text-xs leading-relaxed text-[#475569]">{note}</p>
        {regime === "llp-act" && (
          <p className="text-xs leading-relaxed text-[#475569]">
            PracticeSync does not prepare Form 11 or Form 8 yet. Until it does, file them on
            the MCA portal and record the SRN against the client here.
          </p>
        )}
        <Link
          href={`/clients/${clientId}/compliance/`}
          className="inline-block text-xs font-medium text-blue-600 hover:underline"
        >
          Back to Compliance
        </Link>
      </div>
    </div>
  );
}

export default function MCAWorkspacePage() {
  const { clientId } = useClientNav();
  // MCA/ROC is not universal: AOC-4 (§137), MGT-7 (§92) and ADT-1 (§139) bind
  // companies incorporated under the Companies Act 2013, and those are the
  // only forms this workspace implements. An LLP files on the MCA too, but
  // Form 11 / Form 8 under the LLP Act 2008, so it is not a company here.
  const entity = useClientEntityType(clientId);
  const [tab, setTab] = useState<MCATab>("companies");

  if (!clientId || clientId === "_placeholder") {
    return <p className="text-sm text-[#64748B] p-6">Select a client to view MCA workspace.</p>;
  }

  // Never flash the company workspace at a client that will not keep it: wait
  // for the entity type before deciding. On a failed read we fall through to
  // the workspace — the gate is an affordance, not an access control, and a
  // transient failure must not lock a company's CA out of its own filings.
  if (entity.loading) {
    return <div className="p-6"><ListSkeleton rows={4} /></div>;
  }
  if (entity.error === null && !isCompaniesActCompany(entity.entityType)) {
    return <McaOutOfScope clientId={clientId} entityType={entity.entityType} />;
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
                : "border-transparent text-[#64748B] hover:text-[#334155]"
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
