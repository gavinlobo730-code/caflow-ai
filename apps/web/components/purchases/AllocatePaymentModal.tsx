"use client";

/**
 * APPLY A VENDOR PAYMENT TO BILLS — the AP mirror of SALES-14, and it was
 * unreachable for exactly as long.
 *
 * `PATCH /api/purchase-payments/{id}/allocate` was written at the same time as
 * the AR one: `purchase_payment_service.update_allocations_core` reverses this
 * payment's prior allocations, re-validates every new one against the bill's
 * LIVE outstanding, re-applies, and rewrites `purchase_payments.
 * unallocated_paise`. Its own docstring calls itself "the AP mirror of
 * receipts.py" and names the two cases it exists for — an advance stranded by
 * a bank-match settlement that exceeded the bills it was told about, and a
 * payment recorded before the bill it is meant for existed. Nothing in
 * `apps/web` called it.
 *
 * WHAT MADE THAT INVISIBLE rather than merely missing: the Purchases screen
 * DOES show an unallocated figure — but only while a payment is being TYPED, a
 * running total inside the form. Once saved, the money simply stopped being
 * mentioned. The AR side at least had an "Unallocated" column showing the CA
 * the problem every month; here there was not even that.
 *
 * IT REPLACES THE WHOLE SET, NOT ONE LINE. The endpoint reverses everything
 * first and re-applies what it is sent, so the modal loads the existing
 * allocations and submits all of them. Sending only the new line would silently
 * un-apply the others.
 *
 * THE CEILING IS THE SERVER'S. Each bill's cap is its generated
 * `outstanding_paise` column (migration 278: net payable + credit notes − paid
 * − debited, CGST Act §34 — and the note SIGNS are the opposite way round from
 * the sales side, which is why this reads the column and never re-subtracts)
 * PLUS whatever this payment already has on it, because that is reversed before
 * the new figures are applied. The server re-checks and answers 422; this only
 * stops the CA typing a figure that will be refused.
 *
 * AND WHAT A PAYMENT SETTLES IS THE CASH ALONE — not cash + TDS, which is the
 * AR rule. `lib/purchases/paymentAllocation.settlementValue` says why.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { getSupabaseClient } from "@/lib/supabase/client";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import {
  allocationProblems, ceilingFor as ceilingOf, settlementValue,
} from "@/lib/purchases/paymentAllocation";
import { Callout } from "@/components/ui/callout";

type OpenBill = {
  id: string;
  bill_no: string | null;
  our_reference: string | null;
  bill_date: string;
  net_payable_paise: number;
  outstanding_paise: number;
  status: string;
};

function fmt(paise: number) {
  return "₹" + (paise / 100).toLocaleString("en-IN", {
    minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** A bill's own number is the VENDOR's; `our_reference` is ours. Both are
 *  legitimately absent — a recurring bill is generated with `bill_no` blank on
 *  purpose (PUR-26), because it is a fact about the landlord's books. */
function billLabel(b: OpenBill): string {
  return b.bill_no || b.our_reference || "(no number)";
}

export default function AllocatePaymentModal({
  payment, clientId, onClose, onSaved,
}: {
  payment: { id: string; payment_no?: string | null; vendor_id: string;
             vendor_name?: string; amount_paise: number;
             allocated_paise?: number; unallocated_paise?: number };
  clientId: string;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const [bills, setBills] = useState<OpenBill[]>([]);
  const [prior, setPrior] = useState<Record<string, number>>({});
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const label = payment.payment_no || "this payment";

  const load = useCallback(async () => {
    setLoading(true); setLoadFailed(false);
    const supabase = getSupabaseClient();
    try {
      const [{ data: allocData, error: allocErr }, { data: billData, error: billErr }] =
        await Promise.all([
          supabase.from("purchase_payment_allocations")
            .select("purchase_bill_id, allocated_paise")
            .eq("purchase_payment_id", payment.id),
          supabase.from("purchase_bills")
            .select("id, bill_no, our_reference, bill_date, net_payable_paise, outstanding_paise, status")
            .eq("client_id", clientId)
            .eq("vendor_id", payment.vendor_id)
            // A draft bill was never received — no AP journal exists yet — and
            // a cancelled one cannot be paid. update_allocations_core refuses
            // both with a 409, so neither is offered.
            .not("status", "in", "(draft,cancelled)")
            .order("bill_date", { ascending: true })
            .order("id"),
        ]);
      if (allocErr) throw allocErr;
      if (billErr) throw billErr;

      const priorMap: Record<string, number> = {};
      for (const a of (allocData ?? []) as { purchase_bill_id: string; allocated_paise: number }[]) {
        priorMap[a.purchase_bill_id] =
          (priorMap[a.purchase_bill_id] ?? 0) + Number(a.allocated_paise ?? 0);
      }
      setPrior(priorMap);

      // A bill this payment already cleared has no outstanding left, and it
      // still has to be listed — otherwise re-allocating away from it would be
      // impossible and its line would silently vanish from the set the modal
      // submits, un-applying it.
      const rows = ((billData ?? []) as unknown as OpenBill[]).filter(
        (b) => Number(b.outstanding_paise ?? 0) > 0 || priorMap[b.id] > 0);
      setBills(rows);
      setAmounts(Object.fromEntries(rows.map((b) => [
        b.id, priorMap[b.id] ? String(priorMap[b.id] / 100) : ""])));
    } catch {
      setBills([]);
      setLoadFailed(true);
    } finally { setLoading(false); }
  }, [payment.id, payment.vendor_id, clientId]);

  useEffect(() => { load(); }, [load]);

  function ceilingFor(bill: OpenBill) {
    return ceilingOf(bill, prior[bill.id] ?? 0);
  }

  // The cash, and only the cash — see lib/purchases/paymentAllocation.
  const settlement = settlementValue(payment);
  const entered = bills.map((b) => ({
    documentId: b.id,
    paise: (amounts[b.id] ?? "").trim() === "" ? 0 : paiseFromRupeeInput(amounts[b.id] ?? ""),
    ceiling: ceilingFor(b),
  }));
  const problems = allocationProblems(entered, settlement);
  const messageFor = (id: string) =>
    problems.perLine.find((p) => p.documentId === id)?.message;
  const total = problems.total;
  const overRun = problems.overRun;

  async function save() {
    setSaving(true); setErr(null);
    try {
      const res = await api.purchasePayments.allocate(
        payment.id,
        entered.filter((e) => (e.paise ?? 0) > 0)
          .map((e) => ({ purchase_bill_id: e.documentId, allocated_paise: e.paise! })));
      if (!res?.success) throw new Error(res?.error ?? "That did not save.");
      const left = res.data?.unallocated_paise;
      onSaved(left && left > 0
        ? `${label} applied. ${fmt(left)} is still unallocated.`
        : `${label} fully applied.`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "That did not save.");
    } finally { setSaving(false); }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/25 p-4" onClick={onClose}>
      <div className="w-full max-w-[720px] max-h-[88vh] overflow-y-auto bg-white rounded-xl shadow-xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 bg-white border-b border-ps-border px-5 py-3 flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-ps-ink">Apply {label}</p>
            <p className="text-2xs text-ps-hint">
              {payment.vendor_name ?? "Vendor"} · {fmt(settlement)} paid
            </p>
          </div>
          <button onClick={onClose}
            className="text-xs text-ps-label border border-ps-border rounded-lg px-2.5 py-1 hover:bg-ps-bg shrink-0">
            Close
          </button>
        </div>

        <div className="p-5 space-y-3">
          {loading ? <p className="text-xs text-ps-hint">Loading open bills…</p>
            : loadFailed ? (
              <div className="flex items-center gap-3">
                <p className="text-xs text-red-600">
                  Couldn&apos;t load this vendor&apos;s bills — the request failed.
                </p>
                <button onClick={load}
                  className="text-2xs px-2 py-1 border border-ps-border rounded-lg text-ps-body hover:bg-ps-bg">
                  Retry
                </button>
              </div>
            ) : bills.length === 0 ? (
              <p className="text-xs text-ps-hint py-6 text-center">
                This vendor has no open bills. The payment stays unallocated —
                an advance against a bill not yet received.
              </p>
            ) : (
              <table className="w-full text-2xs">
                <thead>
                  <tr className="text-left text-ps-label border-b border-ps-border">
                    <th className="py-1.5 pr-2">Bill</th>
                    <th className="py-1.5 pr-2">Date</th>
                    <th className="py-1.5 pr-2 text-right">Net payable</th>
                    <th className="py-1.5 pr-2 text-right">Outstanding</th>
                    <th className="py-1.5">Apply</th>
                  </tr>
                </thead>
                <tbody>
                  {bills.map((bill) => {
                    const problem = messageFor(bill.id);
                    return (
                      <tr key={bill.id} className="border-b border-ps-muted">
                        <td className="py-1.5 pr-2 font-mono text-ps-ink">{billLabel(bill)}</td>
                        <td className="py-1.5 pr-2 text-ps-label">{bill.bill_date}</td>
                        <td className="py-1.5 pr-2 text-right font-mono">{fmt(bill.net_payable_paise)}</td>
                        <td className="py-1.5 pr-2 text-right font-mono text-state-attention">
                          {fmt(ceilingFor(bill))}
                        </td>
                        <td className="py-1.5">
                          <div className="flex items-center gap-1.5">
                            <input value={amounts[bill.id] ?? ""} type="text" inputMode="decimal"
                              aria-label={`Amount to apply to ${billLabel(bill)}`}
                              onChange={(ev) => setAmounts((a) => ({ ...a, [bill.id]: ev.target.value }))}
                              className={`w-28 px-2 py-1 border rounded text-right text-2xs outline-none focus:border-blue-400 ${
                                problem ? "border-red-300" : "border-ps-border"}`} />
                            <button type="button"
                              onClick={() => setAmounts((a) => ({
                                ...a, [bill.id]: String(ceilingFor(bill) / 100) }))}
                              className="text-3xs px-1.5 py-1 border border-ps-border rounded text-ps-label hover:bg-ps-bg">
                              All
                            </button>
                          </div>
                          {problem && (
                            <p className="text-3xs text-red-600 mt-0.5">{problem}</p>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}

          <div className="flex items-center justify-between border-t border-ps-border pt-3 text-xs">
            <span className="text-ps-label">
              Applying <span className="font-mono text-ps-ink">{fmt(total)}</span> of{" "}
              <span className="font-mono">{fmt(settlement)}</span>
              {total < settlement && (
                <> · <span className="text-state-attention">{fmt(settlement - total)} left as an advance</span></>
              )}
            </span>
            <div className="flex gap-2">
              <button onClick={onClose}
                className="px-3 py-1.5 text-xs border border-ps-border rounded-lg text-ps-body hover:bg-ps-bg">
                Cancel
              </button>
              <button onClick={save} disabled={saving || !problems.ok || loading}
                className="px-3 py-1.5 text-xs rounded-lg bg-brand-dark text-white disabled:opacity-40">
                {saving ? "Applying…" : "Apply"}
              </button>
            </div>
          </div>

          {overRun && (
            <p className="text-2xs text-red-600">
              That is more than the payment settles. Reduce a line, or record a
              second payment.
            </p>
          )}
          {err && <Callout tone="problem">{err}</Callout>}

          {/* Leaving an advance unallocated is a legitimate outcome, not a
              failure — a client may genuinely have paid ahead of a bill.
              Saying so stops the CA hunting for a bill to force it onto. */}
          <p className="text-3xs text-ps-hint">
            An amount left over stays on the payment as unallocated and can be
            applied to a later bill from here.
          </p>
        </div>
      </div>
    </div>
  );
}
