"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import {
  ChevronLeft, Plus, Pencil, FileText, AlertCircle, CheckCircle2,
  IndianRupee, Users, ExternalLink, X, Power,
} from "lucide-react";
import { formatPaise } from "@/lib/services/formatting";
import { getClients } from "@/lib/data/clients";
import { api, type BillingSchedule } from "@/lib/api";
import type { Client } from "@/lib/types";
import { paiseFromRupeeInput, rupeeInputFromPaise, bpsFromPercentInput } from "@/lib/money/rupeeInput";
import { todayLocalISO } from "@/lib/dateMath";

// ─── What changed here, and why (ACC-06) ────────────────────────────────────
//
// This screen used to keep retainers, a work checklist and "invoices" in three
// localStorage keys, and that was the least of it. It MINTED a document:
//
//   * headed TAX INVOICE, under the firm's own name and GSTIN;
//   * numbered `CAF/<year>/NNNN` from a counter over the browser's own list,
//     so two devices produce the same number and CGST Rule 46(b)'s "consecutive
//     serial number ... unique for a financial year" cannot hold;
//   * taxed at a hardcoded CGST 9% + SGST 9%, so it was simply the wrong tax
//     for any client outside the firm's own state, where IGST 18% applies;
//   * with a Print button, and "Save Invoice" saving it to localStorage.
//
// A CA could hand that to a client. It existed in no ledger, no GSTR-1 and no
// receivable.
//
// NONE OF IT NEEDED BUILDING. `billing_schedules` (migration 073) has carried
// `arrangement IN ('retainer','one_time','package')` since 2024;
// `services/billing_service.py` generates a DRAFT invoice per schedule per
// period, idempotently, THROUGH THE SALES ENGINE — so GST, place of supply and
// the firm's real numbering series are the real ones — and
// `api.billing.listSchedules / createSchedule / generate` were already in the
// frontend client with no callers. This screen now calls them.
//
// The WORK CHECKLIST is not rebuilt here. Four booleans per client per month
// about whether GSTR-1, GSTR-3B and the TDS return were filed is
// `compliance_obligations`, which is built and is per client — so the screen
// links to the client's own Compliance tab instead of keeping a second,
// private answer to a question the platform already answers.

const CADENCES = [
  { value: "monthly", label: "Monthly" },
  { value: "quarterly", label: "Quarterly" },
  { value: "annual", label: "Annual" },
] as const;

type ServiceOption = { id: string; name: string };

// ─── SetRetainerModal ─────────────────────────────────────────────────────────

function SetRetainerModal({
  client, existing, services, onSaved, onClose,
}: {
  client: Client;
  existing: BillingSchedule | undefined;
  services: ServiceOption[];
  onSaved: () => void;
  onClose: () => void;
}) {
  const [feeRupees, setFeeRupees] = useState(
    existing ? rupeeInputFromPaise(existing.amount_paise) : "");
  const [gstPercent, setGstPercent] = useState(
    existing ? String(existing.gst_rate) : "18");
  const [cadence, setCadence] = useState<string>(existing?.cadence ?? "monthly");
  const [serviceId, setServiceId] = useState<string>(existing?.service_id ?? "");
  const [nextRun, setNextRun] = useState<string>(existing?.next_run_date ?? todayLocalISO());
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    // Through the one parser. parseFloat("1,25,000") is 1, and a retainer is
    // billed unattended every month, so a fee read wrong is wrong twelve times.
    const feePaise = paiseFromRupeeInput(feeRupees);
    if (feePaise === null || feePaise <= 0) {
      setError("That isn't an amount — enter rupees, like 15000 or 15000.50.");
      return;
    }
    const gstBps = bpsFromPercentInput(gstPercent);
    if (gstBps === null || gstBps < 0) {
      setError("GST rate must be a percentage, like 18.");
      return;
    }
    if (!serviceId) {
      setError("Choose the product or service this retainer bills for.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const body = {
        arrangement: "retainer",
        cadence,
        amount_paise: feePaise,
        gst_rate: gstBps / 100,
        service_id: serviceId,
        next_run_date: nextRun || null,
        // NO `description`. `billing_schedules` has no such column (migration
        // 073); `BillingScheduleIn` accepts one and the service drops it, so a
        // box here would take a CA's words and discard them — and on the PATCH
        // path PostgREST would reject the whole row, failing the fee change
        // beside it. The generated line reads "Professional fees" until the
        // column exists.
      };
      const res = existing
        ? await api.billing.updateSchedule(existing.id, body)
        : await api.billing.createSchedule({ ...body, client_id: client.id });
      if (!res.success) throw new Error(res.error ?? "Failed to save");
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-5 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[#0F172A]">
            {existing ? "Edit" : "Set"} Retainer — {client.client_name}
          </h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]" aria-label="Close">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div>
          <label htmlFor="retainer-fee" className="text-xs font-medium text-[#334155] block mb-1">Fee per period (₹)</label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8] text-sm">₹</span>
            <input
              id="retainer-fee"
              type="text"
              inputMode="decimal"
              className="w-full border border-[#E2E8F0] rounded-lg pl-7 pr-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="15000"
              value={feeRupees}
              onChange={e => { setFeeRupees(e.target.value); setError(null); }}
            />
          </div>
          <p className="text-[10px] text-[#94A3B8] mt-1">Stored as integer paise</p>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="retainer-cadence" className="text-xs font-medium text-[#334155] block mb-1">Billing cycle</label>
            <select
              id="retainer-cadence"
              className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={cadence}
              onChange={e => setCadence(e.target.value)}
            >
              {CADENCES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="retainer-gst" className="text-xs font-medium text-[#334155] block mb-1">GST rate (%)</label>
            <input
              id="retainer-gst"
              type="text"
              inputMode="decimal"
              className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={gstPercent}
              onChange={e => { setGstPercent(e.target.value); setError(null); }}
            />
          </div>
        </div>

        <div>
          <label htmlFor="retainer-service" className="text-xs font-medium text-[#334155] block mb-1">Product / Service</label>
          <select
            id="retainer-service"
            className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={serviceId}
            onChange={e => { setServiceId(e.target.value); setError(null); }}
          >
            <option value="">Select…</option>
            {services.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <p className="text-[10px] text-[#94A3B8] mt-1">
            The invoice line comes from the practice&apos;s own service catalogue, so
            the SAC and rate are the ones already recorded.
          </p>
        </div>

        <div>
          <label htmlFor="retainer-next" className="text-xs font-medium text-[#334155] block mb-1">Next invoice due</label>
          <input
            id="retainer-next"
            type="date"
            className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={nextRun}
            onChange={e => setNextRun(e.target.value)}
          />
        </div>

        {error && <p className="text-[11px] text-red-600">{error}</p>}

        <div className="flex gap-2 pt-1">
          <button onClick={onClose} className="flex-1 border border-[#E2E8F0] text-[#475569] text-sm py-2 rounded-lg hover:bg-[#F8FAFC]">
            Cancel
          </button>
          <button
            disabled={saving}
            onClick={handleSave}
            className="flex-1 bg-blue-600 text-white text-sm py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save Retainer"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function RetainerPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [schedules, setSchedules] = useState<BillingSchedule[]>([]);
  const [services, setServices] = useState<ServiceOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [modalClient, setModalClient] = useState<Client | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [practiceProvisioned, setPracticeProvisioned] = useState<boolean | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cs, res] = await Promise.all([getClients(), api.billing.listSchedules()]);
      setClients(cs);
      if (!res.success) throw new Error(res.error ?? "Failed to load retainers");
      setSchedules(((res.data ?? []) as BillingSchedule[]).filter(s => s.arrangement === "retainer"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // The practice bills its own clients out of its INTERNAL client's books, so
  // the catalogue a retainer picks from is that client's. The server resolves
  // which client that is — the browser never learns the internal-client
  // concept — and `internal_client_id: null` means it is not provisioned,
  // which is exactly what `generate` would 409 on, so the screen says it now
  // rather than at the click.
  useEffect(() => {
    let cancelled = false;
    api.billing.serviceOptions()
      .then(res => {
        if (cancelled || !res.success) return;
        setServices((res.data.services ?? []).map(x => ({ id: x.id, name: x.name })));
        setPracticeProvisioned(res.data.internal_client_id !== null);
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  const byClient = useMemo(() => {
    const m = new Map<string, BillingSchedule>();
    for (const s of schedules) if (!m.has(s.client_id)) m.set(s.client_id, s);
    return m;
  }, [schedules]);

  const active = schedules.filter(s => s.is_active);
  const totalPerPeriod = active.reduce((sum, s) => sum + s.amount_paise, 0);
  const dueNow = active.filter(s => s.next_run_date && s.next_run_date <= todayLocalISO());

  async function generate(schedule: BillingSchedule) {
    setBusyId(schedule.id);
    setError(null);
    setNotice(null);
    try {
      const res = await api.billing.generate(schedule.id);
      if (!res.success) throw new Error(res.error ?? "Failed to generate");
      const out = res.data;
      setNotice(out.created
        ? `Draft invoice created for ${out.period}. Review and issue it from Billing — nothing is posted or sent until you do.`
        : `An invoice for ${out.period} already exists. Nothing was created.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate");
    } finally {
      setBusyId(null);
    }
  }

  async function toggleActive(schedule: BillingSchedule) {
    setBusyId(schedule.id);
    setError(null);
    try {
      const res = await api.billing.updateSchedule(schedule.id, { is_active: !schedule.is_active });
      if (!res.success) throw new Error(res.error ?? "Failed to update");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-[#94A3B8] hover:text-[#475569]">
          <ChevronLeft size={18} />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-[#0F172A]">Monthly Retainer Tracker</h1>
          <p className="text-sm text-[#64748B] mt-0.5">
            Fixed-fee arrangements, saved for the firm. Generating raises a real draft
            invoice in the practice&apos;s books.
          </p>
        </div>
        <Link
          href="/billing"
          className="flex items-center gap-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md hover:bg-[#F8FAFC]"
        >
          Billing <ExternalLink size={13} />
        </Link>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-100 rounded-lg px-4 py-3 flex gap-2 text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}
      {notice && (
        <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 flex gap-2 text-sm text-blue-800">
          <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{notice}</span>
        </div>
      )}

      {practiceProvisioned === false && (
        <div className="bg-amber-50 border border-amber-100 rounded-lg px-4 py-3 flex gap-2 text-sm text-amber-900">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>
            The firm&apos;s own practice client is not provisioned, so an invoice
            has no books to be raised in. Retainers can be recorded; generating
            one will be refused until it exists.
          </span>
        </div>
      )}
      {practiceProvisioned === true && services.length === 0 && (
        <div className="bg-amber-50 border border-amber-100 rounded-lg px-4 py-3 flex gap-2 text-sm text-amber-900">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>
            The practice&apos;s service catalogue is empty. A retainer bills a
            recorded product or service — add one before setting a fee, so the
            invoice line carries the SAC you actually use.
          </span>
        </div>
      )}

      {/* Summary */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center">
              <Users className="w-4 h-4 text-blue-600" />
            </div>
            <span className="text-xs text-[#64748B]">Active retainers</span>
          </div>
          <p className="text-lg font-semibold text-[#0F172A]">{loading ? "—" : active.length}</p>
          <p className="text-xs text-[#94A3B8] mt-0.5">of {clients.length} clients</p>
        </div>
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-green-50 flex items-center justify-center">
              <IndianRupee className="w-4 h-4 text-green-600" />
            </div>
            <span className="text-xs text-[#64748B]">Fees per period</span>
          </div>
          <p className="text-lg font-semibold text-[#0F172A]">{loading ? "—" : formatPaise(totalPerPeriod)}</p>
          <p className="text-xs text-[#94A3B8] mt-0.5">Sum of active retainers, before GST</p>
        </div>
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-amber-50 flex items-center justify-center">
              <FileText className="w-4 h-4 text-amber-600" />
            </div>
            <span className="text-xs text-[#64748B]">Due to invoice</span>
          </div>
          <p className="text-lg font-semibold text-[#0F172A]">{loading ? "—" : dueNow.length}</p>
          <p className="text-xs text-[#94A3B8] mt-0.5">Next run date reached</p>
        </div>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50">
          <h2 className="text-sm font-semibold text-[#0F172A]">Retainer clients</h2>
          <p className="text-xs text-[#94A3B8] mt-0.5">
            Generating creates a DRAFT — review and issue it from Billing. Nothing is
            posted to the ledger or sent to the client until you do.
          </p>
        </div>

        {loading ? (
          <div className="px-5 py-8 text-center text-sm text-[#94A3B8]">Loading…</div>
        ) : clients.length === 0 ? (
          <div className="px-5 py-8 text-center text-sm text-[#94A3B8]">No clients found — add clients first</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-50">
                  <th className="text-left text-xs font-medium text-[#94A3B8] px-5 py-3">Client</th>
                  <th className="text-right text-xs font-medium text-[#94A3B8] px-3 py-3">Fee</th>
                  <th className="text-left text-xs font-medium text-[#94A3B8] px-3 py-3">Cycle</th>
                  <th className="text-left text-xs font-medium text-[#94A3B8] px-3 py-3">Next due</th>
                  <th className="text-left text-xs font-medium text-[#94A3B8] px-3 py-3">Compliance</th>
                  <th className="text-left text-xs font-medium text-[#94A3B8] px-5 py-3">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {clients.map(client => {
                  const sched = byClient.get(client.id);
                  const busy = sched ? busyId === sched.id : false;
                  return (
                    <tr key={client.id} className="hover:bg-[#F8FAFC]/50">
                      <td className="px-5 py-3">
                        <p className="text-sm font-medium text-[#0F172A]">{client.client_name}</p>
                        {client.gstin && <p className="text-[10px] font-mono text-[#94A3B8]">{client.gstin}</p>}
                      </td>
                      <td className="px-3 py-3 text-right">
                        {sched
                          ? <span className={`text-sm font-semibold ${sched.is_active ? "text-[#0F172A]" : "text-[#94A3B8] line-through"}`}>
                              {formatPaise(sched.amount_paise)}
                            </span>
                          : <span className="text-xs text-[#CBD5E1]">Not set</span>}
                      </td>
                      <td className="px-3 py-3 text-xs text-[#475569]">
                        {sched ? (CADENCES.find(c => c.value === sched.cadence)?.label ?? sched.cadence) : "—"}
                      </td>
                      <td className="px-3 py-3 text-xs text-[#475569]">
                        {sched?.next_run_date ?? "—"}
                      </td>
                      <td className="px-3 py-3">
                        {/* Whether this month's returns are filed is
                            compliance_obligations, per client — not four
                            booleans kept in one browser. */}
                        <Link
                          href={`/clients/${client.id}/compliance`}
                          className="text-xs text-blue-600 hover:text-blue-800 inline-flex items-center gap-1"
                        >
                          View <ExternalLink size={11} />
                        </Link>
                      </td>
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-3">
                          <button
                            onClick={() => setModalClient(client)}
                            className="text-xs text-blue-600 hover:text-blue-800 font-medium whitespace-nowrap flex items-center gap-1"
                          >
                            {sched ? <Pencil className="w-3 h-3" /> : <Plus className="w-3 h-3" />}
                            {sched ? "Edit" : "Set"} retainer
                          </button>
                          {sched && sched.is_active && (
                            <button
                              disabled={busy}
                              onClick={() => generate(sched)}
                              className="text-xs text-green-700 hover:text-green-900 font-medium whitespace-nowrap flex items-center gap-1 disabled:opacity-40"
                            >
                              <FileText className="w-3 h-3" />
                              {busy ? "Working…" : "Generate draft invoice"}
                            </button>
                          )}
                          {sched && (
                            <button
                              disabled={busy}
                              onClick={() => toggleActive(sched)}
                              className="text-xs text-[#94A3B8] hover:text-[#475569] whitespace-nowrap flex items-center gap-1 disabled:opacity-40"
                            >
                              <Power className="w-3 h-3" />
                              {sched.is_active ? "Pause" : "Resume"}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {modalClient && (
        <SetRetainerModal
          client={modalClient}
          existing={byClient.get(modalClient.id)}
          services={services}
          onSaved={load}
          onClose={() => setModalClient(null)}
        />
      )}
    </div>
  );
}
