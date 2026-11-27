import { paiseFromRupeeInput } from "../money/rupeeInput.ts";

/**
 * The year's total income as typed on the unforeseen-income panel (POST-A-075), read for
 * `GET /advance-tax/unforeseen-income?total_income_paise=`.
 *
 * The box is OPTIONAL, and blank means "not given", never nil: without it the server offers no
 * surcharge and says so, which is the truthful answer; a blank read as ₹0 would tell the server the
 * year's income is nil and the bracket would be the lowest one, stated as if it were known. So this
 * does NOT take `paiseFromRupeeInput`'s blank-is-zero; it asks the one parser only about text that
 * is there, and a text that is not an amount (or is below zero) is a problem in words rather than a
 * figure. The server decides everything else: whether the client's kind is offered a surcharge at
 * all, the bracket, the cap and a year the registry does not hold.
 */
export type TotalIncomeReading =
  | { kind: "absent" }
  | { kind: "amount"; paise: number }
  | { kind: "problem"; message: string };

export function readTotalIncome(raw: string): TotalIncomeReading {
  if (raw.trim() === "") return { kind: "absent" };
  const paise = paiseFromRupeeInput(raw);
  if (paise === null) {
    return { kind: "problem", message: "The year's total income is not an amount. Type it in rupees, such as 12500000 or 12500000.50 (commas only where an amount is usually grouped, as in 1,25,00,000), or leave it blank." };
  }
  if (paise < 0) {
    return { kind: "problem", message: "The year's total income cannot be below zero. Leave it blank if it is not known." };
  }
  return { kind: "amount", paise };
}

/**
 * Which offer's answer may still be shown. The total-income box stays editable while an offer is in flight, and an answer computed
 * for a total the person has since changed is about a superseded figure: shown, it would put a surcharge for one total beside a box
 * holding another. So each offer takes a ticket, editing the box (or a newer offer) supersedes every ticket handed out, and only the
 * latest ticket's answer is applied. Nothing about the figures is decided here.
 */
export interface OfferSequence {
  /** A ticket for an offer starting now; it supersedes every earlier one. */
  next(): number;
  /** The figure the offers were for has changed: no ticket handed out so far is current. */
  supersede(): void;
  /** Whether an answer that came back under this ticket may be applied. */
  isCurrent(ticket: number): boolean;
}

export function offerSequence(): OfferSequence {
  let latest = 0;
  return {
    next: () => ++latest,
    supersede: () => { latest += 1; },
    isCurrent: (ticket) => ticket === latest,
  };
}
