/**
 * A ledger balance and the side it is on.
 *
 * ── WHY A COMPONENT ─────────────────────────────────────────────────────────
 * Three screens render this and each decided the side differently: the account
 * ledger takes a SEPARATE `is_debit` from the server, the customer statement
 * derives it as `p >= 0`, and the bank reconciliation puts debits and credits
 * in two columns and reads whichever is non-zero. Only the first is the
 * server's answer; the other two are the browser deciding.
 *
 * ── A NIL BALANCE HAS NO SIDE, AND `>= 0` PUTS IT ON THE DEBIT ONE ──────────
 * `app/clients/[id]/sales/page.tsx` read `p >= 0 ? "Dr" : "Cr"`, so a customer
 * who has settled every invoice showed **"₹0.00 Dr"** on their statement —
 * a positive statement that they owe nothing *as a debtor*, which is not what
 * a nil balance says. It says the account is square. Tally prints a nil
 * closing balance with no side for exactly this reason, and a CA reading
 * "0.00 Dr" on a statement they are about to send out will look for the
 * debit.
 *
 * So `side` is a TRI-STATE: `"debit"`, `"credit"`, or `null` for nil. The
 * derivation from a signed figure is in ONE place (`sideOf`) and it answers
 * `null` at zero.
 *
 * ── THE SERVER'S ANSWER WINS ────────────────────────────────────────────────
 * `account_ledger_page` returns `is_debit` / `opening_is_debit` /
 * `closing_is_debit` beside each figure, because which side an account's
 * balance sits on is a property of the ACCOUNT (a bank overdraft is a credit
 * balance on an asset ledger) and not of the number's sign. Where a caller
 * has that, it passes it; `sideOf` is the fallback for a payload that carries
 * only a signed figure.
 *
 * ── THE MONEY GOES THROUGH THE ONE FORMATTER ────────────────────────────────
 * `lib/money/format.formatPaise` — Indian grouping, two decimals, and "—" for
 * a figure that is absent rather than nil (D5/D6). The magnitude is shown
 * unsigned because the SIDE carries the sign; printing both is how a statement
 * comes to read "-₹1,23,456.78 Cr".
 */
import * as React from "react";
import { cn } from "@/lib/utils";
import { formatPaise, toPaise, NO_FIGURE, type PaiseInput } from "@/lib/money/format";

export type LedgerSide = "debit" | "credit" | null;

/** The side a SIGNED figure sits on, positive being a debit. `null` at zero —
 *  a square account is on neither side. */
export function sideOf(paise: PaiseInput): LedgerSide {
  const p = toPaise(paise);
  if (p === null || p === 0) return null;
  return p > 0 ? "debit" : "credit";
}

export const SIDE_LABEL: Record<"debit" | "credit", string> = {
  debit: "Dr",
  credit: "Cr",
};

export interface DrCrProps {
  paise: PaiseInput;
  /** The server's answer where it has one. Omitted, the side is derived from
   *  the sign; `true`/`false` is the `is_debit` boolean the ledger serves. */
  isDebit?: boolean | null;
  className?: string;
  /** Renders the Dr/Cr marker smaller and quieter, as the account ledger does.
   *  Off by default: on a statement the side is as load-bearing as the figure. */
  quiet?: boolean;
}

export function DrCr({ paise, isDebit, className, quiet }: DrCrProps) {
  const p = toPaise(paise);
  const side: LedgerSide =
    isDebit === true ? "debit" : isDebit === false ? "credit" : sideOf(p);
  const text = p === null ? NO_FIGURE : formatPaise(Math.abs(p));
  return (
    <span className={cn("tabular-nums", className)}>
      {text}
      {side && (
        <span className={cn("ml-1", quiet ? "text-3xs font-normal opacity-60" : "text-2xs")}>
          {SIDE_LABEL[side]}
        </span>
      )}
    </span>
  );
}
