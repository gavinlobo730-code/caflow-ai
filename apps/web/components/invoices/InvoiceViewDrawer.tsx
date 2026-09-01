"use client";

/**
 * InvoiceViewDrawer — the Invoice HUB (Batch 4). Turns the read-only view into the
 * operational hub for an issued invoice by SURFACING existing capabilities (no new
 * backend logic): rich header + three independent status groups (financial /
 * delivery / compliance), a status-gated action bar, an inline journal drill-through,
 * an activity timeline, and Record-Payment / Create-Credit-Note actions that reuse
 * the existing receipts and credit-notes endpoints.
 */
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { useState, useEffect, useCallback } from "react";
import {
  CheckCircle, Download, Pencil, Send, Trash2, Copy, CreditCard, FilePlus2,
  BookOpen, Clock, Loader2, ChevronDown, ChevronUp, AlertCircle, Mail,
} from "lucide-react";
import { Drawer } from "@/components/ui/drawer";
import { Modal as ModalShell } from "@/components/ui/modal";
import { formatDateTime } from "@/lib/services/formatting";
import { diffDaysISO } from "@/lib/sales/dateMath";
import { termLabelForDays } from "@/lib/sales/paymentTerms";
import { FormSkeleton, TableSkeleton } from "@/components/ui/skeleton";

// Receipt payment modes — must match the receipts.payment_mode CHECK constraint
// (migration 050, widened by 161: bank/cash/cheque/upi/neft/rtgs/online).
const PAYMENT_MODE_OPTIONS = ["bank", "cash", "cheque", "upi", "neft", "rtgs", "online"] as const;
import {
  API, apiGet, apiCall, getAuthToken, fmt, STATUS_BADGE, DELIVERY_STATUS_LABEL,
  type InvoiceDetail, type InvoiceDelivery, type SalesInvoice,
} from "@/lib/invoices/shared";
import {
  availableActions, deliverySummary, complianceSummary, buildActivity,
  type TimelineItem,
} from "@/lib/invoices/hub";
import { CompliancePanel } from "@/components/invoices/CompliancePanel";
import {
  complianceTimelineItems, type EInvoiceRecord, type EWayRecord,
} from "@/lib/invoices/compliance";

const fmtDateTime = formatDateTime;

async function viewInvoicePdf(invoiceId: string): Promise<void> {
  const token = await getAuthToken();
  const res = await fetch(`${API}/api/sales-invoices/${invoiceId}/pdf`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("PDF generation failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

function DetailRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="text-xs text-[#94A3B8] flex-shrink-0">{label}</span>
      <span className={`text-xs text-[#334155] text-right break-all ${mono ? "font-mono" : ""}`}>{value}</span>
    </div>
  );
}

interface JournalLine { account_name?: string; account_id?: string; debit_paise: number; credit_paise: number; narration?: string }
interface JournalEntry { id: string; reference_no?: string; narration?: string; entry_date?: string; lines?: JournalLine[] }

export function InvoiceViewDrawer({
  invoiceId,
  clientId,
  onClose,
  onEdit,
  onIssue,
  onSend,
  onDelete,
  onDuplicate,
  onPaymentLink,
  onChanged,
  onToast,
}: {
  invoiceId: string;
  clientId: string;
  onClose: () => void;
  onEdit: (inv: SalesInvoice) => void;
  onIssue: (id: string) => void;
  onSend: (inv: SalesInvoice) => void;
  onDelete: (inv: SalesInvoice) => void;
  onDuplicate: (inv: InvoiceDetail) => void;
  onPaymentLink: (inv: SalesInvoice) => void;
  /** Called after a payment/credit-note is recorded so the caller reloads its list. */
  onChanged: () => void;
  onToast: (msg: string, type: "success" | "error") => void;
}) {
  const [inv, setInv] = useState<InvoiceDetail | null>(null);
  const [deliveries, setDeliveries] = useState<InvoiceDelivery[]>([]);
  const [einvoiceRecords, setEinvoiceRecords] = useState<EInvoiceRecord[]>([]);
  const [ewayRecords, setEwayRecords] = useState<EWayRecord[]>([]);
  const [activity, setActivity] = useState<TimelineItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const [showJournal, setShowJournal] = useState(false);
  const [journal, setJournal] = useState<JournalEntry | null>(null);
  const [journalLoading, setJournalLoading] = useState(false);
  const [payOpen, setPayOpen] = useState(false);
  const [cnOpen, setCnOpen] = useState(false);
  const [dnOpen, setDnOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const token = await getAuthToken();
      const [d, del, tl] = await Promise.all([
        apiGet(`/api/sales-invoices/${invoiceId}`, token),
        apiGet(`/api/sales-invoices/${invoiceId}/deliveries`, token),
        apiGet(`/api/timeline?client_id=${clientId}&limit=100`, token),
      ]);
      if (!d.success || !d.data) { setError(true); return; }
      const detail = d.data as InvoiceDetail;
      const dels = (del.data as InvoiceDelivery[]) ?? [];
      setInv(detail);
      setDeliveries(dels);

      // Compliance records only matter once a document exists (issued+).
      let eiRecs: EInvoiceRecord[] = [];
      let ewRecs: EWayRecord[] = [];
      if (detail.status !== "draft") {
        const [ei, ew] = await Promise.all([
          apiGet(`/api/einvoice/records?client_id=${clientId}`, token),
          apiGet(`/api/eway-bill/records?client_id=${clientId}`, token),
        ]);
        eiRecs = (ei.data as EInvoiceRecord[]) ?? [];
        ewRecs = (ew.data as EWayRecord[]) ?? [];
        setEinvoiceRecords(eiRecs);
        setEwayRecords(ewRecs);
      }

      // One merged, newest-first activity feed: lifecycle + deliveries + the
      // invoice's own compliance events (IRN / E-Way generated / cancelled).
      const compItems: TimelineItem[] = complianceTimelineItems(invoiceId, eiRecs, ewRecs)
        .map((c) => ({ at: c.at, title: c.title, detail: c.detail, kind: "compliance" as const }));
      setActivity(buildActivity(invoiceId, (tl.data as Parameters<typeof buildActivity>[1]) ?? [], dels, compItems));
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [invoiceId, clientId]);

  useEffect(() => { load(); }, [load]);

  async function openJournal() {
    const next = !showJournal;
    setShowJournal(next);
    if (next && !journal && inv?.journal_entry_id && inv.invoice_date) {
      setJournalLoading(true);
      try {
        const token = await getAuthToken();
        const r = await apiGet(
          `/api/accounting/journal?client_id=${clientId}&start_date=${inv.invoice_date}&end_date=${inv.invoice_date}`,
          token,
        );
        const entries = (r.data as JournalEntry[]) ?? [];
        setJournal(entries.find((e) => e.id === inv.journal_entry_id) ?? null);
      } catch {
        onToast("Unable to load the journal entry", "error");
      } finally {
        setJournalLoading(false);
      }
    }
  }

  async function handleViewPdf() {
    try { await viewInvoicePdf(invoiceId); }
    catch { onToast("Unable to open PDF", "error"); }
  }

  const customerName = inv?.customers?.name ?? "—";
  // (total + debit_note_paise) - paid - credited: issued credit/debit notes
  // both move the receivable (CGST Act §34), so a corrected invoice shows the
  // true balance and Record Payment doesn't pre-fill an amount the backend
  // would reject as exceeding (or understating) what's actually outstanding.
  const outstanding = inv ? (inv.total_paise + (inv.debit_note_paise ?? 0)) - (inv.paid_paise ?? 0) - (inv.credited_paise ?? 0) : 0;
  const posted = !!inv?.journal_entry_id;
  const del = deliverySummary(deliveries);
  const compliance = inv ? complianceSummary(inv.id, einvoiceRecords, ewayRecords) : { irn: null, ewayBill: null };
  const actions = inv ? availableActions(inv.status) : null;

  const summary: SalesInvoice | null = inv ? {
    id: inv.id, invoice_no: inv.invoice_no, invoice_date: inv.invoice_date,
    due_date: inv.due_date, customer_id: inv.customer_id, customer_name: customerName,
    taxable_paise: inv.taxable_amount_paise, gst_paise: inv.total_gst_paise,
    total_paise: inv.total_paise, paid_paise: inv.paid_paise, status: inv.status,
    supply_state_code: inv.supply_state_code, is_interstate: inv.is_interstate,
  } : null;

  return (
    <Drawer open onClose={onClose} title={inv ? inv.invoice_no : "Invoice"} widthClass="sm:max-w-lg">
      {loading ? (
        <div className="p-6 space-y-5">
          {/* Header detail fields, then the line-items table */}
          <FormSkeleton fields={6} />
          <TableSkeleton cols={7} rows={4} />
        </div>
      ) : error || !inv ? (
        <div className="p-8 text-center">
          <AlertCircle size={28} className="mx-auto mb-3 text-red-500" />
          <p className="text-sm font-semibold text-[#334155]">Couldn&apos;t load this invoice</p>
          <button onClick={load} className="mt-3 text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Retry</button>
        </div>
      ) : (
        <div className="p-5 space-y-5">
          {/* ── Rich header ─────────────────────────────────────────────── */}
          <section className="space-y-2.5">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-[#0F172A] truncate">{customerName}</p>
                <p className="text-[10px] text-[#94A3B8]">{inv.is_interstate ? "Inter-state · IGST" : "Intra-state · CGST+SGST"}</p>
              </div>
              <div className="text-right flex-shrink-0">
                <p className="text-base font-semibold text-[#0F172A] font-mono">{fmt(inv.total_paise)}</p>
                <p className="text-[10px] text-[#94A3B8]">Grand total</p>
              </div>
            </div>

            {/* Three independent status groups */}
            <div className="flex flex-wrap items-center gap-1.5">
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${STATUS_BADGE[inv.status] ?? "bg-[#F1F5F9] text-[#64748B]"}`}>
                {inv.status.replace("_", " ")}
              </span>
              {inv.status !== "draft" && (
                <>
                  <span className="text-[#E2E8F0]">·</span>
                  <Badge tone={del.sent ? "green" : "muted"}><Mail size={9} /> {del.sent ? "Sent" : "Not sent"}</Badge>
                  <Badge tone="muted" title="Open-tracking not enabled">Viewed —</Badge>
                  <span className="text-[#E2E8F0]">·</span>
                  <Badge tone={compliance.irn ? "blue" : "muted"}>IRN {compliance.irn ? "✓" : "—"}</Badge>
                  <Badge tone={compliance.ewayBill ? "blue" : "muted"}>E-Way {compliance.ewayBill ? "✓" : "—"}</Badge>
                </>
              )}
            </div>

            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 pt-1">
              <DetailRow label="Invoice date" value={inv.invoice_date} />
              <DetailRow label="Due date" value={inv.due_date ?? "—"} />
              <DetailRow label="Outstanding" value={fmt(outstanding)} />
              {(() => {
                const days = inv.credit_days ?? (inv.due_date ? diffDaysISO(inv.invoice_date, inv.due_date) : null);
                return <DetailRow label="Terms" value={days == null ? "—" : termLabelForDays(days)} />;
              })()}
              <DetailRow label="Reference / PO no." value={inv.reference_no ?? "—"} />
              <DetailRow label="Notes" value={inv.notes ?? "—"} />
            </div>
          </section>

          {/* ── Action bar (status-gated) ───────────────────────────────── */}
          {actions && (
            <div className="flex flex-wrap gap-2 pt-1">
              {actions.edit && summary && <Action onClick={() => onEdit(summary)} icon={<Pencil size={12} />}>Edit</Action>}
              {/* Issued invoice: opens the same full-page editor in its locked
                  mode (soft fields editable, amount/tax/customer frozen with an
                  inline Credit-Note reason) — parity with the Purchase Bill
                  drawer, replacing the old cramped Edit-Details modal. */}
              {actions.editDetails && summary && <Action onClick={() => onEdit(summary)} icon={<Pencil size={12} />}>Edit Details</Action>}
              {actions.issue && <Action primary onClick={() => onIssue(inv.id)} icon={<CheckCircle size={12} />}>Issue</Action>}
              {actions.delete && summary && <Action danger onClick={() => onDelete(summary)} icon={<Trash2 size={12} />}>Delete</Action>}
              {actions.recordPayment && <Action primary onClick={() => setPayOpen(true)} icon={<CreditCard size={12} />}>Record Payment</Action>}
              {actions.send && summary && <Action onClick={() => onSend(summary)} icon={<Send size={12} />}>{del.sent ? "Resend Email" : "Send Email"}</Action>}
              {actions.paymentLink && summary && <Action onClick={() => onPaymentLink(summary)} icon={<CreditCard size={12} />}>Payment Link</Action>}
              {actions.creditNote && <Action onClick={() => setCnOpen(true)} icon={<FilePlus2 size={12} />}>Credit Note</Action>}
              {/* Debit Note — the increase-side mirror of Credit Note (CGST Act
                  §34(3)): the customer was undercharged and now owes more. */}
              {actions.debitNote && <Action onClick={() => setDnOpen(true)} icon={<FilePlus2 size={12} />}>Debit Note</Action>}
              {actions.duplicate && <Action onClick={() => onDuplicate(inv)} icon={<Copy size={12} />}>Duplicate</Action>}
              {actions.pdf && <Action onClick={handleViewPdf} icon={<Download size={12} />}>PDF</Action>}
            </div>
          )}

          {/* ── Line items ──────────────────────────────────────────────── */}
          <section>
            <h4 className="text-xs font-semibold text-[#334155] mb-2">Line items</h4>
            <div className="overflow-x-auto border border-[#F1F5F9] rounded-lg">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="text-[#94A3B8] border-b border-[#F1F5F9]">
                    <th className="px-2 py-1.5 text-left font-semibold">Description</th>
                    <th className="px-2 py-1.5 text-left font-semibold">HSN/SAC</th>
                    <th className="px-2 py-1.5 text-right font-semibold">Qty</th>
                    <th className="px-2 py-1.5 text-left font-semibold">Unit</th>
                    <th className="px-2 py-1.5 text-right font-semibold">Rate</th>
                    <th className="px-2 py-1.5 text-right font-semibold">GST%</th>
                    <th className="px-2 py-1.5 text-right font-semibold">Amount</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F8FAFC]">
                  {inv.lines.map((l, i) => (
                    <tr key={l.id ?? i}>
                      <td className="px-2 py-1.5 text-[#334155]">{l.description}</td>
                      <td className="px-2 py-1.5 font-mono text-[#64748B]">{l.hsn_sac || "—"}</td>
                      <td className="px-2 py-1.5 text-right text-[#334155]">{l.quantity}</td>
                      <td className="px-2 py-1.5 text-[#64748B]">{l.unit || "NOS"}</td>
                      <td className="px-2 py-1.5 text-right font-mono text-[#334155]">{fmt(l.rate_paise)}</td>
                      <td className="px-2 py-1.5 text-right text-[#334155]">{l.gst_rate_bps / 100}%</td>
                      <td className="px-2 py-1.5 text-right font-mono text-[#0F172A]">{fmt(l.line_total_paise)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* ── Accounting / View Journal drill-through ─────────────────── */}
          <section className="space-y-2">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-semibold text-[#334155]">Accounting</h4>
              {posted && actions?.viewJournal && (
                <button onClick={openJournal} className="text-[11px] text-blue-600 hover:underline flex items-center gap-1">
                  <BookOpen size={11} /> View Journal {showJournal ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
                </button>
              )}
            </div>
            <DetailRow label="Posting status" value={posted ? "Posted" : "Not posted"} />
            <DetailRow label="Journal entry" value={inv.journal_entry_id ?? "—"} mono />
            <DetailRow label="Issued at" value={fmtDateTime(inv.issued_at)} />
            {showJournal && (
              <div className="border border-[#F1F5F9] rounded-lg p-2 bg-[#F8FAFC]">
                {journalLoading ? (
                  <div className="flex items-center gap-2 text-[11px] text-[#94A3B8] py-2"><Loader2 size={12} className="animate-spin" /> Loading…</div>
                ) : journal?.lines?.length ? (
                  <table className="w-full text-[11px]">
                    <thead><tr className="text-[#94A3B8]"><th className="text-left font-semibold py-1">Account</th><th className="text-right font-semibold">Debit</th><th className="text-right font-semibold">Credit</th></tr></thead>
                    <tbody>
                      {journal.lines.map((jl, i) => (
                        <tr key={i} className="border-t border-[#EEF2F7]">
                          <td className="py-1 text-[#334155]">{jl.account_name ?? jl.account_id ?? "—"}</td>
                          <td className="py-1 text-right font-mono">{jl.debit_paise ? fmt(jl.debit_paise) : ""}</td>
                          <td className="py-1 text-right font-mono">{jl.credit_paise ? fmt(jl.credit_paise) : ""}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p className="text-[11px] text-[#94A3B8] py-1">Journal {inv.journal_entry_id} — line detail unavailable here.</p>
                )}
              </div>
            )}
          </section>

          {/* ── Delivery detail ─────────────────────────────────────────── */}
          {del.sent && (
            <section className="space-y-2">
              <h4 className="text-xs font-semibold text-[#334155]">Delivery</h4>
              <DetailRow label="Email status" value={(del.lastStatus ? DELIVERY_STATUS_LABEL[del.lastStatus] ?? del.lastStatus : "—")} />
              <DetailRow label="Sent to" value={del.lastSentTo ?? "—"} />
              <DetailRow label="Sent at" value={fmtDateTime(del.lastSentAt)} />
              {del.attempts > 1 && <p className="text-[10px] text-[#94A3B8]">{del.attempts} delivery attempts</p>}
            </section>
          )}

          {/* ── GST compliance (IRN / E-Way workflows) ──────────────────── */}
          {inv.status !== "draft" && (
            <CompliancePanel
              invoice={inv}
              clientId={clientId}
              einvoiceRecords={einvoiceRecords}
              ewayRecords={ewayRecords}
              onChanged={load}
              onToast={onToast}
            />
          )}

          {/* ── Activity timeline ───────────────────────────────────────── */}
          <section className="space-y-2">
            <h4 className="text-xs font-semibold text-[#334155] flex items-center gap-1"><Clock size={11} /> Activity</h4>
            {activity.length === 0 ? (
              <p className="text-xs text-[#94A3B8]">No activity recorded yet.</p>
            ) : (
              <ol className="space-y-2 border-l border-[#E2E8F0] pl-3">
                {activity.map((a, i) => (
                  <li key={i} className="relative">
                    <span className="absolute -left-[15px] top-1 h-1.5 w-1.5 rounded-full bg-[#CBD5E1]" />
                    <p className="text-[11px] text-[#334155]">{a.title}</p>
                    {a.detail && <p className="text-[10px] text-[#94A3B8]">{a.detail}</p>}
                    <p className="text-[10px] text-[#CBD5E1]">{fmtDateTime(a.at)}</p>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      )}

      {payOpen && inv && (
        <RecordPaymentModal
          invoice={inv}
          clientId={clientId}
          outstanding={outstanding}
          onClose={() => setPayOpen(false)}
          onDone={() => { setPayOpen(false); onToast(`Payment recorded for ${inv.invoice_no}`, "success"); onChanged(); load(); }}
          onError={(m) => onToast(m, "error")}
        />
      )}
      {cnOpen && inv && (
        <CreateCreditNoteModal
          invoice={inv}
          clientId={clientId}
          onClose={() => setCnOpen(false)}
          onDone={(cnNo) => { setCnOpen(false); onToast(`Credit note ${cnNo} created (draft)`, "success"); onChanged(); }}
          onError={(m) => onToast(m, "error")}
        />
      )}
      {dnOpen && inv && (
        <CreateSalesDebitNoteModal
          invoice={inv}
          clientId={clientId}
          onClose={() => setDnOpen(false)}
          onDone={(dnNo) => { setDnOpen(false); onToast(`Debit note ${dnNo} created (draft)`, "success"); onChanged(); }}
          onError={(m) => onToast(m, "error")}
        />
      )}
    </Drawer>
  );
}

// ── Small presentational helpers ────────────────────────────────────────────
function Badge({ children, tone, title }: { children: React.ReactNode; tone: "green" | "blue" | "muted"; title?: string }) {
  const cls = tone === "green" ? "bg-green-50 text-green-700 border-green-200"
    : tone === "blue" ? "bg-blue-50 text-blue-700 border-blue-200"
    : "bg-[#F8FAFC] text-[#94A3B8] border-[#E2E8F0]";
  return <span title={title} className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium border ${cls}`}>{children}</span>;
}

function Action({ children, onClick, icon, primary, danger }: {
  children: React.ReactNode; onClick: () => void; icon: React.ReactNode; primary?: boolean; danger?: boolean;
}) {
  const cls = primary ? "bg-blue-600 text-white hover:bg-blue-700 border-blue-600"
    : danger ? "border-[#E2E8F0] text-red-600 hover:bg-red-50"
    : "border-[#E2E8F0] text-[#475569] hover:bg-[#F8FAFC]";
  return (
    <button onClick={onClick} className={`text-xs px-3 py-1.5 rounded-lg border flex items-center gap-1 ${cls}`}>
      {icon} {children}
    </button>
  );
}

// ── Record Payment (reuses POST /api/receipts) ──────────────────────────────
function RecordPaymentModal({ invoice, clientId, outstanding, onClose, onDone, onError }: {
  invoice: InvoiceDetail; clientId: string; outstanding: number;
  onClose: () => void; onDone: () => void; onError: (m: string) => void;
}) {
  const today = new Date().toISOString().split("T")[0];
  const [amount, setAmount] = useState(String(outstanding / 100));
  const [date, setDate] = useState(today);
  const [mode, setMode] = useState("bank");
  const [reference, setReference] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit() {
    const amountPaise = paiseFromRupeeInput(amount);
    if (amountPaise === null) {
      onError("Enter the amount in rupees, e.g. 125000 or 125000.50 — without commas.");
      return;
    }
    if (amountPaise <= 0) { onError("Enter a valid amount."); return; }
    if (amountPaise > outstanding) { onError("Amount exceeds the outstanding balance."); return; }
    setSaving(true);
    try {
      const token = await getAuthToken();
      // Reuses the single receipt engine; the allocation settles THIS invoice.
      const r = await apiCall("/api/receipts/", "POST", {
        client_id: clientId,
        customer_id: invoice.customer_id,
        receipt_date: date,
        amount_paise: amountPaise,
        payment_mode: mode,
        reference_no: reference.trim() || undefined,
        allocations: [{ sales_invoice_id: invoice.id, allocated_paise: amountPaise }],
      }, token);
      if (!r.success) throw new Error(r.error ?? "Failed to record payment");
      onDone();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Failed to record payment");
    } finally {
      setSaving(false);
    }
  }

  return (
    <ModalShell title={`Record Payment — ${invoice.invoice_no}`} onClose={onClose}>
      <Field label="Amount (₹)"><input type="number" min="0" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} className={inputCls} /></Field>
      <p className="text-[10px] text-[#94A3B8] -mt-2">Outstanding {fmt(outstanding)}</p>
      <Field label="Date"><input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={inputCls} /></Field>
      <Field label="Mode">
        <select value={mode} onChange={(e) => setMode(e.target.value)} className={inputCls}>
          {PAYMENT_MODE_OPTIONS.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </Field>
      <Field label="Reference (optional)"><input value={reference} onChange={(e) => setReference(e.target.value)} placeholder="UTR / cheque no." className={inputCls} /></Field>
      <ModalActions onClose={onClose} onSubmit={submit} saving={saving} label="Record Payment" />
    </ModalShell>
  );
}

// ── Create Credit Note (reuses POST /api/credit-notes) ──────────────────────
function CreateCreditNoteModal({ invoice, clientId, onClose, onDone, onError }: {
  invoice: InvoiceDetail; clientId: string;
  onClose: () => void; onDone: (cnNo: string) => void; onError: (m: string) => void;
}) {
  const today = new Date().toISOString().split("T")[0];
  const [date, setDate] = useState(today);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit() {
    setSaving(true);
    try {
      const token = await getAuthToken();
      // Full-value credit note against the invoice (draft) — copies its lines and
      // links via sales_invoice_id; reuses the credit-note engine (CGST Act §34).
      const lines = invoice.lines.map((l) => ({
        description: l.description,
        hsn_sac: l.hsn_sac ?? "",
        quantity: l.quantity,
        unit: l.unit ?? undefined,
        rate_paise: l.rate_paise,
        gst_rate_percent: (l.gst_rate_bps ?? 0) / 100,
        // Mandatory on every line (InvoiceLineIn.require_service_catalogue_id,
        // migration 206) — forwarded from the source invoice line, else the
        // credit note POST 422s. Also the link that lets the credit note
        // reverse the right product's stock.
        service_catalogue_id: l.service_catalogue_id ?? undefined,
      }));
      const r = await apiCall("/api/credit-notes/", "POST", {
        client_id: clientId,
        customer_id: invoice.customer_id,
        credit_note_date: date,
        lines,
        sales_invoice_id: invoice.id,
        is_interstate: invoice.is_interstate,
        // CreditNoteIn's field is named `reason` (matches the credit_notes.reason
        // DB column and every sibling note type) — a stray `notes` key here would
        // be silently dropped by pydantic parsing and the reason would never save.
        reason: reason.trim() || undefined,
      }, token);
      if (!r.success) throw new Error(r.error ?? "Failed to create credit note");
      const data = r.data as { credit_note_no?: string; cn_no?: string } | null;
      onDone(data?.credit_note_no ?? data?.cn_no ?? "");
    } catch (e) {
      onError(e instanceof Error ? e.message : "Failed to create credit note");
    } finally {
      setSaving(false);
    }
  }

  return (
    <ModalShell title={`Credit Note — ${invoice.invoice_no}`} onClose={onClose}>
      <p className="text-[11px] text-[#64748B]">Creates a full-value <strong>draft</strong> credit note copying this invoice&apos;s lines. Adjust or issue it from the Credit Notes tab.</p>
      <Field label="Credit note date"><input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={inputCls} /></Field>
      <Field label="Reason / notes"><textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} placeholder="Reason for the credit note" className={inputCls} /></Field>
      <ModalActions onClose={onClose} onSubmit={submit} saving={saving} label="Create Credit Note" />
    </ModalShell>
  );
}

// ── Create Sales Debit Note (reuses POST /api/sales-debit-notes) ────────────
// The increase-side mirror of CreateCreditNoteModal (CGST Act §34(3)): the
// customer was undercharged on this invoice and now owes more.
function CreateSalesDebitNoteModal({ invoice, clientId, onClose, onDone, onError }: {
  invoice: InvoiceDetail; clientId: string;
  onClose: () => void; onDone: (dnNo: string) => void; onError: (m: string) => void;
}) {
  const today = new Date().toISOString().split("T")[0];
  const [date, setDate] = useState(today);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit() {
    setSaving(true);
    try {
      const token = await getAuthToken();
      // Full-value debit note against the invoice (draft) — copies its lines and
      // links via sales_invoice_id; reuses the sales-debit-note engine (§34(3)).
      const lines = invoice.lines.map((l) => ({
        description: l.description,
        hsn_sac: l.hsn_sac ?? "",
        quantity: l.quantity,
        unit: l.unit ?? undefined,
        rate_paise: l.rate_paise,
        gst_rate_percent: (l.gst_rate_bps ?? 0) / 100,
        service_catalogue_id: l.service_catalogue_id ?? undefined,
      }));
      const r = await apiCall("/api/sales-debit-notes/", "POST", {
        client_id: clientId,
        customer_id: invoice.customer_id,
        debit_note_date: date,
        lines,
        sales_invoice_id: invoice.id,
        is_interstate: invoice.is_interstate,
        reason: reason.trim() || undefined,
      }, token);
      if (!r.success) throw new Error(r.error ?? "Failed to create debit note");
      const data = r.data as { debit_note_no?: string } | null;
      onDone(data?.debit_note_no ?? "");
    } catch (e) {
      onError(e instanceof Error ? e.message : "Failed to create debit note");
    } finally {
      setSaving(false);
    }
  }

  return (
    <ModalShell title={`Debit Note — ${invoice.invoice_no}`} onClose={onClose}>
      <p className="text-[11px] text-[#64748B]">Creates a full-value <strong>draft</strong> debit note copying this invoice&apos;s lines — for when the customer was undercharged and owes more. Adjust or issue it from the Debit Notes tab (CGST Act §34(3)).</p>
      <Field label="Debit note date"><input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={inputCls} /></Field>
      <Field label="Reason / notes"><textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} placeholder="Reason for the debit note" className={inputCls} /></Field>
      <ModalActions onClose={onClose} onSubmit={submit} saving={saving} label="Create Debit Note" />
    </ModalShell>
  );
}

// ── Modal primitives (local, compact) ───────────────────────────────────────
const inputCls = "w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500";
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block space-y-1"><span className="block text-xs font-medium text-[#475569]">{label}</span>{children}</label>;
}
function ModalActions({ onClose, onSubmit, saving, label }: { onClose: () => void; onSubmit: () => void; saving: boolean; label: string }) {
  return (
    <div className="flex justify-end gap-2 pt-1">
      <button onClick={onClose} disabled={saving} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] disabled:opacity-50">Cancel</button>
      <button onClick={onSubmit} disabled={saving} className="text-xs px-3.5 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 inline-flex items-center gap-1.5">
        {saving && <Loader2 size={12} className="animate-spin" />} {label}
      </button>
    </div>
  );
}
