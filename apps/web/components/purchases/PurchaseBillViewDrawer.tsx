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
import { Pencil, Trash2, CheckCircle, Paperclip, BookOpen, Clock, Loader2, ChevronDown, ChevronUp, AlertCircle } from "lucide-react";
import { Drawer } from "@/components/ui/drawer";
import { apiGet, getAuthToken, fmt } from "@/lib/invoices/shared";
import { formatDateTime } from "@/lib/services/formatting";
import { termLabelForDays } from "@/lib/sales/paymentTerms";
import { diffDaysISO } from "@/lib/sales/dateMath";
import type { PurchaseBillDetail } from "@/components/purchases/PurchaseBillEditor";

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
  const outstanding = bill ? (bill.net_payable_paise ?? bill.total_paise ?? 0) - (bill.paid_paise ?? 0) : 0;
  const isInterstate = !!bill?.is_interstate;

  return (
    <Drawer open onClose={onClose} title={bill ? (bill.bill_no || "Purchase Bill") : "Purchase Bill"} widthClass="sm:max-w-lg">
      {loading ? (
        <div className="p-6 space-y-3">
          {[...Array(6)].map((_, i) => <div key={i} className="h-10 rounded bg-[#F8FAFC] animate-pulse" />)}
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
              {isDraft && <Action danger onClick={() => onDelete(bill)} icon={<Trash2 size={12} />}>Delete</Action>}
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
    </Drawer>
  );
}
