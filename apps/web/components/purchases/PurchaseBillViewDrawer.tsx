"use client";

/**
 * PurchaseBillViewDrawer — read-only detail view + status-gated action bar for
 * a purchase bill, giving Purchase Bills the same "View details" capability
 * Sales Invoices already has (InvoiceViewDrawer). Scoped to what's actually
 * useful here: this app has no purchase-side equivalent of e-invoice/e-way
 * compliance or a delivery/send flow (those are outward-supply concepts),
 * and Record Payment already has its own home on the Payments tab — so this
 * stays a header + action bar + line items + TDS/accounting + activity feed,
 * not a byte-for-byte port of the sales hub.
 */
import { useState, useEffect, useCallback } from "react";
import { Pencil, Trash2, CheckCircle, Paperclip, BookOpen, Clock, Loader2, ChevronDown, ChevronUp, AlertCircle, Copy, Ban, CreditCard, FilePlus2 } from "lucide-react";
import { Drawer } from "@/components/ui/drawer";
import { Modal as ModalShell } from "@/components/ui/modal";
import { apiGet, apiCall, getAuthToken, fmt } from "@/lib/invoices/shared";
import { formatDateTime } from "@/lib/services/formatting";
import { termLabelForDays } from "@/lib/sales/paymentTerms";
import { diffDaysISO } from "@/lib/sales/dateMath";
import type { PurchaseBillDetail } from "@/components/purchases/PurchaseBillEditor";
import { FormSkeleton, TableSkeleton } from "@/components/ui/skeleton";

// Vendor-payment modes — must match the purchase_payments.payment_mode CHECK
// constraint (migration 050, widened by 161: bank/cash/cheque/upi/neft/rtgs/
// online). Identical to the sales-side receipt modes.
const PAYMENT_MODE_OPTIONS = ["bank", "cash", "cheque", "upi", "neft", "rtgs", "online"] as const;

const PB_STATUS_BADGE: Record<string, string> = {
  draft: "bg-[#F1F5F9] text-[#64748B]",
  received: "bg-blue-100 text-blue-700",
  partially_paid: "bg-amber-100 text-amber-700",
  paid: "bg-green-100 text-green-700",
  cancelled: "bg-red-100 text-red-600",
};

interface JournalLine { account_name?: string; account_id?: string; debit_paise: number; credit_paise: number }
interface JournalEntry { id: string; lines?: JournalLine[] }
interface TimelineEvent { entity_id?: string | null; entity_type?: string | null; title?: string | null; description?: string | null; event_type?: string | null; created_at?: string | null }
interface ActivityItem { at: string; title: string; detail?: string }

function DetailRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="text-xs text-[#94A3B8] flex-shrink-0">{label}</span>
      <span className={`text-xs text-[#334155] text-right break-all ${mono ? "font-mono" : ""}`}>{value}</span>
    </div>
  );
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

export function PurchaseBillViewDrawer({
  billId,
  clientId,
  vendorName,
  onClose,
  onEdit,
  onReceive,
  onDelete,
  onDuplicate,
  onCancelBill,
  onChanged,
  onToast,
}: {
  billId: string;
  clientId: string;
  /** Resolved by the caller from its own vendors list (get_purchase_bill
   * doesn't embed a vendor join) — avoids a second round trip here. */
  vendorName: string;
  onClose: () => void;
  onEdit: (billId: string) => void;
  onReceive: (billId: string) => void;
  onDelete: (bill: PurchaseBillDetail) => void;
  /** "Duplicate" — hands the full loaded bill to the caller, which stashes it
   * via lib/purchases/duplicateSeed and opens the New Bill route. */
  onDuplicate: (bill: PurchaseBillDetail) => void;
  /** "Cancel Bill" — received bills only (drafts are deleted instead). The
   * caller confirms and POSTs /purchase-bills/{id}/cancel, which reverses the
   * posted journal and the inventory stock-in. */
  onCancelBill: (bill: PurchaseBillDetail) => void;
  /** Called after a vendor payment or debit note is recorded so the caller
   * reloads its list (the bill's paid_paise / status may have changed). */
  onChanged: () => void;
  onToast: (msg: string, type: "success" | "error") => void;
}) {
  const [bill, setBill] = useState<PurchaseBillDetail | null>(null);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const [showJournal, setShowJournal] = useState(false);
  const [journal, setJournal] = useState<JournalEntry | null>(null);
  const [journalLoading, setJournalLoading] = useState(false);
  const [attachmentLoading, setAttachmentLoading] = useState(false);
  const [payOpen, setPayOpen] = useState(false);
  const [dnOpen, setDnOpen] = useState(false);
  const [cnOpen, setCnOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const token = await getAuthToken();
      const [d, tl] = await Promise.all([
        apiGet(`/api/purchase-bills/${billId}`, token),
        apiGet(`/api/timeline?client_id=${clientId}&limit=100`, token),
      ]);
      if (!d.success || !d.data) { setError(true); return; }
      setBill(d.data as PurchaseBillDetail);
      const events = (tl.data as TimelineEvent[]) ?? [];
      const items: ActivityItem[] = events
        .filter((e) => e.entity_type === "purchase_bill" && e.entity_id === billId)
        .map((e) => ({ at: e.created_at ?? "", title: e.title ?? e.event_type ?? "Activity", detail: e.description ?? undefined }))
        .filter((i) => i.at)
        .sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0));
      setActivity(items);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [billId, clientId]);

  useEffect(() => { load(); }, [load]);

  async function openJournal() {
    const next = !showJournal;
    setShowJournal(next);
    if (next && !journal && bill?.journal_entry_id && bill.bill_date) {
      setJournalLoading(true);
      try {
        const token = await getAuthToken();
        const r = await apiGet(
          `/api/accounting/journal?client_id=${clientId}&start_date=${bill.bill_date}&end_date=${bill.bill_date}`,
          token,
        );
        const entries = (r.data as JournalEntry[]) ?? [];
        setJournal(entries.find((e) => e.id === bill.journal_entry_id) ?? null);
      } catch {
        onToast("Unable to load the journal entry", "error");
      } finally {
        setJournalLoading(false);
      }
    }
  }

  async function handleViewAttachment() {
    if (!bill) return;
    setAttachmentLoading(true);
    try {
      const token = await getAuthToken();
      const r = await apiGet(`/api/purchase-bills/${bill.id}/document-url`, token);
      const url = (r.data as { url?: string } | null)?.url;
      if (!r.success || !url) throw new Error(r.error ?? "No attachment available");
      window.open(url, "_blank");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Unable to open the attachment", "error");
    } finally {
      setAttachmentLoading(false);
    }
  }

  const isDraft = bill?.status === "draft";
  const isCancelled = bill?.status === "cancelled";
  const posted = !!bill?.journal_entry_id;
  // (net_payable + credit_note_paise) − paid − debited: issued debit notes
  // reduce the payable and issued purchase credit notes increase it (CGST Act
  // §34) — matches purchase_payments._claim_bill_outstanding plus the §34(3)
  // term, so a corrected bill shows the true balance and Record Payment
  // doesn't pre-fill an amount the backend would reject.
  const outstanding = bill
    ? (bill.net_payable_paise ?? bill.total_paise ?? 0) + (bill.credit_note_paise ?? 0) - (bill.paid_paise ?? 0) - (bill.debited_paise ?? 0)
    : 0;
  const isInterstate = !!bill?.is_interstate;

  return (
    <Drawer open onClose={onClose} title={bill ? (bill.bill_no || "Purchase Bill") : "Purchase Bill"} widthClass="sm:max-w-lg">
      {loading ? (
        <div className="p-6 space-y-5">
          {/* Header detail fields, then the line-items table */}
          <FormSkeleton fields={6} />
          <TableSkeleton cols={7} rows={4} />
        </div>
      ) : error || !bill ? (
        <div className="p-8 text-center">
          <AlertCircle size={28} className="mx-auto mb-3 text-red-500" />
          <p className="text-sm font-semibold text-[#334155]">Couldn&apos;t load this purchase bill</p>
          <button onClick={load} className="mt-3 text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Retry</button>
        </div>
      ) : (
        <div className="p-5 space-y-5">
          {/* ── Header ──────────────────────────────────────────────────── */}
          <section className="space-y-2.5">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-[#0F172A] truncate">{vendorName || "—"}</p>
                <p className="text-[10px] text-[#94A3B8]">{isInterstate ? "Inter-state · IGST" : "Intra-state · CGST+SGST"}</p>
              </div>
              <div className="text-right flex-shrink-0">
                <p className="text-base font-semibold text-[#0F172A] font-mono">{fmt(bill.total_paise ?? 0)}</p>
                <p className="text-[10px] text-[#94A3B8]">Grand total</p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${PB_STATUS_BADGE[bill.status] ?? "bg-[#F1F5F9] text-[#64748B]"}`}>
                {bill.status.replace("_", " ")}
              </span>
              {bill.is_reverse_charge && (
                <>
                  <span className="text-[#E2E8F0]">·</span>
                  <span className="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200">RCM</span>
                </>
              )}
              {bill.document_url && (
                <>
                  <span className="text-[#E2E8F0]">·</span>
                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-[#F8FAFC] text-[#94A3B8] border border-[#E2E8F0]">
                    <Paperclip size={9} /> Attached
                  </span>
                </>
              )}
            </div>

            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 pt-1">
              <DetailRow label="Bill date" value={bill.bill_date} />
              <DetailRow label="Due date" value={bill.due_date ?? "—"} />
              <DetailRow label="Outstanding" value={fmt(outstanding)} />
              {(() => {
                const days = bill.credit_days ?? (bill.due_date ? diffDaysISO(bill.bill_date, bill.due_date) : null);
                return <DetailRow label="Terms" value={days == null ? "—" : termLabelForDays(days)} />;
              })()}
              <DetailRow label="Vendor invoice no." value={bill.bill_no || "—"} />
              <DetailRow label="Our reference" value={bill.our_reference ?? "—"} />
              <DetailRow label="Notes" value={bill.notes ?? "—"} />
            </div>
          </section>

          {/* ── Action bar (status-gated) ───────────────────────────────── */}
          {!isCancelled && (
            <div className="flex flex-wrap gap-2 pt-1">
              {/* Edit is available for any non-cancelled bill — a draft gets
                  the full editor, a received/partially-paid/paid bill opens
                  the same editor scoped to its soft fields only (our
                  reference, notes, payment terms, due date, attachment); see
                  PurchaseBillEditor's isLocked handling. */}
              <Action onClick={() => onEdit(bill.id)} icon={<Pencil size={12} />}>Edit</Action>
              {isDraft && <Action primary onClick={() => onReceive(bill.id)} icon={<CheckCircle size={12} />}>Receive</Action>}
              {/* Record Payment — parity with the Sales drawer: a vendor
                  payment is recorded straight from the bill rather than only
                  on the Payments tab. Received/partially-paid bills with an
                  outstanding balance only (a draft isn't posted; a paid bill
                  has nothing left to settle). */}
              {(bill.status === "received" || bill.status === "partially_paid") && outstanding > 0 && (
                <Action primary onClick={() => setPayOpen(true)} icon={<CreditCard size={12} />}>Record Payment</Action>
              )}
              {/* Debit Note — the AP mirror of the Sales drawer's Credit Note:
                  correct a received bill's amount/quantity/item by issuing a
                  Debit Note (CGST Act §34) instead of editing the frozen bill. */}
              {!isDraft && <Action onClick={() => setDnOpen(true)} icon={<FilePlus2 size={12} />}>Debit Note</Action>}
              {/* Credit Note — the increase-side mirror of Debit Note (CGST Act
                  §34(3)): the vendor undercharged us and we now owe more. */}
              {!isDraft && <Action onClick={() => setCnOpen(true)} icon={<FilePlus2 size={12} />}>Credit Note</Action>}
              <Action onClick={() => onDuplicate(bill)} icon={<Copy size={12} />}>Duplicate</Action>
              {isDraft && <Action danger onClick={() => onDelete(bill)} icon={<Trash2 size={12} />}>Delete</Action>}
              {/* Received + unpaid only: the backend deletes drafts instead, and
                  refuses to cancel a bill with payments (reverse those first). */}
              {bill.status === "received" && (bill.paid_paise ?? 0) === 0 && (
                <Action danger onClick={() => onCancelBill(bill)} icon={<Ban size={12} />}>Cancel Bill</Action>
              )}
              {bill.document_url && (
                <Action onClick={handleViewAttachment} icon={attachmentLoading ? <Loader2 size={12} className="animate-spin" /> : <Paperclip size={12} />}>
                  View Attachment
                </Action>
              )}
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
                  {bill.lines.map((l, i) => (
                    <tr key={l.id ?? i}>
                      <td className="px-2 py-1.5 text-[#334155]">{l.description}</td>
                      <td className="px-2 py-1.5 font-mono text-[#64748B]">{l.hsn_sac || "—"}</td>
                      <td className="px-2 py-1.5 text-right text-[#334155]">{l.quantity}</td>
                      <td className="px-2 py-1.5 text-[#64748B]">{l.unit || "NOS"}</td>
                      <td className="px-2 py-1.5 text-right font-mono text-[#334155]">{fmt(l.rate_paise)}</td>
                      <td className="px-2 py-1.5 text-right text-[#334155]">{l.gst_rate_bps / 100}%</td>
                      <td className="px-2 py-1.5 text-right font-mono text-[#0F172A]">
                        {l.line_total_paise != null ? fmt(l.line_total_paise) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* ── GST / TDS breakdown ─────────────────────────────────────── */}
          <section className="space-y-1.5">
            <h4 className="text-xs font-semibold text-[#334155]">GST &amp; TDS</h4>
            <DetailRow label="Taxable value" value={fmt(bill.taxable_amount_paise ?? 0)} />
            {isInterstate ? (
              <DetailRow label="IGST" value={fmt(bill.igst_paise ?? 0)} />
            ) : (
              <>
                <DetailRow label="CGST" value={fmt(bill.cgst_paise ?? 0)} />
                <DetailRow label="SGST" value={fmt(bill.sgst_paise ?? 0)} />
              </>
            )}
            {(bill.tds_paise ?? 0) > 0 && (
              <DetailRow
                label={`TDS ${bill.tds_section ? `§${bill.tds_section}` : ""}${bill.tds_rate_bps ? ` @ ${(bill.tds_rate_bps / 100).toFixed(1)}%` : ""}`}
                value={fmt(bill.tds_paise ?? 0)}
              />
            )}
            <DetailRow label="Net payable" value={fmt(bill.net_payable_paise ?? bill.total_paise ?? 0)} />
          </section>

          {/* ── Accounting / View Journal drill-through ─────────────────── */}
          <section className="space-y-2">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-semibold text-[#334155]">Accounting</h4>
              {posted && (
                <button onClick={openJournal} className="text-[11px] text-blue-600 hover:underline flex items-center gap-1">
                  <BookOpen size={11} /> View Journal {showJournal ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
                </button>
              )}
            </div>
            <DetailRow label="Posting status" value={posted ? "Posted" : "Not posted"} />
            <DetailRow label="Journal entry" value={bill.journal_entry_id ?? "—"} mono />
            <DetailRow label="Received at" value={bill.received_at ? formatDateTime(bill.received_at) : "—"} />
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
                  <p className="text-[11px] text-[#94A3B8] py-1">Journal {bill.journal_entry_id} — line detail unavailable here.</p>
                )}
              </div>
            )}
          </section>

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
                    <p className="text-[10px] text-[#CBD5E1]">{formatDateTime(a.at)}</p>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      )}

      {payOpen && bill && (
        <RecordVendorPaymentModal
          bill={bill}
          clientId={clientId}
          outstanding={outstanding}
          onClose={() => setPayOpen(false)}
          onDone={() => { setPayOpen(false); onToast(`Payment recorded for ${bill.bill_no || "bill"}`, "success"); onChanged(); load(); }}
          onError={(m) => onToast(m, "error")}
        />
      )}
      {dnOpen && bill && (
        <CreateDebitNoteModal
          bill={bill}
          clientId={clientId}
          onClose={() => setDnOpen(false)}
          onDone={(dnNo) => { setDnOpen(false); onToast(`Debit note ${dnNo} created (draft)`, "success"); onChanged(); }}
          onError={(m) => onToast(m, "error")}
        />
      )}
      {cnOpen && bill && (
        <CreatePurchaseCreditNoteModal
          bill={bill}
          clientId={clientId}
          onClose={() => setCnOpen(false)}
          onDone={(cnNo) => { setCnOpen(false); onToast(`Credit note ${cnNo} created (draft)`, "success"); onChanged(); }}
          onError={(m) => onToast(m, "error")}
        />
      )}
    </Drawer>
  );
}

// ── Record Vendor Payment (reuses POST /api/purchase-payments) ──────────────
// Parity with the Sales drawer's RecordPaymentModal. The TDS was already
// deducted at the bill stage (IT Act §194) — this settles the NET payable, so
// the outstanding shown here is net_payable_paise − paid_paise.
function RecordVendorPaymentModal({ bill, clientId, outstanding, onClose, onDone, onError }: {
  bill: PurchaseBillDetail; clientId: string; outstanding: number;
  onClose: () => void; onDone: () => void; onError: (m: string) => void;
}) {
  const today = new Date().toISOString().split("T")[0];
  const [amount, setAmount] = useState(String(outstanding / 100));
  const [date, setDate] = useState(today);
  const [mode, setMode] = useState("bank");
  const [reference, setReference] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit() {
    const amountPaise = Math.round((parseFloat(amount) || 0) * 100);
    if (amountPaise <= 0) { onError("Enter a valid amount."); return; }
    if (amountPaise > outstanding) { onError("Amount exceeds the outstanding balance."); return; }
    setSaving(true);
    try {
      const token = await getAuthToken();
      // Reuses the single vendor-payment engine; the link settles THIS bill.
      const r = await apiCall("/api/purchase-payments", "POST", {
        client_id: clientId,
        vendor_id: bill.vendor_id,
        payment_date: date,
        amount_paise: amountPaise,
        payment_mode: mode,
        reference_no: reference.trim() || undefined,
        purchase_bill_id: bill.id,
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
    <ModalShell title={`Record Payment — ${bill.bill_no || "Purchase Bill"}`} onClose={onClose}>
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

// ── Create Debit Note (reuses POST /api/debit-notes) ────────────────────────
// AP mirror of the Sales drawer's CreateCreditNoteModal. A full-value DRAFT
// debit note copying the bill's lines, linked via purchase_bill_id; the CA
// adjusts or issues it from the Debit Notes tab (CGST Act §34).
function CreateDebitNoteModal({ bill, clientId, onClose, onDone, onError }: {
  bill: PurchaseBillDetail; clientId: string;
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
      const lines = bill.lines.map((l) => ({
        description: l.description,
        hsn_sac: l.hsn_sac ?? "",
        quantity: l.quantity,
        rate_paise: l.rate_paise,
        gst_rate_percent: (l.gst_rate_bps ?? 0) / 100,
        service_catalogue_id: l.service_catalogue_id ?? undefined,
      }));
      const r = await apiCall("/api/debit-notes/", "POST", {
        client_id: clientId,
        vendor_id: bill.vendor_id,
        debit_note_date: date,
        lines,
        purchase_bill_id: bill.id,
        is_interstate: !!bill.is_interstate,
        is_reverse_charge: !!bill.is_reverse_charge,
        reason: reason.trim() || undefined,
      }, token);
      if (!r.success) throw new Error(r.error ?? "Failed to create debit note");
      const data = r.data as { debit_note_no?: string; dn_no?: string } | null;
      onDone(data?.debit_note_no ?? data?.dn_no ?? "");
    } catch (e) {
      onError(e instanceof Error ? e.message : "Failed to create debit note");
    } finally {
      setSaving(false);
    }
  }

  return (
    <ModalShell title={`Debit Note — ${bill.bill_no || "Purchase Bill"}`} onClose={onClose}>
      <p className="text-[11px] text-[#64748B]">Creates a full-value <strong>draft</strong> debit note copying this bill&apos;s lines. Adjust or issue it from the Debit Notes tab (CGST Act §34).</p>
      <Field label="Debit note date"><input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={inputCls} /></Field>
      <Field label="Reason / notes"><textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} placeholder="Reason for the debit note (return, rate correction…)" className={inputCls} /></Field>
      <ModalActions onClose={onClose} onSubmit={submit} saving={saving} label="Create Debit Note" />
    </ModalShell>
  );
}

// ── Create Purchase Credit Note (reuses POST /api/purchase-credit-notes) ────
// The increase-side mirror of CreateDebitNoteModal (CGST Act §34(3)): the
// vendor undercharged us on this bill and we now owe more.
function CreatePurchaseCreditNoteModal({ bill, clientId, onClose, onDone, onError }: {
  bill: PurchaseBillDetail; clientId: string;
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
      const lines = bill.lines.map((l) => ({
        description: l.description,
        hsn_sac: l.hsn_sac ?? "",
        quantity: l.quantity,
        rate_paise: l.rate_paise,
        gst_rate_percent: (l.gst_rate_bps ?? 0) / 100,
        service_catalogue_id: l.service_catalogue_id ?? undefined,
      }));
      const r = await apiCall("/api/purchase-credit-notes/", "POST", {
        client_id: clientId,
        vendor_id: bill.vendor_id,
        credit_note_date: date,
        lines,
        purchase_bill_id: bill.id,
        is_interstate: !!bill.is_interstate,
        is_reverse_charge: !!bill.is_reverse_charge,
        reason: reason.trim() || undefined,
      }, token);
      if (!r.success) throw new Error(r.error ?? "Failed to create credit note");
      const data = r.data as { credit_note_no?: string } | null;
      onDone(data?.credit_note_no ?? "");
    } catch (e) {
      onError(e instanceof Error ? e.message : "Failed to create credit note");
    } finally {
      setSaving(false);
    }
  }

  return (
    <ModalShell title={`Credit Note — ${bill.bill_no || "Purchase Bill"}`} onClose={onClose}>
      <p className="text-[11px] text-[#64748B]">Creates a full-value <strong>draft</strong> credit note copying this bill&apos;s lines — for when the vendor undercharged us and we owe more. Adjust or issue it from the Credit Notes tab (CGST Act §34(3)).</p>
      <Field label="Credit note date"><input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={inputCls} /></Field>
      <Field label="Reason / notes"><textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} placeholder="Reason for the credit note" className={inputCls} /></Field>
      <ModalActions onClose={onClose} onSubmit={submit} saving={saving} label="Create Credit Note" />
    </ModalShell>
  );
}

// ── Modal primitives (local, compact — mirror InvoiceViewDrawer's) ──────────
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
