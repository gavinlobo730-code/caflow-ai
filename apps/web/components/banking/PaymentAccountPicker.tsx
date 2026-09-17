/**
 * Which of the client's own bank accounts this money moved through.
 *
 * ONE PICKER, BECAUSE THE EMPTY OPTION IS A DISCLOSURE (ACC-03).
 *
 * `domain/accounting/payment_account.resolve_payment_account` decides the cash
 * leg's ledger in three steps: a stated `bank_account_id` wins, a cash
 * `payment_mode` goes to Cash in Hand, and otherwise it falls through to the
 * firm's GENERIC `%Bank%` ledger — a fallback, flagged `is_fallback`, which
 * posts and balances fine and can land in the wrong sub-ledger. A client with
 * two current accounts banks at both, and the resolver deliberately does NOT
 * guess which.
 *
 * So the "not specified" option has to SAY what it does. That sentence is the
 * whole reason this is a component rather than three `<select>`s: the receipt
 * screen had one, the two vendor-payment doors had none at all, and three
 * copies is how the wording drifts until one of them reads as a neutral blank.
 *
 * IT IS NOT REQUIRED, AND MUST NOT BECOME REQUIRED. A document recorded before
 * migration 342 has no account and never will, and refusing a payment for want
 * of one would stop a CA recording money that has already left the bank.
 *
 * HIDDEN ON A CASH PAYMENT, for the reason the receipt screen records: cash did
 * not go into or out of a bank, and offering an account there is what makes
 * somebody pick one and mis-post it.
 */
"use client";

import { useEffect, useState } from "react";
import { getSupabaseClient } from "@/lib/supabase/client";

export interface BankAccountOption {
  id: string;
  bank_name: string;
  account_no: string;
}

export interface PaymentAccountPickerProps {
  clientId: string;
  value: string;
  onChange: (id: string) => void;
  /** "Paid From" on a payment, "Deposited Into" on a receipt. */
  label: string;
  /** Hidden entirely when this is a cash mode. */
  paymentMode?: string;
  /** Supply the rows where the parent already fetched them in one round trip. */
  accounts?: BankAccountOption[];
  className?: string;
}

/** The modes that mean physical cash — `domain/accounting/payment_account`'s
 *  own list, which is the authority; kept short here and not extended, because
 *  cheque, UPI, NEFT and RTGS all move money THROUGH an account. */
const CASH_MODES = new Set(["cash", "petty_cash"]);

export function PaymentAccountPicker({
  clientId, value, onChange, label, paymentMode, accounts, className,
}: PaymentAccountPickerProps) {
  const [fetched, setFetched] = useState<BankAccountOption[]>([]);
  const supplied = accounts !== undefined;

  useEffect(() => {
    if (supplied || !clientId) return;
    let cancelled = false;
    (async () => {
      const { data } = await getSupabaseClient()
        .from("bank_accounts")
        .select("id, bank_name, account_no")
        .eq("client_id", clientId)
        .eq("is_active", true)
        .order("bank_name");
      if (!cancelled) setFetched((data as BankAccountOption[]) ?? []);
    })();
    return () => { cancelled = true; };
  }, [clientId, supplied]);

  if (paymentMode && CASH_MODES.has(paymentMode)) return null;
  const rows = supplied ? accounts! : fetched;

  return (
    <div className={className}>
      <label className="block text-xs font-medium text-ps-label mb-1">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-3 py-1.5 text-xs border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand"
      >
        <option value="">Not specified — posts to the general Bank ledger</option>
        {rows.map((b) => (
          <option key={b.id} value={b.id}>
            {b.bank_name} — {String(b.account_no || "").slice(-4)}
          </option>
        ))}
      </select>
    </div>
  );
}
