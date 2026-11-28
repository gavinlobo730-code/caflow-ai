"use client";

/**
 * CA Firm Fee Billing — Track fee engagements, invoices, outstanding and receipts
 * GST on CA services: 18% under SAC 998211 (Accounting and bookkeeping services)
 * All monetary values stored and calculated in integer paise (1 INR = 100 paise)
 */

import { useState, useEffect, useCallback } from "react";
import { RefreshCw, MessageCircle, Download } from "lucide-react";
import { TableSkeleton } from "@/components/ui/skeleton";
import { SectionPlaceholder } from "@/components/ui/page-frame";
import { api } from "@/lib/api";
import type { FeeEngagementStatus } from "@/lib/api";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { getClients } from "@/lib/data/clients";
import { selectAll } from "@/lib/supabase/selectAll";
import { daysBetweenLocalISO } from "@/lib/dateMath";
import { formatDate, todayIstISO } from "@/lib/dates/format";
import Link from "next/link";
import { Callout } from "@/components/ui/callout";
// A payload field is not a list until something has checked.
import { arrayOrEmpty } from "@/lib/api/shape";
// Indian grouping (D6) from the one authority; this screen's own formatter
// grouped the Western way (₹1,234,567).
import { formatPaise as fmtPaise } from "@/lib/money/format";
import { isOwedFeeInvoice, type FeeInvoiceStatus } from "@/lib/constants/feeInvoiceStatus";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/states";

// ─── Types ────────────────────────────────────────────────────────────────────

type ServiceType = "GST Filing" | "ITR Filing" | "Accounting" | "Payroll" | "MCA" | "Audit" | "Advisory";
type BillingCycle = "Monthly" | "Quarterly" | "Annual";
// The whole of migration 123's CHECK, not the four this screen used to know —
// "Sent" and "Cancelled" rows exist and were typed as something they are not.
type InvoiceStatus = FeeInvoiceStatus;
type PaymentMode = "NEFT" | "RTGS" | "Cheque" | "Cash" | "UPI";

// `status` is migration 108's CHECK, verbatim. This said `"Active" | "Paused"`
// and `fee_engagements` cannot hold "Paused" — the CHECK allows Draft, Active,
// In Progress, Review, Completed, Closed and Inactive. So the one alternative
// the type offered was one the database would have refused, and the chip below
// rendered everything-not-Active as the same grey.
interface Engagement {
  id: string;
  firm_id: string;
  client_id: string;
  service_type: ServiceType;
  fee_paise: number;
  billing_cycle: BillingCycle;
  start_date: string;
  status: FeeEngagementStatus;
  client_name?: string;
}

interface Invoice {
  id: string;
  firm_id: string;
  client_id: string;
  invoice_no: string;
  invoice_date: string;
  amount_paise: number;
  gst_paise: number;
  total_paise: number;
  status: InvoiceStatus;
  client_name?: string;
}

interface Receipt {
  id: string;
  firm_id: string;
  invoice_id: string;
  receipt_date: string;
  amount_paise: number;
  payment_mode: PaymentMode;
  reference_no: string;
  invoice_no?: string;
  client_name?: string;
}

interface OutstandingRow {
  client_id: string;
  client_name: string;
  invoiceCount: number;
  totalPaise: number;
  d0_30: number;
  d31_60: number;
  d61_90: number;
  d90plus: number;
  phone?: string;
}

type Tab = "dashboard" | "engagements" | "invoices" | "outstanding" | "receipts";


const STATUS_COLORS: Record<InvoiceStatus, string> = {
  Draft: "bg-ps-muted text-ps-label",
  Issued: "bg-state-working-surface text-state-working",
  Sent: "bg-state-working-surface text-state-working",
  Paid: "bg-state-ready-surface text-state-ready",
  Overdue: "bg-state-problem-surface text-state-problem",
  Cancelled: "bg-state-done-surface text-state-done",
};

// ─── Main Page ────────────────────────────────────────────────────────────────

// The seven statuses migration 108's CHECK allows, in the state vocabulary:
// Active and Completed are finished, Draft/In Progress/Review are
// somebody-is-on-it, Review is waiting on a person, and Closed/Inactive are
// settled.
const ENGAGEMENT_STATUS_BADGE: Record<FeeEngagementStatus, string> = {
  "Draft":       "bg-ps-muted text-ps-label",
  "Active":      "bg-state-ready-surface text-state-ready",
  "In Progress": "bg-state-working-surface text-state-working",
  "Review":      "bg-state-attention-surface text-state-attention",
  "Completed":   "bg-state-ready-surface text-state-ready",
  "Closed":      "bg-state-done-surface text-state-done",
  "Inactive":    "bg-state-done-surface text-state-done",
};

export default function BillingPage() {
  // THIS SCREEN IS A RECORD SINCE 21-11-2026 (POST-B-193, decided by the owner on 20-11-2026). The firm's own fee billing lives
  // in My practice, on the sales engine in the practice's own books (billing schedules, the practice's sales invoices, real GST,
  // a posted journal). The bills raised here before that are kept exactly as they were and nothing is added to them or changed,
  // so the screen has no control that writes (the dialogs, the status buttons, Raise Invoice and the overdue check are deleted:
  // POST-A-572).
  const [tab, setTab] = useState<Tab>("dashboard");
  const [engagements, setEngagements] = useState<Engagement[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [outstanding, setOutstanding] = useState<OutstandingRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  // `recorded` is a receipt the server has just confirmed. It stays on the list
  // whatever the read below returns, so the Receipts tab never says "No
  // receipts recorded" over a receipt the CA was just told succeeded — a CA who
  // believes it failed records it a second time.
  const load = useCallback(async (recorded?: Receipt | null) => {
    setLoading(true);
    setError(null);
    try {
      const [clientList, firmId] = await Promise.all([getClients(), getFirmId()]);
      const clientMap = new Map(clientList.map(c => [c.id, c]));
      const sb = getSupabaseClient();

      // Engagements come from the API — `billing:read` is Partner-only
      // ("exposes fee economics"), and over PostgREST the SELECT policy is
      // firm-scoped with no role test, so every role could read every fee.
      // Invoices and receipts are still direct reads; moving them is the same
      // shape and is not this change.
      //
      // Both are PAGED, because the headline figures below (revenue, outstanding,
      // overdue, issued, draft) are added up in the browser from these rows.
      // PostgREST cuts a response at ~1000 rows and says nothing, and a firm's
      // fee invoices pass 1000 in under two years on a 50-client book
      // (accounting/receivables says the same of its ageing). Newest-first, the
      // cut took the OLDEST invoices: revenue short, and an old unpaid invoice
      // missing from "outstanding" entirely. `.order("id")` is the unique
      // tiebreaker the OFFSET paging needs, since neither date is unique.
      const [engResp, invRes, recRes] = await Promise.all([
        api.engagements.list(),
        selectAll<Invoice>(() => sb.from("fee_invoices").select("*").eq("firm_id", firmId)
          .order("invoice_date", { ascending: false }).order("id")),
        selectAll<Receipt>(() => sb.from("fee_receipts").select("*").eq("firm_id", firmId)
          .order("receipt_date", { ascending: false }).order("id")),
      ]);
      // A non-null PostgREST error is a real failure (RLS denial, network, timeout),
      // not "zero rows" — .data would still be null/[] either way, so skipping this
      // check would silently render invoices/receipts as empty instead
      // of surfacing the failure.
      if (!engResp.success) throw new Error(engResp.error || "Could not read fee engagements");
      if (invRes.error) throw new Error(invRes.error.message);
      if (recRes.error) throw new Error(recRes.error.message);

      const engs: Engagement[] = arrayOrEmpty(engResp.data?.engagements).map((e) => ({
        ...(e as unknown as Engagement),
        client_name: clientMap.get((e as { client_id: string }).client_id)?.client_name,
      }));
      const invs: Invoice[] = (invRes.data ?? []).map((i: Invoice) => ({
        ...i,
        client_name: clientMap.get(i.client_id)?.client_name,
      }));
      const recs: Receipt[] = (recRes.data ?? []).map((r: Receipt) => {
        const inv = invs.find(i => i.id === r.invoice_id);
        return { ...r, invoice_no: inv?.invoice_no, client_name: inv?.client_name };
      });
      if (recorded && !recs.some(r => r.id === recorded.id)) {
        const inv = invs.find(i => i.id === recorded.invoice_id);
        recs.unshift({ ...recorded, invoice_no: inv?.invoice_no, client_name: inv?.client_name });
      }

      setEngagements(engs);
      setInvoices(invs);
      setReceipts(recs);

      // Build aged outstanding from OWED invoices. This kept `status !== "Paid"`,
      // so a Draft — and a Cancelled invoice — aged as a debt and got a
      // WhatsApp "Remind" link demanding fees nobody had billed, while the
      // Outstanding tile counted "Issued" alone. Both ask the one set now.
      const today = todayIstISO();
      const unpaidInvs = invs.filter(i => isOwedFeeInvoice(i.status));
      const outMap = new Map<string, OutstandingRow>();
      for (const inv of unpaidInvs) {
        const days = daysBetweenLocalISO(inv.invoice_date, today) ?? 0;
        const existing = outMap.get(inv.client_id);
        const row: OutstandingRow = existing ?? {
          client_id: inv.client_id,
          client_name: inv.client_name ?? "Unknown",
          invoiceCount: 0,
          totalPaise: 0,
          d0_30: 0, d31_60: 0, d61_90: 0, d90plus: 0,
        };
        row.invoiceCount++;
        row.totalPaise += inv.total_paise;
        if (days <= 30) row.d0_30 += inv.total_paise;
        else if (days <= 60) row.d31_60 += inv.total_paise;
        else if (days <= 90) row.d61_90 += inv.total_paise;
        else row.d90plus += inv.total_paise;
        outMap.set(inv.client_id, row);
      }
      setOutstanding(Array.from(outMap.values()));
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to load";
      if (msg.includes("does not exist") || msg.includes("relation")) {
        setError("Billing tables not set up yet. Please run database migrations.");
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleDownloadPdf(invoiceId: string) {
    setDownloadingId(invoiceId);
    try {
      await api.invoices.downloadPdf(invoiceId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to download PDF");
    } finally {
      setDownloadingId(null);
    }
  }

  const _paidInvoices = invoices.filter(i => i.status === "Paid");
  // Outstanding is every OWED invoice — the same set Aged Debtors totals, so
  // the tile and the report cannot disagree. Overdue is shown beside it as the
  // part of it that is late, and the pipeline's "Issued" row is the rest.
  const _owedInvoices = invoices.filter(i => isOwedFeeInvoice(i.status));
  const _overdueInvoices = _owedInvoices.filter(i => i.status === "Overdue");
  const _sentInvoices = _owedInvoices.filter(i => i.status !== "Overdue");
  const _draftInvoices = invoices.filter(i => i.status === "Draft");
  const _activeEngs = engagements.filter(e => e.status === "Active");
  const _mPaise = _activeEngs.filter(e => e.billing_cycle === "Monthly").reduce((s, e) => s + e.fee_paise, 0);
  const _qPaise = _activeEngs.filter(e => e.billing_cycle === "Quarterly").reduce((s, e) => s + e.fee_paise, 0);
  const _aPaise = _activeEngs.filter(e => e.billing_cycle === "Annual").reduce((s, e) => s + e.fee_paise, 0);
  const dash = {
    totalRevenuePaise: _paidInvoices.reduce((s, i) => s + i.total_paise, 0),
    outstandingPaise: _owedInvoices.reduce((s, i) => s + i.total_paise, 0),
    issuedPaise: _sentInvoices.reduce((s, i) => s + i.total_paise, 0),
    overduePaise: _overdueInvoices.reduce((s, i) => s + i.total_paise, 0),
    draftPaise: _draftInvoices.reduce((s, i) => s + i.total_paise, 0),
    monthlyPaise: _mPaise,
    quarterlyPaise: _qPaise,
    annualPaise: _aPaise,
    annualisedPaise: _mPaise * 12 + _qPaise * 4 + _aPaise,
    paidCount: _paidInvoices.length,
    owedCount: _owedInvoices.length,
    sentCount: _sentInvoices.length,
    overdueCount: _overdueInvoices.length,
    draftCount: _draftInvoices.length,
    activeEngCount: _activeEngs.length,
  };

  const TABS: { id: Tab; label: string }[] = [
    { id: "dashboard", label: "Dashboard" },
    { id: "engagements", label: "Engagements" },
    { id: "invoices", label: "Invoices" },
    { id: "outstanding", label: "Outstanding" },
    { id: "receipts", label: "Receipts" },
  ];

  return (
    <div className="p-4 md:p-6 max-w-ps-data mx-auto space-y-5">
      <PageHeader
        title="Earlier fee bills"
        subtitle="Fee bills raised before billing moved to My practice. A record: nothing here is added to or changed."
        actions={
          <button aria-label="Refresh" onClick={() => load()} className="p-2 rounded-lg border border-ps-border hover:bg-ps-bg text-ps-label">
            <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
          </button>
        }
      />

      <Callout tone="note" title="New fee bills are raised in My practice">
        Set up what you bill a client on{" "}
        <Link href="/practice/billing/" className="font-medium underline underline-offset-2">Billing Schedules</Link>; each bill is
        prepared as a draft in your own firm&apos;s books and issued from there. The bills on this screen stay as they were when
        they were raised. What is still owed on them is on{" "}
        <Link href="/accounting/receivables/" className="font-medium underline underline-offset-2">their ageing</Link>.
      </Callout>

      {error && (
        <div className="rounded-lg bg-state-attention-surface border border-state-attention-border px-4 py-3 text-sm text-amber-800">{error}</div>
      )}

      <div className="flex gap-1 border-b border-ps-border overflow-x-auto">
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${
              tab === t.id ? "border-brand text-blue-600" : "border-transparent text-ps-label hover:text-ps-body"
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Dashboard */}
      {/* A figure that has not been read is not a zero: the dashboard waits with a shape, as the other tabs do. */}
      {tab === "dashboard" && loading && <SectionPlaceholder label="Loading the fee dashboard" shape="dashboard" rows={4} cols={4} />}
      {tab === "dashboard" && !loading && (
        <div className="space-y-5">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-white border rounded-xl p-4">
              <p className="text-xs text-ps-label">Revenue Collected</p>
              <p className="text-xl font-bold text-ps-ink mt-1">{fmtPaise(dash.totalRevenuePaise)}</p>
              <p className="text-2xs text-ps-hint mt-0.5">{dash.paidCount} paid invoices</p>
            </div>
            <div className="bg-white border rounded-xl p-4">
              <p className="text-xs text-ps-label">Outstanding</p>
              <p className={`text-xl font-bold mt-1 ${dash.outstandingPaise > 0 ? "text-state-attention" : "text-ps-ink"}`}>{fmtPaise(dash.outstandingPaise)}</p>
              <p className="text-2xs text-ps-hint mt-0.5">{dash.owedCount} unpaid invoices, overdue included</p>
            </div>
            <div className={`bg-white border rounded-xl p-4 ${dash.overduePaise > 0 ? "border-state-problem-border" : ""}`}>
              <p className="text-xs text-ps-label">Overdue</p>
              <p className={`text-xl font-bold mt-1 ${dash.overduePaise > 0 ? "text-red-600" : "text-ps-ink"}`}>{fmtPaise(dash.overduePaise)}</p>
              <p className="text-2xs text-ps-hint mt-0.5">{dash.overdueCount} invoices</p>
            </div>
            <div className="bg-white border rounded-xl p-4">
              <p className="text-xs text-ps-label">ARR (Annualised)</p>
              <p className="text-xl font-bold text-blue-600 mt-1">{fmtPaise(dash.annualisedPaise)}</p>
              <p className="text-2xs text-ps-hint mt-0.5">{dash.activeEngCount} active engagements</p>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-white border rounded-xl p-4 space-y-3">
              <p className="text-sm font-semibold text-ps-body">Revenue Pipeline</p>
              <div className="space-y-2">
                {[
                  { label: "Draft", paise: dash.draftPaise, count: dash.draftCount, color: "bg-gray-300" },
                  { label: "Issued", paise: dash.issuedPaise, count: dash.sentCount, color: "bg-blue-400" },
                  { label: "Overdue", paise: dash.overduePaise, count: dash.overdueCount, color: "bg-red-400" },
                  { label: "Paid", paise: dash.totalRevenuePaise, count: dash.paidCount, color: "bg-green-500" },
                ].map(row => (
                  <div key={row.label} className="flex items-center gap-3">
                    <div className={`w-2.5 h-2.5 rounded-full ${row.color} shrink-0`} />
                    <span className="text-sm text-ps-body flex-1">{row.label}</span>
                    <span className="text-xs text-ps-label">{row.count} inv</span>
                    <span className="text-sm font-semibold text-ps-ink">{fmtPaise(row.paise)}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="bg-white border rounded-xl p-4 space-y-3">
              <p className="text-sm font-semibold text-ps-body">Recurring Revenue Breakdown</p>
              <div className="space-y-2">
                {[
                  { label: "Monthly", paise: dash.monthlyPaise, count: _activeEngs.filter(e => e.billing_cycle === "Monthly").length },
                  { label: "Quarterly", paise: dash.quarterlyPaise, count: _activeEngs.filter(e => e.billing_cycle === "Quarterly").length },
                  { label: "Annual", paise: dash.annualPaise, count: _activeEngs.filter(e => e.billing_cycle === "Annual").length },
                ].map(row => (
                  <div key={row.label} className="flex items-center gap-3">
                    <span className="text-sm text-ps-body flex-1">{row.label}</span>
                    <span className="text-xs text-ps-label">{row.count} clients</span>
                    <span className="text-sm font-semibold text-ps-ink">{fmtPaise(row.paise)}</span>
                  </div>
                ))}
                <div className="border-t pt-2 flex items-center gap-3">
                  <span className="text-sm font-semibold text-ps-body flex-1">ARR</span>
                  <span className="text-sm font-bold text-blue-600">{fmtPaise(dash.annualisedPaise)}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Engagements */}
      {tab === "engagements" && (
        <div className="space-y-4">
          {loading ? (
            <TableSkeleton cols={6} rows={3} />
          ) : (
            <div className="overflow-x-auto rounded-xl border border-ps-border bg-white">
              <table className="w-full text-sm min-w-[700px]">
                <thead className="bg-ps-bg border-b border-ps-border">
                  <tr>
                    <th className="text-left px-4 py-3 font-medium text-ps-label">Client</th>
                    <th className="text-left px-4 py-3 font-medium text-ps-label">Service</th>
                    <th className="text-left px-4 py-3 font-medium text-ps-label">Fee</th>
                    <th className="text-left px-4 py-3 font-medium text-ps-label">Cycle</th>
                    <th className="text-left px-4 py-3 font-medium text-ps-label">Start Date</th>
                    <th className="text-left px-4 py-3 font-medium text-ps-label">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ps-border">
                  {engagements.length === 0 && (
                    <tr><td colSpan={6}>
                      <EmptyState
                        className="py-10"
                        title="No engagements were recorded here"
                        description="An engagement was the work done for a client and the fee agreed for it. New ones are set up as billing schedules in My practice."
                      />
                    </td></tr>
                  )}
                  {engagements.map(e => (
                    <tr key={e.id} className="hover:bg-ps-bg">
                      <td className="px-4 py-3 font-medium text-ps-ink">{e.client_name ?? "—"}</td>
                      <td className="px-4 py-3 text-ps-label">{e.service_type}</td>
                      <td className="px-4 py-3 text-gray-800 font-mono">{fmtPaise(e.fee_paise)}</td>
                      <td className="px-4 py-3 text-ps-label">{e.billing_cycle}</td>
                      <td className="px-4 py-3 text-ps-label">{formatDate(e.start_date)}</td>
                      <td className="px-4 py-3">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${ENGAGEMENT_STATUS_BADGE[e.status] ?? "bg-ps-muted text-ps-label"}`}>
                          {e.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Invoices */}
      {tab === "invoices" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-xs text-ps-label">GST @ 18% applied on CA services — SAC 998211</p>
          </div>
          {loading ? (
            <TableSkeleton cols={8} rows={3} />
          ) : (
            <div className="overflow-x-auto rounded-xl border border-ps-border bg-white">
              <table className="w-full text-sm min-w-[800px]">
                <thead className="bg-ps-bg border-b border-ps-border">
                  <tr>
                    <th className="text-left px-4 py-3 font-medium text-ps-label">Invoice No.</th>
                    <th className="text-left px-4 py-3 font-medium text-ps-label">Date</th>
                    <th className="text-left px-4 py-3 font-medium text-ps-label">Client</th>
                    <th className="text-right px-4 py-3 font-medium text-ps-label">Amount</th>
                    <th className="text-right px-4 py-3 font-medium text-ps-label">GST 18%</th>
                    <th className="text-right px-4 py-3 font-medium text-ps-label">Total</th>
                    <th className="text-left px-4 py-3 font-medium text-ps-label">Status</th>
                    <th className="px-4 py-3"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ps-border">
                  {invoices.length === 0 && (
                    <tr><td colSpan={8}>
                      <EmptyState
                        className="py-10"
                        title="No fee invoices were raised here"
                        description="Fee invoices are now prepared from billing schedules in My practice and issued from your own firm's books."
                      />
                    </td></tr>
                  )}
                  {invoices.map(inv => (
                    <tr key={inv.id} className="hover:bg-ps-bg">
                      <td className="px-4 py-3 font-mono text-ps-body">{inv.invoice_no}</td>
                      <td className="px-4 py-3 text-ps-label">{formatDate(inv.invoice_date)}</td>
                      <td className="px-4 py-3 font-medium text-ps-ink">{inv.client_name ?? "—"}</td>
                      <td className="px-4 py-3 text-right font-mono text-ps-body">{fmtPaise(inv.amount_paise)}</td>
                      <td className="px-4 py-3 text-right font-mono text-ps-label">{fmtPaise(inv.gst_paise)}</td>
                      <td className="px-4 py-3 text-right font-mono font-semibold text-ps-ink">{fmtPaise(inv.total_paise)}</td>
                      <td className="px-4 py-3">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_COLORS[inv.status]}`}>
                          {inv.status}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <button onClick={() => handleDownloadPdf(inv.id)} disabled={downloadingId === inv.id}
                          title="Download PDF"
                          className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700 font-medium disabled:opacity-50">
                          <Download size={13} /> {downloadingId === inv.id ? "Downloading…" : "PDF"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Outstanding */}
      {tab === "outstanding" && (
        <div className="space-y-4">
          <h2 className="text-sm font-semibold text-ps-body">Aged Debtors Report</h2>
          <div className="overflow-x-auto rounded-xl border border-ps-border bg-white">
            <table className="w-full text-sm min-w-[800px]">
              <thead className="bg-ps-bg border-b border-ps-border">
                <tr>
                  <th className="text-left px-4 py-3 font-medium text-ps-label">Client</th>
                  <th className="text-right px-4 py-3 font-medium text-ps-label">Invoices</th>
                  <th className="text-right px-4 py-3 font-medium text-ps-label">Total Outstanding</th>
                  <th className="text-right px-4 py-3 font-medium text-ps-label">0–30 days</th>
                  <th className="text-right px-4 py-3 font-medium text-ps-label">31–60 days</th>
                  <th className="text-right px-4 py-3 font-medium text-ps-label">61–90 days</th>
                  <th className="text-right px-4 py-3 font-medium text-ps-label">90+ days</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ps-border">
                {outstanding.length === 0 && (
                  <tr><td colSpan={8} className="text-center py-8 text-ps-hint">No outstanding invoices</td></tr>
                )}
                {outstanding.map(row => (
                  <tr key={row.client_id} className="hover:bg-ps-bg">
                    <td className="px-4 py-3 font-medium text-ps-ink">{row.client_name}</td>
                    <td className="px-4 py-3 text-right text-ps-label">{row.invoiceCount}</td>
                    <td className="px-4 py-3 text-right font-semibold font-mono text-ps-ink">{fmtPaise(row.totalPaise)}</td>
                    <td className="px-4 py-3 text-right font-mono text-ps-label">{fmtPaise(row.d0_30)}</td>
                    <td className="px-4 py-3 text-right font-mono text-amber-600">{fmtPaise(row.d31_60)}</td>
                    <td className="px-4 py-3 text-right font-mono text-orange-600">{fmtPaise(row.d61_90)}</td>
                    <td className="px-4 py-3 text-right font-mono text-red-600">{fmtPaise(row.d90plus)}</td>
                    <td className="px-4 py-3">
                      <a
                        href={`https://wa.me/${(row.phone ?? "").replace(/\D/g, "")}?text=${encodeURIComponent(
                          `Dear ${row.client_name}, this is a reminder that you have ${fmtPaise(row.totalPaise)} in outstanding fees. Please arrange payment. Thank you.`
                        )}`}
                        target="_blank" rel="noopener noreferrer"
                        className="flex items-center gap-1 text-xs text-green-600 hover:text-green-700 font-medium"
                      >
                        <MessageCircle size={13} /> Remind
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Receipts */}
      {tab === "receipts" && (
        <div className="space-y-4">
          <div className="overflow-x-auto rounded-xl border border-ps-border bg-white">
            <table className="w-full text-sm min-w-[700px]">
              <thead className="bg-ps-bg border-b border-ps-border">
                <tr>
                  <th className="text-left px-4 py-3 font-medium text-ps-label">Invoice</th>
                  <th className="text-left px-4 py-3 font-medium text-ps-label">Client</th>
                  <th className="text-left px-4 py-3 font-medium text-ps-label">Date</th>
                  <th className="text-right px-4 py-3 font-medium text-ps-label">Amount</th>
                  <th className="text-left px-4 py-3 font-medium text-ps-label">Mode</th>
                  <th className="text-left px-4 py-3 font-medium text-ps-label">Reference</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ps-border">
                {receipts.length === 0 && (
                  <tr><td colSpan={6}>
                    <EmptyState
                      className="py-10"
                      title="No receipts were recorded here"
                      description="Money received against a fee bill is now recorded against the practice's own sales invoice, in My practice."
                    />
                  </td></tr>
                )}
                {receipts.map(r => (
                  <tr key={r.id} className="hover:bg-ps-bg">
                    <td className="px-4 py-3 font-mono text-ps-body">{r.invoice_no ?? "—"}</td>
                    <td className="px-4 py-3 font-medium text-ps-ink">{r.client_name ?? "—"}</td>
                    <td className="px-4 py-3 text-ps-label">{formatDate(r.receipt_date)}</td>
                    <td className="px-4 py-3 text-right font-mono font-semibold text-green-700">{fmtPaise(r.amount_paise)}</td>
                    <td className="px-4 py-3 text-ps-label">{r.payment_mode}</td>
                    <td className="px-4 py-3 font-mono text-ps-label text-xs">{r.reference_no || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

    </div>
  );
}
