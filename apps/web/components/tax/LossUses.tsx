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
 * A person who may change loss records (`canEdit`, the compute tier) can RECORD A YEAR'S USE BY HAND and TAKE ANY USE BACK, each with a reason
 * (POST-A-368, items 2 and 3). The controls only ask: `onRecord` / `onTakeBack` are the screen's calls to the server, which refuses in a sentence
 * the dialog shows as written. A use recorded by hand names no return ("recorded by hand for FY ..."), which is a different thing from a return
 * that could not be read or is gone, and is drawn as its own kind. The controls are not offered while the uses are loading or could not be
 * read: a correction made on a list that was not seen is a correction made blind.
 *
 * Nothing here files anything. CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
 */
import { formatWhole } from "@/lib/money/format";
import { Button } from "@/components/ui/button";
import type { LossUse, LossUsesView } from "@/lib/tax/lossUses";

export type LossUsesState = "loading" | "failed" | "ready";

/** How one use reads on the list. A hand entry says so and names no return. */
export function lossUseLine(u: LossUse): string {
  if (u.return_type === "manual") return `FY ${u.financial_year}, recorded by hand: ${formatWhole(u.amount_paise)}`;
  const base = `FY ${u.financial_year}, ${u.return_type} return${u.acknowledgement_number ? `, acknowledgement ${u.acknowledgement_number}` : ""}: ${formatWhole(u.amount_paise)}`;
  return base + (u.filing_found === false ? " (that return is no longer on file)" : u.filing_found === null ? " (the return's details could not be read just now)" : "");
}

export function LossUses({
  state, view, canEdit = false, onRecord, onTakeBack,
}: {
  state: LossUsesState;
  view?: LossUsesView;
  /** May this person change loss records? (The compute tier; the server asks again.) */
  canEdit?: boolean;
  onRecord?: () => void;
  onTakeBack?: (use: LossUse) => void;
}) {
  if (state === "loading") return null;
  if (state === "failed") {
    return <p className="text-3xs text-ps-hint mt-1">Where this loss was used could not be read just now.</p>;
  }
  if (!view) return null;
  const record = canEdit && onRecord ? (
    <Button type="button" variant="plain" size="none" onClick={onRecord}
      className="text-3xs text-brand-dark underline mt-1">
      Record a year&apos;s use by hand
    </Button>
  ) : null;
  if (view.uses.length === 0 && view.hand_recorded_paise === 0) {
    return (
      <div>
        <p className="text-3xs text-ps-hint mt-1">The record shows no use of it.</p>
        {record}
      </div>
    );
  }
  return (
    <div>
      <ul className="text-3xs text-ps-label mt-1 space-y-0.5" aria-label="Where this loss was used">
        {view.uses.map((u) => (
          <li key={u.entry_id}>
            {lossUseLine(u)}
            {canEdit && onTakeBack && (
              <>
                {" "}
                <Button type="button" variant="plain" size="none" onClick={() => onTakeBack(u)}
                  className="text-3xs text-brand-dark underline">
                  Take back
                </Button>
              </>
            )}
          </li>
        ))}
        {view.hand_recorded_paise > 0 && <li>Recorded by hand, not linked to a filed return: {formatWhole(view.hand_recorded_paise)}</li>}
      </ul>
      {record}
    </div>
  );
}
