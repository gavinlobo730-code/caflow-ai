/**
 * Where a brought-forward loss went, as the server records it (POST-A-368, item 1).
 *
 * `GET /api/itr/bf-losses?client_id=` serves each loss record with `uses` (one item per filed return that used part of it, oldest year
 * first, with the return's acknowledgement number) and `hand_recorded_paise` (the part somebody typed in). Both are built on the server by
 * the rule that offers the loss and writes the return's use back (`domain/income_tax/loss_utilisation.uses_view`). THIS FILE DOES NO
 * ARITHMETIC: it checks the shape of what arrived and hands it on, so the list of losses can say which return holds which part without
 * the browser adding anything up. A payload that is not a list of records is `null`, which the screen words as "could not be read", and
 * never as a loss nobody used.
 */

export interface LossUse {
  filing_id: string;
  financial_year: string;
  return_type: "original" | "revised";
  amount_paise: number;
  /** `null` when the server could not read the returns at all: it says nothing about whether the return is still on file. */
  filing_found: boolean | null;
  acknowledgement_number: string | null;
}

export interface LossUsesView {
  hand_recorded_paise: number;
  uses: LossUse[];
}

const isCount = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && v >= 0;

function useOf(raw: unknown): LossUse | null {
  if (typeof raw !== "object" || raw === null) return null;
  const u = raw as Record<string, unknown>;
  if (typeof u.filing_id !== "string" || typeof u.financial_year !== "string" || !isCount(u.amount_paise)) return null;
  return {
    filing_id: u.filing_id,
    financial_year: u.financial_year,
    return_type: u.return_type === "revised" ? "revised" : "original",
    amount_paise: u.amount_paise,
    filing_found: typeof u.filing_found === "boolean" ? u.filing_found : null,
    acknowledgement_number: typeof u.acknowledgement_number === "string" && u.acknowledgement_number ? u.acknowledgement_number : null,
  };
}

/**
 * The per-loss view from the list the server answered, keyed by the loss record's id; `null` when the payload is not a list. A record that
 * carries no `uses` (an older server that had not been redeployed) is left OUT of the map rather than shown as a loss with no use: the
 * screen then says nothing about it, which is the honest reading of an answer that did not say. So is a record with one malformed item.
 */
export function lossUsesOf(data: unknown): Record<string, LossUsesView> | null {
  if (!Array.isArray(data)) return null;
  const out: Record<string, LossUsesView> = {};
  for (const row of data) {
    if (typeof row !== "object" || row === null) continue;
    const r = row as Record<string, unknown>;
    if (typeof r.id !== "string" || !Array.isArray(r.uses) || !isCount(r.hand_recorded_paise)) continue;
    // One item that is not a use makes the whole record unreadable: showing the others would understate where the loss went.
    const items = r.uses.map(useOf);
    if (items.some((u) => u === null)) continue;
    out[r.id] = { hand_recorded_paise: r.hand_recorded_paise, uses: items as LossUse[] };
  }
  return out;
}
