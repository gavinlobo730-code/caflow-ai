"use client";

/**
 * InvoiceViewDrawer — read-only invoice detail, the Invoice Hub SHELL (Batch 2).
 * Extracted from the Sales page and rebuilt on the reusable <Drawer> primitive;
 * behaviour is unchanged (loads the invoice + deliveries, shows status/amounts/
 * accounting, links to Edit/Issue/Send/PDF). New Hub actions are deferred.
 */
import { useState, useEffect } from "react";
import { CheckCircle, Download, Pencil, Send } from "lucide-react";
import { Drawer } from "@/components/ui/drawer";
import { formatDateTime } from "@/lib/services/formatting";
import { diffDaysISO } from "@/lib/sales/dateMath";
import { termLabelForDays } from "@/lib/sales/paymentTerms";
import {
  API, apiGet, getAuthToken, fmt, STATUS_BADGE, DELIVERY_STATUS_LABEL,
  type InvoiceDetail, type InvoiceDelivery, type SalesInvoice,
} from "@/lib/invoices/shared";

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

export function InvoiceViewDrawer({
  invoiceId,
  onClose,
  onEdit,
  onIssue,
  onSend,
  onToast,
}: {
  invoiceId: string;
  onClose: () => void;
  onEdit: (inv: SalesInvoice) => void;
  onIssue: (id: string) => void;
  onSend: (inv: SalesInvoice) => void;
  onToast: (msg: string, type: "success" | "error") => void;
}) {
  const [inv, setInv] = useState<InvoiceDetail | null>(null);
  const [deliveries, setDeliveries] = useState<InvoiceDelivery[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const token = await getAuthToken();
        const [d, del] = await Promise.all([
          apiGet(`/api/sales-invoices/${invoiceId}`, token),
          apiGet(`/api/sales-invoices/${invoiceId}/deliveries`, token),
        ]);
        if (cancelled) return;
        if (d.success) setInv(d.data as InvoiceDetail);
        setDeliveries((del.data as InvoiceDelivery[]) ?? []);
      } finally {
        // Clear the skeleton even if a request throws (audit M17).
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [invoiceId]);

  async function handleViewPdf() {
    try { await viewInvoicePdf(invoiceId); }
    catch { onToast("Unable to open PDF", "error"); }
  }

  const customerName = inv?.customers?.name ?? "—";
  const outstanding = inv ? inv.total_paise - (inv.paid_paise ?? 0) : 0;
  const posted = !!inv?.journal_entry_id;
  const lastDelivery = deliveries[0];

  // Thin SalesInvoice projection for the edit / send callbacks.
  const summary: SalesInvoice | null = inv ? {
    id: inv.id, invoice_no: inv.invoice_no, invoice_date: inv.invoice_date,
    due_date: inv.due_date, customer_id: inv.customer_id, customer_name: customerName,
    taxable_paise: inv.taxable_amount_paise, gst_paise: inv.total_gst_paise,
    total_paise: inv.total_paise, paid_paise: inv.paid_paise, status: inv.status,
    supply_state_code: inv.supply_state_code, is_interstate: inv.is_interstate,
  } : null;

  return (
    <Drawer open onClose={onClose} title={inv ? inv.invoice_no : "Invoice"}>
        {loading || !inv ? (
          <div className="p-6 space-y-3">
            {[...Array(5)].map((_, i) => <div key={i} className="h-10 rounded bg-[#F8FAFC] animate-pulse" />)}
          </div>
        ) : (
          <div className="p-5 space-y-5">
            {/* Header */}
            <section className="space-y-2">
              <div className="flex items-center justify-between">
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${STATUS_BADGE[inv.status] ?? "bg-[#F1F5F9] text-[#64748B]"}`}>
                  {inv.status.replace("_", " ")}
                </span>
                <span className="text-[10px] text-[#94A3B8]">{inv.is_interstate ? "Inter-state (IGST)" : "Intra-state (CGST+SGST)"}</span>
              </div>
              <DetailRow label="Customer" value={customerName} />
              <DetailRow label="Invoice Date" value={inv.invoice_date} />
              <DetailRow label="Due Date" value={inv.due_date ?? "—"} />
              {(() => {
                const days = inv.credit_days ?? (inv.due_date ? diffDaysISO(inv.invoice_date, inv.due_date) : null);
                return <DetailRow label="Payment Terms" value={days == null ? "—" : termLabelForDays(days)} />;
              })()}
              <DetailRow label="Amount" value={fmt(inv.total_paise)} />
              <DetailRow label="Outstanding" value={fmt(outstanding)} />
              <DetailRow label="Created By" value={inv.created_by_name ?? "—"} />
            </section>

            {/* Line Items */}
            <section>
              <h4 className="text-xs font-semibold text-[#334155] mb-2">Line Items</h4>
              <div className="overflow-x-auto border border-[#F1F5F9] rounded-lg">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="text-[#94A3B8] border-b border-[#F1F5F9]">
                      <th className="px-2 py-1.5 text-left font-semibold">Description</th>
                      <th className="px-2 py-1.5 text-left font-semibold">HSN/SAC</th>
                      <th className="px-2 py-1.5 text-right font-semibold">Qty</th>
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
                        <td className="px-2 py-1.5 text-right font-mono text-[#334155]">{fmt(l.rate_paise)}</td>
                        <td className="px-2 py-1.5 text-right text-[#334155]">{l.gst_rate_bps / 100}%</td>
                        <td className="px-2 py-1.5 text-right font-mono text-[#0F172A]">{fmt(l.line_total_paise)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            {/* Accounting */}
            <section className="space-y-2">
              <h4 className="text-xs font-semibold text-[#334155]">Accounting</h4>
              <DetailRow label="Journal Entry ID" value={inv.journal_entry_id ?? "—"} mono />
              <DetailRow label="Posting Status" value={posted ? "Posted" : "Not posted"} />
              <DetailRow label="Issued At" value={fmtDateTime(inv.issued_at)} />
            </section>

            {/* Delivery */}
            <section className="space-y-2">
              <h4 className="text-xs font-semibold text-[#334155]">Delivery</h4>
              {lastDelivery ? (
                <>
                  <DetailRow label="Email Status" value={DELIVERY_STATUS_LABEL[lastDelivery.status] ?? lastDelivery.status} />
                  <DetailRow label="Sent To" value={lastDelivery.sent_to} />
                  <DetailRow label="Sent At" value={fmtDateTime(lastDelivery.sent_at ?? lastDelivery.created_at)} />
                  {deliveries.length > 1 && (
                    <div className="text-[10px] text-[#94A3B8] pt-1">{deliveries.length} delivery attempts</div>
                  )}
                </>
              ) : (
                <p className="text-xs text-[#94A3B8]">Not sent yet.</p>
              )}
            </section>

            {/* Actions */}
            <div className="flex flex-wrap gap-2 pt-3 border-t border-[#F1F5F9]">
              {inv.status === "draft" && summary && (
                <button onClick={() => onEdit(summary)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] flex items-center gap-1">
                  <Pencil size={12} /> Edit
                </button>
              )}
              {inv.status === "draft" && (
                <button onClick={() => onIssue(inv.id)} className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center gap-1">
                  <CheckCircle size={12} /> Issue
                </button>
              )}
              {inv.status !== "draft" && inv.status !== "cancelled" && summary && (
                <button onClick={() => onSend(summary)} className="text-xs px-3 py-1.5 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 flex items-center gap-1">
                  <Send size={12} /> Send Email
                </button>
              )}
              <button onClick={handleViewPdf} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] flex items-center gap-1">
                <Download size={12} /> View PDF
              </button>
            </div>
          </div>
        )}
    </Drawer>
  );
}
