/**
 * What the TDS register could not establish about a bill, in a form a screen
 * can render.
 *
 * WHY THIS EXISTS
 *     Receiving a purchase bill writes its deduction into tds_deductions, and
 *     services/tds_register_service.py REPORTS what it could not settle:
 *
 *       * the vendor's residency is not classified, so the deduction cannot be
 *         routed to 26Q or 27Q (Rule 31A(4));
 *       * a 27Q deductee row is missing its country of residence or TIN;
 *       * the §195 rate table is reconciled but not line-by-line verified;
 *       * a no-PE declaration is on file but undated;
 *       * Form 15CA is not recorded for a remittance that needs one;
 *       * the deduction is a CATCH-UP: the year's aggregate has been crossed
 *         and this bill carries tax on earlier payments too (§200), so
 *         tds_paise is not taxable × rate and looks wrong unless you know why.
 *
 *     Every one of those has been computed on every foreign-supplier bill since
 *     the register was written, returned in the receive response as
 *     `tds_register.gap_details`, and read by nobody (PUR-14). Payroll's
 *     equivalent has always reached its screen; this is the same shape.
 *
 *     A gap is not an error. The bill received, the journal posted and the
 *     register row was written — what is missing is a fact only the CA holds.
 *     So this renders as an amber note, never as a failure.
 */

export interface RegisterNote {
  /** The vendor the gap is about, when the register named one. */
  vendor: string | null;
  /** The sentence, as the backend wrote it — describe_gaps() is the one place
   *  that words them, so two screens cannot describe one gap differently. */
  text: string;
}

/** What describe_gaps() actually returns — a CODE and the sentence for it.
 *
 *  THIS WAS TYPED AS A BARE string[] AND IT NEVER WAS ONE.
 *  domain/tds/residency.describe_gaps returns
 *  `[{"code": c, "message": GAP_MESSAGES.get(c, "")}]`, and its docstring has
 *  said so since it was written. The declaration below said `string[]`, so
 *  TypeScript typed the objects as strings and let them through to `{n.text}` —
 *  and React THROWS on a plain object child ("Objects are not valid as a React
 *  child (found: object with keys {code, message})"). Every gap the register
 *  reported took the purchases page down with it, which is worse than the
 *  silence PUR-14 fixed: the CA lost the screen instead of the sentence.
 *
 *  Found while wiring the payment path onto the same vocabulary; nothing in the
 *  bill path had a test that fed a real backend payload through, only source
 *  scans that check the call is made. */
export interface GapDetail {
  code: string;
  message: string;
}

interface RegisterResult {
  synced?: boolean;
  reason?: string;
  vendor_name?: string | null;
  gap_details?: GapDetail[];
  statutory_gaps?: string[];
}

/** The notes in one `POST /receive` response. Empty when nothing was reported. */
export function registerNotesFrom(data: unknown): RegisterNote[] {
  const reg = (data as { tds_register?: RegisterResult } | null)?.tds_register;
  if (!reg) return [];
  return notesFrom(reg);
}

/** The notes at the TOP LEVEL of a response, rather than under `tds_register`.
 *
 *  Three paths report the same vocabulary this way — a vendor PAYMENT (whose
 *  advance is a charging event in its own right), and issuing a purchase
 *  DEBIT or CREDIT note (PUR-23 ≡ TDS-32, where the note has moved a credit
 *  the tax was already withheld on). None of the three has a second document
 *  to nest the gaps under, so `services/tds_register_service` puts them on the
 *  document itself.
 *
 *  Named for the SHAPE and not for the payment path, because it stopped being
 *  the payment path's alone: a helper named after one of its three callers is
 *  how the fourth ends up with a hand-rolled copy and a gap worded differently
 *  on one screen. One renderer, so one wording. */
export function topLevelNotesFrom(data: unknown): RegisterNote[] {
  if (!data || typeof data !== "object") return [];
  return notesFrom(data as RegisterResult);
}

function notesFrom(reg: RegisterResult): RegisterNote[] {
  const vendor = reg.vendor_name ?? null;

  // A FAILED SYNC IS THE LOUDEST CASE, not a silent one. The bill and its
  // journal are correct and committed; the register is out of step, which is
  // what 26Q is built from. _sync_tds_register deliberately never raises so a
  // register failure cannot roll back a correct posting — that is exactly why
  // it has to be said here instead.
  if (reg.synced === false) {
    return [{
      vendor,
      text: reg.reason
        ? `The TDS register is out of step with this bill: ${reg.reason}. The bill and its journal are posted; 26Q will be short until the register is repaired.`
        : "The TDS register could not be updated for this bill. The bill and its journal are posted; 26Q will be short until the register is repaired.",
    }];
  }

  // gap_details carries the sentences; statutory_gaps carries the codes. Prefer
  // the sentences and fall back to the codes rather than showing nothing — a
  // response that named a gap must never render as "no gaps".
  const details = reg.gap_details ?? [];
  if (details.length > 0) {
    // The MESSAGE, falling back to the code — a gap whose wording the backend
    // could not supply is still a gap, and an empty note reads as none.
    return details.map((d) => ({ vendor, text: d?.message || d?.code || "" }))
                  .filter((n) => n.text !== "");
  }
  return (reg.statutory_gaps ?? []).map((code) => ({ vendor, text: code }));
}

/** One sentence per (vendor, text). A batch of twenty bills to one
 *  unclassified supplier raises the same gap twenty times, and twenty copies
 *  of one sentence is how a real warning gets scrolled past. */
export function dedupeRegisterNotes(notes: RegisterNote[]): RegisterNote[] {
  const seen = new Set<string>();
  const out: RegisterNote[] = [];
  for (const n of notes) {
    const key = `${n.vendor ?? ""} ${n.text}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(n);
  }
  return out;
}
