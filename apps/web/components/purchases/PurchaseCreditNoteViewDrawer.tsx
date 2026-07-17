"use client";

/**
 * PurchaseCreditNoteViewDrawer — read-only detail view + status-gated action
 * bar for a Purchase Credit Note. Structural mirror of DebitNoteViewDrawer.
 * No Cancel/reversal action (deliberately absent platform-wide for notes)
 * and no Record Payment.
 */
import { useState, useEffect, useCallback } from "react";
import { Pencil, Trash2, CheckCircle, Paperclip, BookOpen, Clock, Loader2, ChevronDown, ChevronUp, AlertCircle, Copy } from "lucide-react";
import { Drawer } from "@/components/ui/drawer";
import { apiGet, getAuthToken, fmt } from "@/lib/invoices/shared";
import { formatDateTime } from "@/lib/services/formatting";
import type { PurchaseCreditNoteDetail } from "@/components/purchases/PurchaseCreditNoteEditor";

const PCN_STATUS_BADGE: Record<string, string> = {
  draft: "bg-[#F1F5F9] text-[#64748B]",
  issued: "bg-blue-100 text-blue-700",
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

export function PurchaseCreditNoteViewDrawer({
  pcnId, clientId, vendorName, onClose, onEdit, onIssue, onDelete, onDuplicate,
}: {
  pcnId: string;
  clientId: string;
  vendorName: string;
  onClose: () => void;
  onEdit: (pcnId: string) => void;
  onIssue: (pcn: PurchaseCreditNoteDetail) => void;
  onDelete: (pcn: PurchaseCreditNoteDetail) => void;
  onDuplicate: (pcn: PurchaseCreditNoteDetail) => void;
}) {
  const [pcn, setPcn] = useState<PurchaseCreditNoteDetail | null>(null);
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
        apiGet(`/api/purchase-credit-notes/${pcnId}`, token),
        apiGet(`/api/timeline?client_id=${clientId}&limit=100`, token),
      ]);
      if (!d.success || !d.data) { setError(true); return; }
      setPcn(d.data as PurchaseCreditNoteDetail);
      const events = (tl.data as TimelineEvent[]) ?? [];
      const items: ActivityItem[] = events
        .filter((e) => e.entity_type === "purchase_credit_note" && e.entity_id === pcnId)
        .map((e) => ({ at: e.created_at ?? "", title: e.title ?? e.event_type ?? "Activity", detail: e.description ?? undefined }))
        .filter((i) => i.at)
        .sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0));
      setActivity(items);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [pcnId, clientId]);

  useEffect(() => { load(); }, [load]);

  async function openJournal() {
    const next = !showJournal;
    setShowJournal(next);
    if (next && !journal && pcn?.journal_entry_id && pcn.credit_note_date) {
      setJournalLoading(true);
      try {
        const token = await getAuthToken();
        const r = await apiGet(
          `/api/accounting/journal?client_id=${clientId}&start_date=${pcn.credit_note_date}&end_date=${pcn.credit_note_date}`,
          token,
        );
        const entries = (r.data as JournalEntry[]) ?? [];
        setJournal(entries.find((e) => e.id === pcn.journal_entry_id) ?? null);
      } catch {
        // Best-effort — the drill-through just stays empty.
      } finally {
        setJournalLoading(false);
      }
    }
  }

  async function handleViewAttachment() {
    if (!pcn) return;
    setAttachmentLoading(true);
    try {
      const token = await getAuthToken();
      const r = await apiGet(`/api/purchase-credit-notes/${pcn.id}/document-url`, token);
      const url = (r.data as { url?: string } | null)?.url;
      if (!r.success || !url) throw new Error(r.error ?? "No attachment available");
      window.open(url, "_blank");
    } catch {
      // Best-effort — no toast plumbing on this drawer.
    } finally {
      setAttachmentLoading(false);
    }
  }

  const isDraft = pcn?.status === "draft";
  const posted = !!pcn?.journal_entry_id;
  const isInterstate = !!pcn?.is_interstate;

  return (
    <Drawer open onClose={onClose} title={pcn ? (pcn.credit_note_no || "Credit Note") : "Credit Note"} widthClass="sm:max-w-lg">
      {loading ? (
        <div className="p-6 space-y-3">
          {[...Array(6)].map((_, i) => <div key={i} className="h-10 rounded bg-[#F8FAFC] animate-pulse" />)}
        </div>
      ) : error || !pcn ? (
        <div className="p-8 text-center">
          <AlertCircle size={28} className="mx-auto mb-3 text-red-500" />
          <p className="text-sm font-semibold text-[#334155]">Couldn&apos;t load this credit note</p>
          <button onClick={load} className="mt-3 text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Retry</button>
        </div>
      ) : (
        <div className="p-5 space-y-5">
          <section className="space-y-2.5">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-[#0F172A] truncate">{vendorName || "—"}</p>
                <p className="text-[10px] text-[#94A3B8]">{isInterstate ? "Inter-state · IGST" : "Intra-state · CGST+SGST"}</p>
              </div>
              <div className="text-right flex-shrink-0">
                <p className="text-base font-semibold text-[#0F172A] font-mono">{fmt(pcn.total_paise ?? 0)}</p>
                <p className="text-[10px] text-[#94A3B8]">Credit note total</p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${PCN_STATUS_BADGE[pcn.status] ?? "bg-[#F1F5F9] text-[#64748B]"}`}>
                {pcn.status}
              </span>
              {pcn.is_reverse_charge && (
                <>
                  <span className="text-[#E2E8F0]">·</span>
                  <span className="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200">RCM</span>
                </>
              )}
              {pcn.document_url && (
                <>
                  <span className="text-[#E2E8F0]">·</span>
                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-[#F8FAFC] text-[#94A3B8] border border-[#E2E8F0]">
                    <Paperclip size={9} /> Attached
                  </span>
                </>
              )}
            </div>

            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 pt-1">
              <DetailRow label="CN date" value={pcn.credit_note_date} />
              <DetailRow label="Applied to bill" value={pcn.purchase_bill_id ? "Yes" : "Standalone"} />
              <DetailRow label="Reason" value={pcn.reason ?? "—"} />
              <DetailRow label="Notes" value={pcn.notes ?? "—"} />
            </div>
          </section>

          <div className="flex flex-wrap gap-2 pt-1">
            <Action onClick={() => onEdit(pcn.id)} icon={<Pencil size={12} />}>Edit</Action>
            {isDraft && <Action primary onClick={() => onIssue(pcn)} icon={<CheckCircle size={12} />}>Issue</Action>}
            <Action onClick={() => onDuplicate(pcn)} icon={<Copy size={12} />}>Duplicate</Action>
            {isDraft && <Action danger onClick={() => onDelete(pcn)} icon={<Trash2 size={12} />}>Delete</Action>}
            {pcn.document_url && (
              <Action onClick={handleViewAttachment} icon={attachmentLoading ? <Loader2 size={12} className="animate-spin" /> : <Paperclip size={12} />}>
                View Attachment
              </Action>
            )}
          </div>

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
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F8FAFC]">
                  {pcn.lines.map((l, i) => (
                    <tr key={l.id ?? i}>
                      <td className="px-2 py-1.5 text-[#334155]">{l.description}</td>
                      <td className="px-2 py-1.5 font-mono text-[#64748B]">{l.hsn_sac || "—"}</td>
                      <td className="px-2 py-1.5 text-right text-[#334155]">{l.quantity}</td>
                      <td className="px-2 py-1.5 text-[#64748B]">{l.unit || "NOS"}</td>
                      <td className="px-2 py-1.5 text-right font-mono text-[#334155]">{fmt(l.rate_paise)}</td>
                      <td className="px-2 py-1.5 text-right text-[#334155]">{l.gst_rate_bps / 100}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="space-y-1.5">
            <h4 className="text-xs font-semibold text-[#334155]">GST</h4>
            <DetailRow label="Taxable value" value={fmt(pcn.taxable_amount_paise ?? 0)} />
            {isInterstate ? (
              <DetailRow label="IGST" value={fmt(pcn.igst_paise ?? 0)} />
            ) : (
              <>
                <DetailRow label="CGST" value={fmt(pcn.cgst_paise ?? 0)} />
                <DetailRow label="SGST" value={fmt(pcn.sgst_paise ?? 0)} />
              </>
            )}
          </section>

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
            <DetailRow label="Journal entry" value={pcn.journal_entry_id ?? "—"} mono />
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
                  <p className="text-[11px] text-[#94A3B8] py-1">Journal {pcn.journal_entry_id} — line detail unavailable here.</p>
                )}
              </div>
            )}
          </section>

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
