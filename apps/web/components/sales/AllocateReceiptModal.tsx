"use client";

/**
 * APPLY A RECEIPT TO INVOICES (SALES-14).
 *
 * `PATCH /api/receipts/{id}/allocate` has existed and been correct since task
 * H3: it reverses this receipt's prior allocations, re-validates every new one
 * against the invoice's LIVE outstanding, re-applies, and rewrites
 * `receipts.unallocated_paise`. A grep of apps/web for it returned nothing.
 *
 * So a customer who paid in advance — or paid a round figure across three
 * invoices — had money sitting in the books that could not be applied to the
 * invoices it was for from anywhere in the product. The receipts table even
 * had an "Unallocated" column and an "Unallocated only" filter, so the product
 * showed the CA the problem every month and offered no way to fix it.
 *
 * IT REPLACES THE WHOLE SET, NOT ONE LINE. The endpoint reverses everything
 * first and re-applies what it is sent, so the modal loads the existing
 * allocations and submits all of them. Sending only the new line would silently
 * un-apply the others.
 *
 * THE CEILING IS THE SERVER'S. Each invoice's cap here is its generated
 * `outstanding_paise` column (migration 278: total + debit notes − paid −
 * credited, CGST Act §34) PLUS whatever this receipt already has on it, because
 * that is reversed before the new figures are applied — which is exactly the
 * arithmetic routers/receipts.py does. The server re-checks it and answers 422;
 * this only stops the CA typing a figure that will be refused.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { getSupabaseClient } from "@/lib/supabase/client";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import {
  allocationProblems, ceilingFor as ceilingOf, settlementValue,
} from "@/lib/sales/receiptAllocation";

type OpenInvoice = {
  id: string;
  invoice_no: string;
  invoice_date: string;
  total_paise: number;
  outstanding_paise: number;
  status: string;
};

function fmt(paise: number) {
  return "₹" + (paise / 100).toLocaleString("en-IN", {
    minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function AllocateReceiptModal({
  receipt, clientId, onClose, onSaved,
}: {
  receipt: { id: string; receipt_no: string; customer_id: string;
             customer_name?: string; amount_paise: number;
             allocated_paise?: number; tds_paise?: number };
  clientId: string;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const [invoices, setInvoices] = useState<OpenInvoice[]>([]);
  const [prior, setPrior] = useState<Record<string, number>>({});
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setLoadFailed(false);
    const supabase = getSupabaseClient();
    try {
      const [{ data: allocData, error: allocErr }, { data: invData, error: invErr }] =
        await Promise.all([
          supabase.from("receipt_allocations")
            .select("sales_invoice_id, allocated_paise")
            .eq("receipt_id", receipt.id),
          supabase.from("client_sales_invoices")
            .select("id, invoice_no, invoice_date, total_paise, outstanding_paise, status")
            .eq("client_id", clientId)
            .eq("customer_id", receipt.customer_id)
            // A draft or cancelled invoice cannot receive a payment — the
            // endpoint refuses it, so it is not offered.
            .not("status", "in", "(draft,cancelled)")
            .order("invoice_date", { ascending: true })
            .order("id"),
        ]);
      if (allocErr) throw allocErr;
      if (invErr) throw invErr;

      const priorMap: Record<string, number> = {};
      for (const a of (allocData ?? []) as { sales_invoice_id: string; allocated_paise: number }[]) {
        priorMap[a.sales_invoice_id] =
          (priorMap[a.sales_invoice_id] ?? 0) + Number(a.allocated_paise ?? 0);
      }
      setPrior(priorMap);

      // An invoice this receipt already paid IN FULL has no outstanding left,
      // and it still has to be listed — otherwise re-allocating away from it
      // would be impossible and its line would silently vanish from the set
      // the modal submits.
      const rows = ((invData ?? []) as unknown as OpenInvoice[]).filter(
        (i) => Number(i.outstanding_paise ?? 0) > 0 || priorMap[i.id] > 0);
      setInvoices(rows);
      setAmounts(Object.fromEntries(rows.map((i) => [
        i.id, priorMap[i.id] ? String(priorMap[i.id] / 100) : ""])));
    } catch {
      setInvoices([]);
      setLoadFailed(true);
    } finally { setLoading(false); }
  }, [receipt.id, receipt.customer_id, clientId]);

  useEffect(() => { load(); }, [load]);

  function ceilingFor(inv: OpenInvoice) {
    return ceilingOf(inv, prior[inv.id] ?? 0);
  }

  // The SETTLEMENT value, not the cash — see lib/sales/receiptAllocation.
  const settlement = settlementValue(receipt);
  const entered = invoices.map((i) => ({
    invoiceId: i.id,
    paise: (amounts[i.id] ?? "").trim() === "" ? 0 : paiseFromRupeeInput(amounts[i.id] ?? ""),
    ceiling: ceilingFor(i),
  }));
  const problems = allocationProblems(entered, settlement);
  const messageFor = (id: string) =>
    problems.perLine.find((p) => p.invoiceId === id)?.message;
  const total = problems.total;
  const overRun = problems.overRun;

  async function save() {
    setSaving(true); setErr(null);
    try {
      const res = await api.receipts.allocate(
        receipt.id,
        entered.filter((e) => (e.paise ?? 0) > 0)
          .map((e) => ({ sales_invoice_id: e.invoiceId, allocated_paise: e.paise! })));
      if (!res?.success) throw new Error(res?.error ?? "That did not save.");
      const left = res.data?.unallocated_paise;
      onSaved(left && left > 0
        ? `${receipt.receipt_no} applied. ${fmt(left)} is still unallocated.`
        : `${receipt.receipt_no} fully applied.`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "That did not save.");
    } finally { setSaving(false); }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/25 p-4" onClick={onClose}>
      <div className="w-full max-w-[720px] max-h-[88vh] overflow-y-auto bg-white rounded-xl shadow-xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 bg-white border-b border-[#E2E8F0] px-5 py-3 flex items-start justify-between gap-3">
          <div>
            <p className="text-[14px] font-semibold text-[#1E293B]">
              Apply {receipt.receipt_no}
            </p>
            <p className="text-[11px] text-[#94A3B8]">
              {receipt.customer_name ?? "Customer"} · {fmt(settlement)} to settle
              {Number(receipt.tds_paise ?? 0) > 0
                ? ` (${fmt(receipt.amount_paise)} received + ${fmt(Number(receipt.tds_paise))} TDS)`
                : ""}
            </p>
          </div>
          <button onClick={onClose}
            className="text-[12px] text-[#64748B] border border-[#E2E8F0] rounded-lg px-2.5 py-1 hover:bg-[#F8FAFC] shrink-0">
            Close
          </button>
        </div>

        <div className="p-5 space-y-3">
          {loading ? <p className="text-[12px] text-[#94A3B8]">Loading open invoices…</p>
            : loadFailed ? (
              <div className="flex items-center gap-3">
                <p className="text-[12px] text-red-600">
                  Couldn&apos;t load this customer&apos;s invoices — the request failed.
                </p>
                <button onClick={load}
                  className="text-[11px] px-2 py-1 border border-[#E2E8F0] rounded-lg text-[#334155] hover:bg-[#F8FAFC]">
                  Retry
                </button>
              </div>
            ) : invoices.length === 0 ? (
              <p className="text-[12px] text-[#94A3B8] py-6 text-center">
                This customer has no open invoices. The receipt stays unallocated —
                an advance against an invoice not yet raised.
              </p>
            ) : (
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="text-left text-[#64748B] border-b border-[#E2E8F0]">
                    <th className="py-1.5 pr-2">Invoice</th>
                    <th className="py-1.5 pr-2">Date</th>
                    <th className="py-1.5 pr-2 text-right">Total</th>
                    <th className="py-1.5 pr-2 text-right">Outstanding</th>
                    <th className="py-1.5">Apply</th>
                  </tr>
                </thead>
                <tbody>
                  {invoices.map((inv) => {
                    const problem = messageFor(inv.id);
                    return (
                      <tr key={inv.id} className="border-b border-[#F1F5F9]">
                        <td className="py-1.5 pr-2 font-mono text-[#1E293B]">{inv.invoice_no}</td>
                        <td className="py-1.5 pr-2 text-[#64748B]">{inv.invoice_date}</td>
                        <td className="py-1.5 pr-2 text-right font-mono">{fmt(inv.total_paise)}</td>
                        <td className="py-1.5 pr-2 text-right font-mono text-amber-700">
                          {fmt(ceilingFor(inv))}
                        </td>
                        <td className="py-1.5">
                          <div className="flex items-center gap-1.5">
                            <input value={amounts[inv.id] ?? ""} type="text" inputMode="decimal"
                              aria-label={`Amount to apply to ${inv.invoice_no}`}
                              onChange={(ev) => setAmounts((a) => ({ ...a, [inv.id]: ev.target.value }))}
                              className={`w-28 px-2 py-1 border rounded text-right text-[11px] outline-none focus:border-blue-400 ${
                                problem ? "border-red-300" : "border-[#E2E8F0]"}`} />
                            <button type="button"
                              onClick={() => setAmounts((a) => ({
                                ...a, [inv.id]: String(ceilingFor(inv) / 100) }))}
                              className="text-[10px] px-1.5 py-1 border border-[#E2E8F0] rounded text-[#475569] hover:bg-[#F8FAFC]">
                              All
                            </button>
                          </div>
                          {problem && (
                            <p className="text-[10px] text-red-600 mt-0.5">{problem}</p>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}

          <div className="flex items-center justify-between border-t border-[#E2E8F0] pt-3 text-[12px]">
            <span className="text-[#64748B]">
              Applying <span className="font-mono text-[#1E293B]">{fmt(total)}</span> of{" "}
              <span className="font-mono">{fmt(settlement)}</span>
              {total < settlement && (
                <> · <span className="text-amber-700">{fmt(settlement - total)} left as an advance</span></>
              )}
            </span>
            <div className="flex gap-2">
              <button onClick={onClose}
                className="px-3 py-1.5 text-[12px] border border-[#E2E8F0] rounded-lg text-[#334155] hover:bg-[#F8FAFC]">
                Cancel
              </button>
              <button onClick={save} disabled={saving || !problems.ok || loading}
                className="px-3 py-1.5 text-[12px] rounded-lg bg-[#1E293B] text-white disabled:opacity-40">
                {saving ? "Applying…" : "Apply"}
              </button>
            </div>
          </div>

          {overRun && (
            <p className="text-[11px] text-red-600">
              That is more than the receipt settles. Reduce a line, or record a
              second receipt.
            </p>
          )}
          {err && <p className="text-[12px] px-3 py-2 rounded-lg bg-red-50 text-red-600">{err}</p>}

          {/* Leaving an advance unallocated is a legitimate outcome, not a
              failure — a customer may genuinely have paid ahead of an invoice.
              Saying so stops the CA hunting for an invoice to force it onto. */}
          <p className="text-[10px] text-[#94A3B8]">
            An amount left over stays on the receipt as unallocated and can be
            applied to a later invoice from here.
          </p>
        </div>
      </div>
    </div>
  );
}
