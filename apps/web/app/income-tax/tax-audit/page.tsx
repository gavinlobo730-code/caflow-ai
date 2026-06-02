"use client";

/**
 * Tax Audit Checklist — Form 3CD
 * IT Act Section 44AB — Tax Audit requirement
 * Accordion-style checklist covering all major Form 3CD clauses
 * Save draft to Supabase tax_audit_checklists table
 */

import { useState, useEffect, useCallback } from "react";
import { Save, ChevronDown, ChevronUp, CheckCircle, Circle } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";

interface ClauseValue {
  value: string;
  completed: boolean;
  notes: string;
}

type ClauseType = "text" | "yesno" | "select" | "amount";

interface ClauseDef {
  no: number | string;
  title: string;
  type: ClauseType;
  options?: string[];
  placeholder?: string;
}

// Form 3CD Clauses — IT Act Section 44AB
const CLAUSE_GROUPS: { title: string; clauses: ClauseDef[] }[] = [
  {
    title: "Basic Details (Clauses 1–8)",
    clauses: [
      { no: 1, title: "Name of assessee", type: "text", placeholder: "Full name as per PAN" },
      { no: 2, title: "Address", type: "text", placeholder: "Registered address" },
      { no: 3, title: "PAN", type: "text", placeholder: "AAAAA9999A" },
      { no: 4, title: "Status (nature of assessee)", type: "select", options: ["Individual", "HUF", "Firm/LLP", "Company", "Trust/AOP", "BOI"] },
      { no: 5, title: "Previous year ended", type: "select", options: ["31-Mar-2026", "31-Mar-2025", "31-Mar-2024"] },
      { no: 6, title: "Assessment year", type: "select", options: ["2026-27", "2025-26", "2024-25"] },
      { no: "7a", title: "Whether liable for audit under any other law?", type: "yesno" },
      { no: 8, title: "Relevant clause of Section 44AB", type: "select", options: ["44AB(a) — Business turnover > ₹1Cr", "44AB(b) — Profession receipts > ₹50L", "44AB(c) — Presumptive income scheme opted", "44AB(d) — TP provisions applicable"] },
    ],
  },
  {
    title: "Financial Information (Clauses 9–16)",
    clauses: [
      { no: 9, title: "Nature of business/profession and code", type: "text", placeholder: "e.g. Manufacturing — 0104" },
      { no: 10, title: "Books of account maintained (list)", type: "text", placeholder: "e.g. Cash book, Ledger, Journal" },
      { no: 11, title: "Books examined — where kept and by whom", type: "text", placeholder: "e.g. At registered office, maintained by XYZ & Co." },
      { no: 12, title: "Presumptive income scheme (44AD/44ADA/44AE)?", type: "yesno" },
      { no: 13, title: "Method of accounting", type: "select", options: ["Mercantile (Accrual)", "Cash Basis"] },
      { no: 14, title: "Method of stock valuation", type: "select", options: ["FIFO", "LIFO", "Weighted Average", "Specific Identification", "N/A"] },
      { no: 15, title: "Capital assets converted to stock-in-trade?", type: "yesno" },
      { no: 16, title: "Amounts not credited to P&L (details)", type: "text", placeholder: "Specify items not credited, if any" },
    ],
  },
  {
    title: "Key Compliance Clauses",
    clauses: [
      { no: 17, title: "Expenditure debited to P&L but disallowable (Section 37)", type: "amount", placeholder: "Amount ₹" },
      { no: 19, title: "Amounts inadmissible under Section 40(a) — TDS default", type: "amount", placeholder: "Amount ₹" },
      { no: 21, title: "Payments to related parties / specified persons", type: "text", placeholder: "Details of related party transactions" },
      { no: 26, title: "Section 43B deferred payments (MSME, PF, ESI, etc.)", type: "text", placeholder: "Amounts deferred beyond due date" },
      { no: 34, title: "TDS/TCS compliance — whether deducted and deposited on time", type: "yesno" },
      { no: 44, title: "GST — registered, returns filed, ITC reconciled", type: "text", placeholder: "GSTIN, filing status, ITC differences if any" },
    ],
  },
];

// Total clauses
const ALL_CLAUSES: ClauseDef[] = CLAUSE_GROUPS.flatMap(g => g.clauses);
const TOTAL = ALL_CLAUSES.length;

function makeDefault(): Record<string, ClauseValue> {
  const d: Record<string, ClauseValue> = {};
  for (const c of ALL_CLAUSES) {
    d[String(c.no)] = { value: "", completed: false, notes: "" };
  }
  return d;
}

interface ClauseRowProps {
  clause: ClauseDef;
  value: ClauseValue;
  onChange: (v: ClauseValue) => void;
}

function ClauseRow({ clause, value, onChange }: ClauseRowProps) {
  return (
    <div className={`border-b border-gray-100 last:border-0 px-4 py-3 ${value.completed ? "bg-green-50/40" : ""}`}>
      <div className="flex items-start gap-3">
        <button onClick={() => onChange({ ...value, completed: !value.completed })} className="mt-0.5 shrink-0">
          {value.completed
            ? <CheckCircle size={16} className="text-green-500" />
            : <Circle size={16} className="text-gray-300" />}
        </button>
        <div className="flex-1 space-y-2">
          <div className="flex items-start justify-between gap-2">
            <span className="text-sm font-medium text-gray-800">
              <span className="text-gray-400 mr-1">Clause {clause.no}:</span>{clause.title}
            </span>
          </div>

          {clause.type === "text" && (
            <input type="text" value={value.value} placeholder={clause.placeholder}
              onChange={e => onChange({ ...value, value: e.target.value })}
              className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm outline-none focus:border-blue-500" />
          )}

          {clause.type === "amount" && (
            <div className="flex items-center gap-1">
              <span className="text-sm text-gray-400">₹</span>
              <input type="number" min="0" value={value.value} placeholder="0"
                onChange={e => onChange({ ...value, value: e.target.value })}
                className="w-40 border border-gray-200 rounded-lg px-3 py-1.5 text-sm outline-none focus:border-blue-500" />
            </div>
          )}

          {clause.type === "yesno" && (
            <div className="flex gap-3">
              {["Yes", "No", "N/A"].map(opt => (
                <label key={opt} className="flex items-center gap-1.5 text-sm text-gray-700 cursor-pointer">
                  <input type="radio" name={`clause-${clause.no}`} value={opt}
                    checked={value.value === opt}
                    onChange={() => onChange({ ...value, value: opt })} />
                  {opt}
                </label>
              ))}
            </div>
          )}

          {clause.type === "select" && clause.options && (
            <select value={value.value} onChange={e => onChange({ ...value, value: e.target.value })}
              className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm outline-none focus:border-blue-500">
              <option value="">— Select —</option>
              {clause.options.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          )}

          <input type="text" value={value.notes} placeholder="Notes (optional)"
            onChange={e => onChange({ ...value, notes: e.target.value })}
            className="w-full border border-gray-100 rounded-lg px-3 py-1 text-xs text-gray-500 outline-none focus:border-blue-300 bg-gray-50" />
        </div>
      </div>
    </div>
  );
}

function GroupAccordion({ group, values, onChange }: {
  group: { title: string; clauses: ClauseDef[] };
  values: Record<string, ClauseValue>;
  onChange: (key: string, v: ClauseValue) => void;
}) {
  const [open, setOpen] = useState(true);
  const completed = group.clauses.filter(c => values[String(c.no)]?.completed).length;

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <button onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50">
        <span className="font-medium text-gray-900 text-sm">{group.title}</span>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400">{completed}/{group.clauses.length} done</span>
          {open ? <ChevronUp size={15} className="text-gray-400" /> : <ChevronDown size={15} className="text-gray-400" />}
        </div>
      </button>
      {open && group.clauses.map(clause => (
        <ClauseRow key={String(clause.no)} clause={clause}
          value={values[String(clause.no)] ?? { value: "", completed: false, notes: "" }}
          onChange={v => onChange(String(clause.no), v)} />
      ))}
    </div>
  );
}

const FY_OPTIONS = ["2026-27", "2025-26", "2024-25"];

export default function TaxAuditPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState("");
  const [fy, setFy] = useState(FY_OPTIONS[0]);
  const [clauses, setClauses] = useState<Record<string, ClauseValue>>(makeDefault());
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  useEffect(() => {
    getClients().then(c => { setClients(c); if (c.length > 0) setClientId(c[0].id); }).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    if (!clientId) return;
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();
      const { data } = await sb.from("tax_audit_checklists")
        .select("clauses_json")
        .eq("firm_id", firmId)
        .eq("client_id", clientId)
        .eq("fy", fy)
        .maybeSingle();
      if (data?.clauses_json) {
        setClauses({ ...makeDefault(), ...(data.clauses_json as Record<string, ClauseValue>) });
      } else {
        setClauses(makeDefault());
      }
    } catch {
      // Table may not exist — use default
      setClauses(makeDefault());
    }
  }, [clientId, fy]);

  useEffect(() => { load(); }, [load]);

  function handleClauseChange(key: string, v: ClauseValue) {
    setClauses(prev => ({ ...prev, [key]: v }));
  }

  const completedCount = Object.values(clauses).filter(v => v.completed).length;

  async function handleSave() {
    if (!clientId) return;
    setSaving(true);
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();
      const now = new Date().toISOString();
      const { error } = await sb.from("tax_audit_checklists").upsert({
        firm_id: firmId,
        client_id: clientId,
        fy,
        clauses_json: clauses,
        completed_count: completedCount,
        total_count: TOTAL,
        updated_at: now,
      }, { onConflict: "firm_id,client_id,fy" });
      if (error) throw new Error(error.message);
      setSaveMsg("Draft saved");
      setTimeout(() => setSaveMsg(null), 3000);
    } catch (e) {
      setSaveMsg(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  const progressPct = Math.round((completedCount / TOTAL) * 100);

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-lg md:text-xl font-semibold text-gray-900">Tax Audit Checklist — Form 3CD</h1>
          <p className="text-sm text-gray-500 mt-0.5">IT Act Section 44AB — Statement of Particulars</p>
        </div>
        <button onClick={handleSave} disabled={saving || !clientId}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-60">
          <Save size={15} /> {saving ? "Saving…" : "Save Draft"}
        </button>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap gap-3">
        <select value={clientId} onChange={e => setClientId(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500">
          {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
        </select>
        <select value={fy} onChange={e => setFy(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500">
          {FY_OPTIONS.map(f => <option key={f} value={f}>FY {f}</option>)}
        </select>
      </div>

      {/* Progress bar */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-2">
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium text-gray-800">{completedCount} of {TOTAL} clauses completed</span>
          <span className="text-gray-500">{progressPct}%</span>
        </div>
        <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden">
          <div className={`h-full rounded-full transition-all ${progressPct === 100 ? "bg-green-500" : "bg-blue-500"}`}
            style={{ width: `${progressPct}%` }} />
        </div>
        {saveMsg && <p className="text-xs text-green-600">{saveMsg}</p>}
      </div>

      {/* Clause groups */}
      {CLAUSE_GROUPS.map(group => (
        <GroupAccordion key={group.title} group={group} values={clauses} onChange={handleClauseChange} />
      ))}
    </div>
  );
}
