"use client";

import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { Receipt, RefreshCw, Plus, CheckCircle2, FileText } from "lucide-react";
import { api, type ApiResp, type BillingGenerateResult } from "@/lib/api";
import { practiceSalesHref } from "@/lib/invoices/workspaceNav";
import { formatPaise } from "@/lib/services/formatting";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";
import { PartnerGuard } from "@/components/practice/PartnerGuard";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { ServiceCataloguePicker } from "@/components/lookups/ServiceCataloguePicker";
import type { ServiceCatalogueItem } from "@/lib/catalogue/service";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/states";
import { EmptyStateAction, EmptyStateActions } from "@/components/ui/empty-state-action";

interface Schedule {
  id: string; client_id: string; arrangement: string; cadence: string;
  amount_paise: number; gst_rate: number; next_run_date: string | null; is_active: boolean;
}

function Billing() {
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  // The invoice a "Generate draft" press produced or found, when the message
  // above is about one: the message links to it in the practice's own sales
  // workspace, where it is checked, numbered, issued and paid (PRE-A-018).
  // `created` tells a draft this press made from one that was already there
  // (which may have been issued since, so it is not called a draft).
  const [msgInvoice, setMsgInvoice] = useState<{ id: string; created: boolean } | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ client_id: "", arrangement: "retainer", cadence: "monthly", amount_rupees: "", gst_rate: "18" });
  const [product, setProduct] = useState<ServiceCatalogueItem | null>(null);
  // The practice's own internal client (Guardrail G1/G2: never shown as a
  // regular client) — its Product/Service catalogue is what a retainer fee
  // gets linked to, same as any other document. GET /api/practice already
  // resolves this server-side and is Partner-gated, matching this page.
  const [internalClientId, setInternalClientId] = useState<string | null>(null);
  // This row's request is in flight. These handlers had no loading state at
  // all, so the button was never disabled and a second click sent it again.
  const [rowBusy, setRowBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await api.billing.listSchedules() as ApiResp<Schedule[]>;
      setSchedules(r.data ?? []);
      setClients(await getClients());
      const p = await api.practice.get() as ApiResp<{ internal_client_id: string | null }>;
      setInternalClientId(p.data?.internal_client_id ?? null);
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load billing"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const clientName = (id: string) => clients.find((c) => c.id === id)?.client_name ?? id.slice(0, 8);

  // One place the banner is set, so a message about a schedule can never keep
  // the previous run's invoice link.
  function say(text: string | null, invoice: { id: string; created: boolean } | null = null) {
    setMsg(text);
    setMsgInvoice(invoice);
  }

  async function createSchedule(e: React.FormEvent) {
    e.preventDefault();
    say(null);
    if (!product) { say("Select a Product/Service for this fee"); return; }
    // A billing schedule bills this amount every cadence until somebody stops
    // it, so an amount read wrong is wrong repeatedly.
    const amountPaise = paiseFromRupeeInput(form.amount_rupees || "0");
    if (amountPaise === null) { setError("Enter the amount in rupees, e.g. 125000 or 125000.50 — without commas."); return; }
    try {
      await api.billing.createSchedule({
        client_id: form.client_id, arrangement: form.arrangement, cadence: form.cadence,
        amount_paise: amountPaise,
        gst_rate: parseFloat(form.gst_rate || "18"),
        service_id: product.id,
      });
      setShowForm(false); setForm({ ...form, client_id: "", amount_rupees: "" }); setProduct(null); await load();
    } catch (e) { say(e instanceof Error ? e.message : "Create failed"); }
  }

  async function generate(scheduleId: string) {
    setRowBusy(true);
    try {
    say(null);
    try {
      const r = await api.billing.generate(scheduleId);
      const result: BillingGenerateResult | undefined = r.data;
      const invoiceId = result?.invoice?.id ?? null;
      // A billing run numbers its draft with a placeholder (the CA is not
      // present in an unattended run), and Issue accepts it as a number — so
      // the one thing the CA must do before issuing is said where they are
      // sent to do it.
      say(
        result?.created
          ? `Draft invoice generated (${result.invoice?.invoice_no ?? invoiceId}). Replace its placeholder number in Edit before you issue it.`
          : "Already generated for this period",
        invoiceId ? { id: invoiceId, created: result?.created === true } : null,
      );
      await load();
    } catch (e) { say(e instanceof Error ? e.message : "Generate failed"); }
  } finally { setRowBusy(false); }
  }

  if (loading) return <div className="p-8 text-sm text-gray-500">Loading billing…</div>;
  if (error) return <div className="p-8 text-sm text-red-600">{error}</div>;

  // Where the practice's own fee invoices are checked, numbered, issued and paid.
  // Null until the server has named the practice client: a null renders no link.
  const practiceInvoicesHref = practiceSalesHref(internalClientId);
  const draftHref = practiceSalesHref(internalClientId, { invoiceId: msgInvoice?.id });

  return (
    <div className="p-6 max-w-4xl">
      <PageHeader
        icon={<Receipt size={18} className="text-brand" />}
        title="Billing Schedules"
        actions={
          <div className="flex items-center gap-3">
            <button onClick={() => setShowForm((v) => !v)} className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-brand text-white">
              <Plus size={13} /> New schedule
            </button>
            {practiceInvoicesHref && (
              <Link href={practiceInvoicesHref} className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-brand">
                <FileText size={13} /> Practice invoices
              </Link>
            )}
            <button onClick={load} className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-brand">
              <RefreshCw size={13} /> Refresh
            </button>
          </div>
        }
        className="mb-5"
      />

      {msg && (
        <div className="mb-3 text-xs px-3 py-2 rounded-lg bg-blue-50 text-blue-700">
          {msg}
          {draftHref && msgInvoice && (
            <>
              {" "}
              <Link href={draftHref} className="font-medium underline">
                {msgInvoice.created ? "Open the draft" : "Open the invoice"}
              </Link>
            </>
          )}
        </div>
      )}

      {showForm && (
        <form onSubmit={createSchedule} className="mb-4 bg-white border border-gray-200 rounded-xl p-4 grid grid-cols-2 gap-3 text-sm">
          <ClientLookup
            clients={clients}
            value={form.client_id}
            onChange={(id) => setForm({ ...form, client_id: id })}
            ariaLabel="Client"
            placeholder="Select client…"
          />
          <select value={form.arrangement} onChange={(e) => setForm({ ...form, arrangement: e.target.value })} className="border rounded-lg px-2 py-1.5">
            <option value="retainer">Retainer</option><option value="one_time">One-time</option><option value="package">Package</option>
          </select>
          <select value={form.cadence} onChange={(e) => setForm({ ...form, cadence: e.target.value })} className="border rounded-lg px-2 py-1.5">
            <option value="monthly">Monthly</option><option value="quarterly">Quarterly</option><option value="annual">Annual</option><option value="one_time">One-time</option>
          </select>
          {internalClientId ? (
            <ServiceCataloguePicker
              clientId={internalClientId}
              value={product}
              onPick={setProduct}
              ariaLabel="Product/Service"
              placeholder="Product/Service…"
            />
          ) : (
            <p className="text-2xs text-state-attention bg-state-attention-surface rounded-lg px-3 py-2 col-span-1 flex items-center">
              Provision the practice (internal client) before billing — see Practice settings.
            </p>
          )}
          <input required type="number" step="0.01" placeholder="Fee (₹)" value={form.amount_rupees} onChange={(e) => setForm({ ...form, amount_rupees: e.target.value })} className="border rounded-lg px-2 py-1.5" />
          <input type="number" step="0.01" placeholder="GST %" value={form.gst_rate} onChange={(e) => setForm({ ...form, gst_rate: e.target.value })} className="border rounded-lg px-2 py-1.5" />
          <button type="submit" className="px-3 py-1.5 rounded-lg bg-brand text-white">Create</button>
        </form>
      )}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-2xs uppercase tracking-wide text-gray-500 border-b border-gray-200">
              <th className="px-4 py-2.5 font-medium">Client</th>
              <th className="px-4 py-2.5 font-medium">Cadence</th>
              <th className="px-4 py-2.5 font-medium text-right">Fee</th>
              <th className="px-4 py-2.5 font-medium">Next run</th>
              <th className="px-4 py-2.5 font-medium text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {schedules.length === 0 && (
              <tr><td colSpan={5}>
                <EmptyState
                  className="py-10"
                  title="No billing schedules yet"
                  description="A schedule bills a client a fixed fee on a cadence. Each run produces a draft invoice for you to check; nothing is issued on its own."
                  action={
                    <EmptyStateActions>
                      <EmptyStateAction requires={["billing", "write"]} icon={<Plus size={14} />} label="New schedule"
                        onClick={() => setShowForm(true)} />
                    </EmptyStateActions>
                  }
                />
              </td></tr>
            )}
            {schedules.map((s) => (
              <tr key={s.id} className="border-b border-ps-border last:border-0">
                <td className="px-4 py-2.5 text-brand">{clientName(s.client_id)}</td>
                <td className="px-4 py-2.5 text-gray-600 capitalize">{s.cadence}</td>
                <td className="px-4 py-2.5 text-right tabular-nums">{formatPaise(s.amount_paise)}</td>
                <td className="px-4 py-2.5 text-gray-600">{s.next_run_date ?? "—"}</td>
                <td className="px-4 py-2.5 text-right">
                  <Button variant="plain" size="none" disabled={rowBusy} onClick={() => generate(s.id)} className="text-xs text-blue-600 hover:underline">Generate draft</Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-gray-500 mt-3 flex items-center gap-1.5">
        <CheckCircle2 size={13} className="text-gray-400" />
        <span>
          Generation creates a DRAFT only. Confirm &amp; issue each draft from{" "}
          {practiceInvoicesHref
            ? <Link href={practiceInvoicesHref} className="underline hover:text-brand">the practice&apos;s Sales invoices</Link>
            : "the invoice"}
          {" "}(CA-confirm gate) before despatch.
        </span>
      </p>
    </div>
  );
}

export default function BillingPage() {
  return <PartnerGuard><Billing /></PartnerGuard>;
}
