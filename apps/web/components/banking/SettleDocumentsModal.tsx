"use client";
// Settle one bank line across several invoices/bills, with TDS
//
// Moved verbatim out of app/clients/[id]/bank/page.tsx on 2026-09-03, when
// the bank module was rebuilt around ENTRIES (docs/architecture/09-bank-entries.md).
// The 4,964-line page was the reason small changes went unreviewed; each tab
// is its own file now. Behaviour here is unchanged by the move.

import { useEffect, useState, ReactNode } from "react";
import { X } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { CustomerLookup } from "@/components/lookups/CustomerLookup";
import { VendorLookup } from "@/components/lookups/VendorLookup";
import { api } from "@/lib/api";
import { TransactionListSkeleton } from "@/components/ui/skeleton";
import { fmt, rsToP, QueueTxn } from "@/components/banking/shared";

// ── Bank settlement modal ───────────────────────────────────────────────────
// Allocates ONE bank transaction across one or more sales invoices (a credit
// transaction) or purchase bills (a debit transaction) for a single customer/
// vendor — reached from "Settle invoices / TDS" in the Bank Match Queue.
//
// TDS
//   The everyday Indian receipt: a customer settles a ₹1,00,000 invoice,
//   withholds 10% under s.194J of the Income-tax Act 1961, and remits ₹90,000.
//   The invoice is settled IN FULL; only the cash is short. The backend has
//   always supported this (match_and_settle_multi's `tds_paise` raises the
//   allocation cap accordingly) but the modal never collected the figure, so it
//   was always zero and the case had no route through the UI at all.
//
//   TDS is entered by the CA, never inferred. When the modal is opened from a
//   short match suggestion the field is PRE-FILLED with the shortfall the
//   backend measured — a starting figure to confirm or correct, not a decision.

export interface SplitDoc {
  id: string; no: string; date: string; outstanding_paise: number; currency: string;
}
export interface SplitParty { id: string; name: string; gstin?: string | null }
export interface SettlePrefill {
  partyId: string;
  docId: string | null;
  tdsPaise: number;
}

export function MultiInvoiceMatchModal({ txn, clientId, prefill, onClose, onDone, modeSwitch }: {
  txn: QueueTxn; clientId: string; prefill?: SettlePrefill | null;
  onClose: () => void; onDone: () => void;
  /** The across-ledgers / across-documents switch, owned by the caller so both
   *  split editors show the same one in the same place. */
  modeSwitch?: ReactNode;
}) {
  const isCredit = txn.credit_paise > 0;
  const txnAmount = isCredit ? txn.credit_paise : txn.debit_paise;
  const entityType: "sales_invoice" | "purchase_bill" = isCredit ? "sales_invoice" : "purchase_bill";
  const docLabel = isCredit ? "invoice" : "bill";

  const [parties, setParties] = useState<SplitParty[]>([]);
  const [partyId, setPartyId] = useState(prefill?.partyId ?? "");
  const [docs, setDocs] = useState<SplitDoc[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [amounts, setAmounts] = useState<Record<string, string>>({});   // rupees, per doc id
  const [exchangeRate, setExchangeRate] = useState("");
  // TDS withheld by the customer, in rupees as typed. Only meaningful on a
  // credit (a receipt): TDS the client itself withholds on a vendor payment is
  // already carried in the bill's net_payable_paise, so it must not be added a
  // second time here — the backend applies tds_paise to sales invoices only.
  const [tds, setTds] = useState(
    prefill?.tdsPaise ? (prefill.tdsPaise / 100).toFixed(2) : "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const supabase = getSupabaseClient();
      if (isCredit) {
        const { data } = await selectAll<SplitParty>(() =>
          supabase.from("customers").select("id, name, gstin").eq("client_id", clientId).eq("is_active", true).order("name"));
        setParties(data ?? []);
      } else {
        const { data } = await selectAll<SplitParty>(() =>
          supabase.from("vendors").select("id, name, gstin").eq("client_id", clientId).eq("is_active", true).order("name"));
        setParties(data ?? []);
      }
    })();
  }, [clientId, isCredit]);

  useEffect(() => {
    setChecked(new Set()); setAmounts({}); setDocs([]); setError(null);
    if (!partyId) return;
    (async () => {
      setLoadingDocs(true);
      const supabase = getSupabaseClient();
      if (isCredit) {
        const { data } = await selectAll<{
          id: string; invoice_no: string; invoice_date: string; total_paise: number;
          paid_paise: number; credited_paise: number | null; debit_note_paise: number | null;
          status: string; txn_currency: string | null;
        }>(() =>
          supabase.from("client_sales_invoices")
            .select("id, invoice_no, invoice_date, total_paise, paid_paise, credited_paise, debit_note_paise, status, txn_currency")
            .eq("client_id", clientId).eq("customer_id", partyId).is("deleted_at", null)
            .neq("status", "cancelled").neq("status", "draft").order("invoice_date"));
        setDocs((data ?? []).map((r) => ({
          id: r.id, no: r.invoice_no, date: r.invoice_date, currency: r.txn_currency || "INR",
          // Mirrors bank_posting_service._invoice_outstanding (CGST Act §34).
          outstanding_paise: Math.max(
            r.total_paise + (r.debit_note_paise || 0) - r.paid_paise - (r.credited_paise || 0), 0),
        })).filter((d) => d.outstanding_paise > 0));
      } else {
        const { data } = await selectAll<{
          id: string; bill_no: string; bill_date: string; net_payable_paise: number; total_paise: number;
          paid_paise: number; debited_paise: number | null; credit_note_paise: number | null;
          status: string; txn_currency: string | null;
        }>(() =>
          supabase.from("purchase_bills")
            .select("id, bill_no, bill_date, net_payable_paise, total_paise, paid_paise, debited_paise, credit_note_paise, status, txn_currency")
            .eq("client_id", clientId).eq("vendor_id", partyId).is("deleted_at", null)
            .not("status", "in", "(cancelled,draft)").order("bill_date"));
        setDocs((data ?? []).map((r) => ({
          id: r.id, no: r.bill_no, date: r.bill_date, currency: r.txn_currency || "INR",
          // Mirrors bank_posting_service._bill_outstanding.
          outstanding_paise: Math.max(
            (r.net_payable_paise || r.total_paise) + (r.credit_note_paise || 0) - r.paid_paise - (r.debited_paise || 0), 0),
        })).filter((d) => d.outstanding_paise > 0));
      }
      setLoadingDocs(false);
    })();
  }, [partyId, clientId, isCredit]);

  // Opened from a short match suggestion: tick the document the backend
  // matched and allocate its FULL outstanding — the point of the TDS field is
  // that the document clears even though less cash arrived. Runs once the docs
  // for the prefilled party have loaded, and only while nothing is ticked, so
  // it never fights the CA's own selection.
  const prefillDocId = prefill?.docId ?? null;
  useEffect(() => {
    if (!prefillDocId || docs.length === 0 || checked.size > 0) return;
    const doc = docs.find((d) => d.id === prefillDocId);
    if (!doc) return;
    setChecked(new Set([doc.id]));
    setAmounts({ [doc.id]: (doc.outstanding_paise / 100).toFixed(2) });
    // `checked` is deliberately excluded: this must fire when the docs arrive,
    // not re-run every time the selection changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefillDocId, docs]);

  const totalAllocatedPaise = Array.from(checked).reduce((sum, id) => sum + rsToP(parseFloat(amounts[id] || "0") || 0), 0);
  // Mirror of bank_posting_service.match_and_settle_multi's settlement_cap: the
  // documents that can be settled total the cash received PLUS any TDS the
  // customer withheld, because the withheld amount discharges the receivable
  // just as cash does (it lands in TDS receivable instead of the bank).
  const tdsPaise = isCredit ? Math.max(rsToP(parseFloat(tds || "0") || 0), 0) : 0;
  const settlementCap = txnAmount + tdsPaise;
  const remaining = settlementCap - totalAllocatedPaise;
  const checkedCurrencies = new Set(Array.from(checked).map((id) => docs.find((d) => d.id === id)?.currency ?? "INR"));
  const currency = checkedCurrencies.size === 1 ? Array.from(checkedCurrencies)[0] : null;
  const isForeign = currency != null && currency !== "INR";

  function toggle(doc: SplitDoc) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(doc.id)) {
        next.delete(doc.id);
        setAmounts((a) => { const na = { ...a }; delete na[doc.id]; return na; });
      } else {
        next.add(doc.id);
        const alreadyAllocated = Array.from(next).filter((id) => id !== doc.id)
          .reduce((sum, id) => sum + rsToP(parseFloat(amounts[id] || "0") || 0), 0);
        const remainingBefore = Math.max(settlementCap - alreadyAllocated, 0);
        const fill = Math.min(doc.outstanding_paise, remainingBefore);
        setAmounts((a) => ({ ...a, [doc.id]: (fill / 100).toFixed(2) }));
      }
      return next;
    });
  }

  async function save() {
    if (checked.size === 0) { setError(`Select at least one ${docLabel}.`); return; }
    if (checkedCurrencies.size > 1) { setError(`Select ${docLabel}s in a single currency.`); return; }
    if (isForeign && !exchangeRate) { setError("Enter the exchange rate for this foreign-currency settlement."); return; }
    if (totalAllocatedPaise > settlementCap) {
      setError(tdsPaise > 0
        ? "Total allocated exceeds the amount received plus TDS."
        : "Total allocated exceeds the transaction amount.");
      return;
    }
    setSaving(true); setError(null);
    try {
      const res = await api.banking.matchMulti(txn.id, {
        entity_type: entityType,
        allocations: Array.from(checked).map((id) => ({ entity_id: id, allocated_paise: rsToP(parseFloat(amounts[id] || "0") || 0) })),
        tds_paise: tdsPaise > 0 ? tdsPaise : undefined,
        currency: isForeign ? currency! : undefined,
        exchange_rate: isForeign ? exchangeRate : undefined,
      }) as { success: boolean; error?: string | null };
      if (!res.success) { setError(res.error ?? `Could not settle these ${docLabel}s.`); return; }
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : `Could not settle these ${docLabel}s.`);
    } finally {
      // One release covering all three exits. The success path never lowered
      // it at all, which was harmless only because onDone() unmounts this
      // modal — a fact this function should not have to rely on.
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#F1F5F9]">
          <div>
            <h3 className="text-sm font-semibold text-[#0F172A]">Settle {docLabel}s</h3>
            <p className="text-xs text-[#64748B] mt-0.5">{txn.description} · {fmt(txnAmount)} {isCredit ? "credit" : "debit"}</p>
          </div>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
        </div>
        {modeSwitch && <div className="px-5 pt-3">{modeSwitch}</div>}
        <div className="px-5 py-4 space-y-3 overflow-y-auto flex-1">
          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">{isCredit ? "Customer" : "Vendor"} *</label>
            {isCredit ? (
              <CustomerLookup customers={parties} value={partyId} onChange={setPartyId} ariaLabel="Customer" placeholder={`Select customer…`} />
            ) : (
              <VendorLookup vendors={parties} value={partyId} onChange={setPartyId} ariaLabel="Vendor" placeholder={`Select vendor…`} />
            )}
            <p className="text-[10px] text-[#94A3B8] mt-1">All selected {docLabel}s must belong to this one {isCredit ? "customer" : "vendor"}.</p>
          </div>

          {partyId && (
            loadingDocs ? (
              <TransactionListSkeleton rows={3} />
            ) : docs.length === 0 ? (
              <p className="text-xs text-[#94A3B8] text-center py-6">No open {docLabel}s for this {isCredit ? "customer" : "vendor"}.</p>
            ) : (
              <div className="border border-[#F1F5F9] rounded-lg divide-y divide-[#F8FAFC]">
                {docs.map((d) => (
                  <div key={d.id} className="flex items-center gap-2 px-3 py-2">
                    <input type="checkbox" checked={checked.has(d.id)} onChange={() => toggle(d)} className="h-3.5 w-3.5 rounded border-[#CBD5E1] shrink-0" />
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-medium text-[#1E293B] truncate">{d.no}</p>
                      <p className="text-[10px] text-[#94A3B8]">{d.date} · Outstanding {fmt(d.outstanding_paise)} {d.currency !== "INR" ? d.currency : ""}</p>
                    </div>
                    {checked.has(d.id) && (
                      <input
                        type="number" min="0" step="0.01" value={amounts[d.id] ?? ""}
                        onChange={(e) => setAmounts((a) => ({ ...a, [d.id]: e.target.value }))}
                        className="w-24 border rounded px-2 py-1 text-xs text-right font-mono"
                      />
                    )}
                  </div>
                ))}
              </div>
            )
          )}

          {/* TDS — receipts only. On a vendor payment the withholding is already
              inside the bill's net payable, so adding it here would double it. */}
          {isCredit && (
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">
                TDS withheld by the customer (₹)
              </label>
              <input
                type="number" min="0" step="0.01" value={tds}
                onChange={(e) => setTds(e.target.value)}
                className="w-full border rounded-lg px-3 py-2 text-sm font-mono" placeholder="0.00" />
              <p className="text-[10px] text-[#94A3B8] mt-1">
                {tdsPaise > 0
                  ? `Invoices totalling ${fmt(settlementCap)} can be settled from this ${fmt(txnAmount)} receipt — the ${fmt(tdsPaise)} withheld clears the receivable too.`
                  : "Leave blank unless the customer deducted tax at source. Enter the amount deducted, not the rate."}
              </p>
            </div>
          )}

          {isForeign && (
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Exchange rate ({currency} → INR) *</label>
              <input type="number" step="0.0001" value={exchangeRate} onChange={(e) => setExchangeRate(e.target.value)}
                className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="e.g. 83.25" />
            </div>
          )}

          {checked.size > 0 && (
            <div className={`rounded-lg px-3 py-2 text-xs ${remaining < 0 ? "bg-red-50 text-red-700" : "bg-[#F8FAFC] text-[#475569]"}`}>
              Allocated {fmt(totalAllocatedPaise)} of {fmt(settlementCap)}
              {tdsPaise > 0 && ` (${fmt(txnAmount)} received + ${fmt(tdsPaise)} TDS)`}
              {remaining > 0 && ` — ${fmt(remaining)} will remain unallocated on the ${isCredit ? "receipt" : "payment"}.`}
              {remaining < 0 && (tdsPaise > 0 ? " — exceeds the receipt plus TDS." : " — exceeds the transaction amount.")}
            </div>
          )}
          {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
        </div>
        <div className="flex gap-3 justify-end px-5 py-4 border-t border-[#F1F5F9]">
          <button onClick={onClose} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
          <button onClick={save} disabled={saving || checked.size === 0 || remaining < 0} className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">
            {saving ? "Settling…" : `Confirm allocation`}
          </button>
        </div>
      </div>
    </div>
  );
}

