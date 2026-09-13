"use client";

/**
 * Tax Audit Tracker — IT Act Section 44AB
 * Applicability is decided by apps/api/domain/income_tax/tax_audit.py — §44AB(a)
 * for a business, §44AB(b) for a profession, on figures this file does not hold
 * Form 3CA-3CD (for companies audited u/s 44AB(a)) or 3CB-3CD (others)
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
 *
 * All amounts in integer paise (never floating point).
 */

import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, Plus, X, CheckCircle, Clock, AlertTriangle, Pencil } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { TableSkeleton } from "@/components/ui/skeleton";
import { formatPaise } from "@/lib/services/formatting";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { getClients } from "@/lib/data/clients";
import { api, type TaxAuditDueDates, type TaxAuditApplicability } from "@/lib/api";
import type { Client } from "@/lib/types";
import { financialYearChoicesAround } from "@/lib/dates/periods";

// ─── Types ────────────────────────────────────────────────────────────────────

type AuditStatus = "not_started" | "in_progress" | "completed" | "filed";
type FormType = "3CA-3CD" | "3CB-3CD";

interface TaxAudit {
  id: string;
  firm_id: string;
  client_id: string;
  financial_year: string;
  form_type: FormType;
  status: AuditStatus;
  auditor_name: string | null;
  audit_date: string | null;
  filing_date: string | null;
  udin: string | null;
  ack_number: string | null;
  turnover_paise: number;
  created_at: string;
}

const STATUS_OPTIONS: AuditStatus[] = ["not_started", "in_progress", "completed", "filed"];
// FROM THE CLOCK, NOT A LITERAL. This list ended at a year that is now in the
// past, so the current financial year could not be selected at all — broken on
// 1 April with nothing saying so. `financialYearChoicesAround` is the one
// helper (lib/dates/periods.ts); see
// scripts/a-financial-year-choice-comes-from-the-clock.test.ts.
const FY_OPTIONS = financialYearChoicesAround(null);

/** An ISO date as an Indian compliance screen prints it: 30 Sep 2026. */
function fmtDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function statusBadge(status: AuditStatus) {
  switch (status) {
    case "not_started": return { cls: "text-[#475569] bg-[#F1F5F9]", icon: Clock, label: "Not Started" };
    case "in_progress": return { cls: "text-blue-700 bg-blue-50", icon: Clock, label: "In Progress" };
    case "completed": return { cls: "text-amber-700 bg-amber-50", icon: CheckCircle, label: "Completed" };
    case "filed": return { cls: "text-green-700 bg-green-50", icon: CheckCircle, label: "Filed" };
  }
}

// ─── Add / Edit Modal ─────────────────────────────────────────────────────────

interface AuditFormState {
  clientId: string;
  financialYear: string;
  formType: FormType;
  status: AuditStatus;
  auditorName: string;
  auditDate: string;
  filingDate: string;
  udin: string;
  ackNumber: string;
  turnoverRs: string;
  // NOT persisted — tax_audits has no column for any of these, and they are
  // inputs to a live §44AB check rather than facts about the engagement. The
  // answer states what it was computed on, so nothing is lost by asking again.
  nature: "business" | "profession";
  cashReceiptsRs: string;
  cashPaymentsRs: string;
  totalPaymentsRs: string;
}

const BLANK: AuditFormState = {
  clientId: "",
  financialYear: FY_OPTIONS[0],
  formType: "3CB-3CD",
  status: "not_started",
  auditorName: "",
  auditDate: "",
  filingDate: "",
  udin: "",
  ackNumber: "",
  turnoverRs: "",
  // No default. §44AB(a) and (b) are different clauses and the app does not
  // hold which one a client is on, so the CA says — guessing "business" is
  // exactly the inference this replaced, moved one step earlier.
  nature: "business",
  cashReceiptsRs: "",
  cashPaymentsRs: "",
  totalPaymentsRs: "",
};

function AuditModal({ clients, editAudit, onClose, onSaved }: {
  clients: Client[];
  editAudit: TaxAudit | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<AuditFormState>(() => {
    if (!editAudit) return { ...BLANK, clientId: clients[0]?.id ?? "" };
    return {
      clientId: editAudit.client_id,
      financialYear: editAudit.financial_year,
      formType: editAudit.form_type,
      status: editAudit.status,
      auditorName: editAudit.auditor_name ?? "",
      auditDate: editAudit.audit_date ?? "",
      filingDate: editAudit.filing_date ?? "",
      udin: editAudit.udin ?? "",
      ackNumber: editAudit.ack_number ?? "",
      turnoverRs: editAudit.turnover_paise > 0 ? (editAudit.turnover_paise / 100).toFixed(2) : "",
      nature: "business",
      cashReceiptsRs: "",
      cashPaymentsRs: "",
      totalPaymentsRs: "",
    };
  });

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── §44AB applicability, ASKED not decided (IT-11) ───────────────────────
  // The badge under the turnover box used to be three lines of TypeScript
  // comparing the amount against two constants, and it read the NATURE of the
  // activity off the AMOUNT: above ₹1 crore it said "business", between
  // ₹50 lakh and ₹1 crore it said "profession". So a trader with ₹60 lakh of
  // turnover — whom §44AB(a) does not reach — was told an audit was
  // mandatory, and it never applied the proviso to §44AB(a) at all.
  // domain/income_tax/tax_audit.py is the authority now; this asks it.
  const [applicability, setApplicability] = useState<TaxAuditApplicability | null>(null);
  const [applicabilityError, setApplicabilityError] = useState<string | null>(null);
  const [showProviso, setShowProviso] = useState(false);

  const cashReceiptsPaise = form.cashReceiptsRs ? paiseFromRupeeInput(form.cashReceiptsRs) : null;
  const cashPaymentsPaise = form.cashPaymentsRs ? paiseFromRupeeInput(form.cashPaymentsRs) : null;
  const totalPaymentsPaise = form.totalPaymentsRs ? paiseFromRupeeInput(form.totalPaymentsRs) : null;

  const client = clients.find(c => c.id === form.clientId);
  const isCompany = /company|pvt|private limited|limited/i.test(String(client?.entity_type ?? ""));

  useEffect(() => {
    // Nothing typed is not the same as zero: an empty box asks nothing.
    const typed = paiseFromRupeeInput(form.turnoverRs);
    if (!form.turnoverRs || typed === null) {
      setApplicability(null);
      setApplicabilityError(null);
      return;
    }
    let cancelled = false;
    // Debounced — the box is typed a digit at a time and each keystroke would
    // otherwise be a request, with the answers arriving out of order.
    const t = setTimeout(() => {
      api.incomeTax.taxAuditApplicability({
        nature: form.nature,
        turnover_paise: typed,
        financial_year: form.financialYear,
        cash_receipts_paise: cashReceiptsPaise ?? undefined,
        cash_payments_paise: cashPaymentsPaise ?? undefined,
        total_payments_paise: totalPaymentsPaise ?? undefined,
        is_company: isCompany,
      }).then(r => {
        if (cancelled) return;
        if (r.success && r.data) { setApplicability(r.data); setApplicabilityError(null); }
        // A refusal is SHOWN. The old badge could not fail, so it always said
        // something — which is how it came to say something wrong.
        else { setApplicability(null); setApplicabilityError(r.error ?? "Couldn't check §44AB."); }
      }).catch(() => {
        if (!cancelled) { setApplicability(null); setApplicabilityError("Couldn't check §44AB."); }
      });
    }, 400);
    return () => { cancelled = true; clearTimeout(t); };
  }, [form.turnoverRs, form.nature, form.financialYear,
      cashReceiptsPaise, cashPaymentsPaise, totalPaymentsPaise, isCompany]);

  function upd(patch: Partial<AuditFormState>) { setForm(f => ({ ...f, ...patch })); }
  const inputCls = "w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500";
  const lbl = "text-xs font-medium text-[#334155] block mb-1";

  async function handleSave() {
    if (!form.clientId) { setError("Select a client"); return; }
    // All money in integer paise — no floating point
    // This turnover decides whether a s.44AB tax audit applies at all. Read as
    // ₹1 because it was typed "1,20,00,000", it says no audit is required for a
    // client 12 crore over the threshold.
    const turnoverPaise = form.turnoverRs ? paiseFromRupeeInput(form.turnoverRs) : 0;
    if (turnoverPaise === null) {
      setError("Turnover must be an amount in rupees, e.g. 12000000 — without commas.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();
      const payload = {
        firm_id: firmId,
        client_id: form.clientId,
        financial_year: form.financialYear,
        form_type: form.formType,
        status: form.status,
        auditor_name: form.auditorName || null,
        audit_date: form.auditDate || null,
        filing_date: form.filingDate || null,
        udin: form.udin || null,
        ack_number: form.ackNumber || null,
        turnover_paise: turnoverPaise,
      };
      if (editAudit) {
        const { error: err } = await sb.from("tax_audits").update(payload).eq("id", editAudit.id);
        if (err) throw new Error(err.message);
      } else {
        const { error: err } = await sb.from("tax_audits").insert(payload);
        if (err) throw new Error(err.message);
      }
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-white flex items-center justify-between px-6 py-4 border-b border-[#F1F5F9]">
          <h3 className="text-sm font-semibold text-[#0F172A]">{editAudit ? "Edit Tax Audit" : "Add Tax Audit"}</h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
        </div>
        <div className="px-6 py-4 space-y-3">
          {error && <div className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</div>}
          <div>
            <label className={lbl}>Client *</label>
            <ClientLookup
              clients={clients}
              value={form.clientId}
              onChange={(id) => upd({ clientId: id })}
              ariaLabel="Client"
              placeholder="Select client…"
              disabled={!!editAudit}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={lbl}>Financial Year</label>
              <select value={form.financialYear} onChange={e => upd({ financialYear: e.target.value })} className={inputCls} disabled={!!editAudit}>
                {FY_OPTIONS.map(f => <option key={f} value={f}>FY {f}</option>)}
              </select>
            </div>
            <div>
              <label className={lbl}>Form Type</label>
              <select value={form.formType} onChange={e => upd({ formType: e.target.value as FormType })} className={inputCls}>
                <option value="3CB-3CD">Form 3CB-3CD (Non-company)</option>
                <option value="3CA-3CD">Form 3CA-3CD (Company)</option>
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={lbl}>Turnover / Gross Receipts (₹)</label>
              <input type="number" min="0" step="0.01" value={form.turnoverRs} onChange={e => upd({ turnoverRs: e.target.value })} className={inputCls} placeholder="Enter turnover for threshold check" />
            </div>
            <div>
              {/* §44AB(a) and (b) are different clauses. Which applies is a
                  fact about the client, and the CA states it — the screen used
                  to infer it from the amount, which is how a ₹60 lakh trader
                  was told a profession's threshold applied to them. */}
              <label className={lbl}>Nature of activity (§44AB)</label>
              <select value={form.nature} onChange={e => upd({ nature: e.target.value as "business" | "profession" })} className={inputCls}>
                <option value="business">Business — §44AB(a)</option>
                <option value="profession">Profession — §44AB(b)</option>
              </select>
            </div>
          </div>

          {/* THE PROVISO TO §44AB(a), behind a disclosure because most clients
              do not need it and an always-open block of three more amount
              boxes is how a form stops being read. Absent, the base figure
              applies — the direction that cannot cause a missed audit. */}
          {form.nature === "business" && (
            <div className="border border-[#E2E8F0] rounded-lg">
              <button
                type="button"
                onClick={() => setShowProviso(v => !v)}
                className="w-full text-left px-3 py-2 text-xs font-medium text-[#334155] flex items-center justify-between"
              >
                <span>Cash receipts and payments (the proviso to §44AB(a))</span>
                <span className="text-[#94A3B8]">{showProviso ? "−" : "+"}</span>
              </button>
              {showProviso && (
                <div className="px-3 pb-3 space-y-3">
                  <p className="text-xs text-[#64748B]">
                    The proviso reads clause (a) with a higher figure where cash receipts
                    AND cash payments are each within a small share of their own aggregate.
                    Both sides are needed — the payments side has its own denominator,
                    which turnover cannot supply — and leaving any of the three blank
                    applies the base figure, which is the direction that cannot cause a
                    missed audit. A cheque or bank draft that is not account payee counts
                    as cash for this test. The answer below states the figures it used.
                  </p>
                  <div className="grid grid-cols-3 gap-3">
                    <div>
                      <label className={lbl}>Cash receipts (₹)</label>
                      <input type="number" min="0" step="0.01" value={form.cashReceiptsRs} onChange={e => upd({ cashReceiptsRs: e.target.value })} className={inputCls} />
                    </div>
                    <div>
                      <label className={lbl}>Cash payments (₹)</label>
                      <input type="number" min="0" step="0.01" value={form.cashPaymentsRs} onChange={e => upd({ cashPaymentsRs: e.target.value })} className={inputCls} />
                    </div>
                    <div>
                      <label className={lbl}>Total payments (₹)</label>
                      <input type="number" min="0" step="0.01" value={form.totalPaymentsRs} onChange={e => upd({ totalPaymentsRs: e.target.value })} className={inputCls} />
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {applicabilityError && (
            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
              {applicabilityError}
            </p>
          )}
          {applicability && (
            <div className={`rounded-lg border px-3 py-2 space-y-2 ${
              applicability.required
                ? "bg-amber-50 border-amber-200"
                : "bg-[#F8FAFC] border-[#E2E8F0]"}`}>
              <p className="text-xs font-medium text-[#0F172A]">{applicability.basis}</p>
              {applicability.required && applicability.report_due_date && (
                <p className="text-xs text-[#334155]">
                  Report (Form {applicability.form_type}) due {applicability.report_due_date};
                  return due {applicability.return_due_date}. Explanation (ii) to §44AB puts
                  the report one month before the §139(1) date.
                </p>
              )}
              {applicability.caveats.length > 0 && (
                <ul className="text-xs text-[#64748B] list-disc pl-4 space-y-1">
                  {applicability.caveats.map((c, i) => <li key={i}>{c}</li>)}
                </ul>
              )}
              {/* Always shown, including on a "not required" answer: §44AB is
                  not exhausted by clauses (a) and (b), and an answer that
                  reads as if it were is the one a CA would rely on. */}
              <details className="text-xs text-[#64748B]">
                <summary className="cursor-pointer">
                  Limbs not tested here ({applicability.limbs_not_tested.length})
                </summary>
                <ul className="list-disc pl-4 mt-1 space-y-1">
                  {applicability.limbs_not_tested.map((l, i) => <li key={i}>{l}</li>)}
                </ul>
              </details>
            </div>
          )}
          <div>
            <label className={lbl}>Status</label>
            <select value={form.status} onChange={e => upd({ status: e.target.value as AuditStatus })} className={inputCls}>
              {STATUS_OPTIONS.map(s => <option key={s} value={s}>{statusBadge(s).label}</option>)}
            </select>
          </div>
          <div>
            <label className={lbl}>Auditor Name</label>
            <input type="text" value={form.auditorName} onChange={e => upd({ auditorName: e.target.value })} className={inputCls} placeholder="CA firm / individual name" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={lbl}>Audit Date</label>
              <input type="date" value={form.auditDate} onChange={e => upd({ auditDate: e.target.value })} className={inputCls} />
            </div>
            <div>
              <label className={lbl}>Filing Date</label>
              <input type="date" value={form.filingDate} onChange={e => upd({ filingDate: e.target.value })} className={inputCls} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={lbl}>UDIN</label>
              <input type="text" value={form.udin} onChange={e => upd({ udin: e.target.value })} className={inputCls} placeholder="ICAI UDIN" />
            </div>
            <div>
              <label className={lbl}>Acknowledgement Number</label>
              <input type="text" value={form.ackNumber} onChange={e => upd({ ackNumber: e.target.value })} className={inputCls} placeholder="ITD ack number" />
            </div>
          </div>
        </div>
        <div className="sticky bottom-0 bg-white px-6 py-4 border-t border-[#F1F5F9] flex gap-2 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-[#334155] bg-[#F1F5F9] rounded-lg hover:bg-white/[0.08]">Cancel</button>
          <button onClick={handleSave} disabled={saving} className="px-4 py-2 text-sm text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-60">
            {saving ? "Saving…" : editAudit ? "Update" : "Add Audit"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function TaxAuditPage() {
  const [audits, setAudits] = useState<TaxAudit[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [fyFilter, setFyFilter] = useState(FY_OPTIONS[0]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [editAudit, setEditAudit] = useState<TaxAudit | null>(null);
  // IT-12. The header used to read "Due: 30 November" as a hardcoded string —
  // wrong by two months against the report and by one against the return, and
  // unfixable by any backend change because no backend was involved. Both
  // dates are §44AB Explanation (ii) arithmetic and belong in apps/api
  // (CLAUDE.md), so the page asks.
  const [dueDates, setDueDates] = useState<TaxAuditDueDates | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cls, firmId] = await Promise.all([getClients(), getFirmId()]);
      setClients(cls);
      const sb = getSupabaseClient();
      const { data, error: err } = await sb
        .from("tax_audits")
        .select("*")
        .eq("firm_id", firmId)
        .eq("financial_year", fyFilter)
        .order("created_at", { ascending: false });
      if (err) throw new Error(err.message);
      setAudits((data ?? []) as TaxAudit[]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [fyFilter]);

  useEffect(() => { loadData(); }, [loadData]);

  useEffect(() => {
    let live = true;
    // A failure leaves the dates absent rather than showing a guess: a wrong
    // statutory date on a compliance screen is worse than no date, because the
    // CA acts on it. §271B is 0.5% of turnover, capped at ₹1,50,000.
    api.compliance.taxAuditDueDates(fyFilter)
      .then((r) => { if (live) setDueDates(r.success ? r.data : null); })
      .catch(() => { if (live) setDueDates(null); });
    return () => { live = false; };
  }, [fyFilter]);

  const clientName = (id: string) => clients.find(c => c.id === id)?.client_name ?? id;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/income-tax" className="text-[#94A3B8] hover:text-[#475569]"><ChevronLeft size={18} /></Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-[#0F172A]">Tax Audit Tracker</h1>
          <p className="text-sm text-[#64748B] mt-0.5" title={dueDates?.basis ?? undefined}>
            IT Act Section 44AB — Form 3CA/3CB/3CD
            {dueDates
              ? <> | Report due {fmtDate(dueDates.report_due_date)} · return due {fmtDate(dueDates.return_due_date)}</>
              : <> | due dates unavailable</>}
          </p>
        </div>
        <select value={fyFilter} onChange={e => setFyFilter(e.target.value)}
          className="border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500">
          {FY_OPTIONS.map(f => <option key={f} value={f}>FY {f}</option>)}
        </select>
        <Button size="sm" onClick={() => setShowAdd(true)}>
          <Plus size={14} className="mr-1" /> Add Audit
        </Button>
      </div>

      {/* Notice */}
      <div className="bg-amber-50 border border-amber-200 rounded-xl px-5 py-3 flex items-start gap-3">
        <AlertTriangle size={16} className="text-amber-600 shrink-0 mt-0.5" />
        <p className="text-sm text-amber-800">
          §44AB(a) reaches a business and §44AB(b) a profession, on different figures —
          enter the turnover and say which, and the check below states the answer and
          what it rests on. UDIN required from the ICAI portal for every audit report.
          {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
        </p>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {STATUS_OPTIONS.map(s => {
          const badge = statusBadge(s);
          return (
            <Card key={s}>
              <CardContent className="pt-4 pb-3">
                <p className="text-2xl font-bold text-[#0F172A]">{audits.filter(a => a.status === s).length}</p>
                <p className="text-xs text-[#64748B] mt-0.5">{badge.label}</p>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {error && <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error}</div>}

      {/* Table */}
      <Card>
        {loading ? (
          <TableSkeleton cols={9} bare />
        ) : audits.length === 0 ? (
          <div className="p-10 text-center text-[#94A3B8] text-sm">
            No tax audits for FY {fyFilter}. Click &quot;Add Audit&quot; to track one.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[900px]">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-xs text-[#94A3B8]">
                  <th className="px-5 py-3 text-left">Client</th>
                  <th className="px-3 py-3 text-left">Form</th>
                  <th className="px-3 py-3 text-right">Turnover</th>
                  <th className="px-3 py-3 text-left">Status</th>
                  <th className="px-3 py-3 text-left">Auditor</th>
                  <th className="px-3 py-3 text-left">Audit Date</th>
                  <th className="px-3 py-3 text-left">Filing Date</th>
                  <th className="px-3 py-3 text-left">UDIN</th>
                  <th className="px-5 py-3 text-left">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {audits.map(a => {
                  const badge = statusBadge(a.status);
                  const Icon = badge.icon;
                  return (
                    <tr key={a.id} className="hover:bg-[#F8FAFC]">
                      <td className="px-5 py-3 text-sm font-medium">{clientName(a.client_id)}</td>
                      <td className="px-3 py-3 text-xs font-mono text-[#475569]">{a.form_type}</td>
                      <td className="px-3 py-3 text-sm tabular-nums text-right">
                        {a.turnover_paise > 0 ? formatPaise(a.turnover_paise) : "—"}
                      </td>
                      <td className="px-3 py-3">
                        <span className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full font-medium ${badge.cls}`}>
                          <Icon size={11} /> {badge.label}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-xs text-[#475569]">{a.auditor_name ?? "—"}</td>
                      <td className="px-3 py-3 text-xs text-[#475569]">{a.audit_date ?? "—"}</td>
                      <td className="px-3 py-3 text-xs text-[#475569]">{a.filing_date ?? "—"}</td>
                      <td className="px-3 py-3 text-xs font-mono text-[#64748B] max-w-[120px] truncate" title={a.udin ?? undefined}>{a.udin ?? "—"}</td>
                      <td className="px-5 py-3">
                        <button onClick={() => setEditAudit(a)}
                          className="flex items-center gap-1 text-xs text-blue-600 hover:underline">
                          <Pencil size={11} /> Edit
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <p className="text-xs text-[#94A3B8] text-center">
        {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
        All audit details are for internal tracking only. UDIN must be verified on the ICAI portal before report submission.
      </p>

      {(showAdd || editAudit) && clients.length > 0 && (
        <AuditModal
          clients={clients}
          editAudit={editAudit}
          onClose={() => { setShowAdd(false); setEditAudit(null); }}
          onSaved={loadData}
        />
      )}
    </div>
  );
}
