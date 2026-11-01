"use client";

/**
 * LossUses — under each brought-forward loss, which return used how much of it (POST-A-368, item 1).
 *
 * The loss list used to show "remaining of original" and nothing about why: a loss that was partly used by a filed return looked the same as one
 * a person had typed a smaller figure for. The server records each filed return's use of a loss (POST-A-073) and serves it beside the record
 * (`GET /api/itr/bf-losses`); this draws exactly that. IT ADDS NOTHING UP and holds no rule: the rupees, the years, the kind of return and the
 * acknowledgement numbers are the server's.
 *
 * Three states, kept apart because an unknown is never shown as a value:
 *   * the list could not be read  -> "could not be read just now" (NOT "no use");
 *   * the list was read and the record is in it -> its uses, the part recorded by hand, or "The record shows no use of it";
 *   * the list was read and the record is not in it (just added, or an older server that does not say) -> nothing.
 * A use whose returns could not be read says so ("the return's details could not be read just now") and is never drawn like a return that was found
 * without an acknowledgement number or one that is gone. The part "recorded by hand" is not linked to a filed return: it says nothing about whether
 * a return exists, only that the record holds no link to one.
 * "The record shows no use of it" says what the RECORD holds. It does not say no return used the loss: a return acknowledged before the write-back
 * existed leaves exactly that, which the computation screen names when it finds one.
 *
 * Nothing here files or changes anything. CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
 */
import { formatWhole } from "@/lib/money/format";
import type { LossUsesView } from "@/lib/tax/lossUses";

export type LossUsesState = "loading" | "failed" | "ready";

export function LossUses({ state, view }: { state: LossUsesState; view?: LossUsesView }) {
  if (state === "loading") return null;
  if (state === "failed") {
    return <p className="text-3xs text-ps-hint mt-1">Where this loss was used could not be read just now.</p>;
  }
  if (!view) return null;
  if (view.uses.length === 0 && view.hand_recorded_paise === 0) {
    return <p className="text-3xs text-ps-hint mt-1">The record shows no use of it.</p>;
  }
  return (
    <ul className="text-3xs text-ps-label mt-1 space-y-0.5" aria-label="Where this loss was used">
      {view.uses.map((u) => (
        <li key={u.filing_id}>
          FY {u.financial_year}, {u.return_type} return
          {u.acknowledgement_number ? `, acknowledgement ${u.acknowledgement_number}` : ""}: {formatWhole(u.amount_paise)}
          {u.filing_found === false ? " (that return is no longer on file)" : u.filing_found === null ? " (the return's details could not be read just now)" : ""}
        </li>
      ))}
      {view.hand_recorded_paise > 0 && <li>Recorded by hand, not linked to a filed return: {formatWhole(view.hand_recorded_paise)}</li>}
    </ul>
  );
}
