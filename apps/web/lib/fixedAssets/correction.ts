/**
 * What a correction to a fixed asset actually CHANGED (FA-10).
 *
 * The register was final the moment it was saved, and the correction path that
 * fixes that has three tiers on the server — a rename touches nothing, a
 * revised rate applies prospectively, and a corrected COST reverses the
 * acquisition journal and re-posts it. Which tier a request falls into is
 * decided by the fields it carries.
 *
 * So the browser's job is exactly one thing: send what the CA touched and
 * nothing else. Posting the whole form back would put `purchase_cost_paise` in
 * every request, and every rename would reverse and re-post an acquisition
 * journal for no reason — a real entry on a real ledger, produced by typing in
 * a name field.
 *
 * It lives here rather than inside the drawer because that is the one piece of
 * the screen that can do damage, and a component is not testable.
 */
import { paiseFromRupeeInput } from "../money/rupeeInput.ts";

export interface CorrectableAsset {
  asset_name: string;
  // `null` and `undefined` both mean "not recorded" — the register's own row
  // type uses one and PostgREST returns the other.
  location?: string | null;
  notes?: string | null;
  purchase_cost_paise: number;
  salvage_value_paise: number;
  wdv_rate_percent?: number | null;
  useful_life_years?: number | null;
}

export interface CorrectionForm {
  asset_name: string;
  location: string;
  notes: string;
  purchase_cost_rs: string;
  salvage_value_rs: string;
  wdv_rate_percent: string;
  useful_life_years: string;
  reason: string;
}

/** The form as it should be initialised from an asset — the same shape
 *  `changedFields` compares against, so "unchanged" means literally unchanged. */
export function formFor(asset: CorrectableAsset): CorrectionForm {
  return {
    asset_name:        asset.asset_name,
    location:          asset.location ?? "",
    notes:             asset.notes ?? "",
    purchase_cost_rs:  (asset.purchase_cost_paise / 100).toString(),
    salvage_value_rs:  (asset.salvage_value_paise / 100).toString(),
    wdv_rate_percent:  asset.wdv_rate_percent != null ? String(asset.wdv_rate_percent) : "",
    useful_life_years: asset.useful_life_years != null ? String(asset.useful_life_years) : "",
    reason:            "",
  };
}

export type CorrectionResult =
  | { ok: true; body: Record<string, unknown> }
  | { ok: false; error: string };

/** The PATCH body for a correction, or the reason it cannot be built.
 *
 *  Amounts go through the one money parser: `parseFloat("1,25,000")` is 1, and
 *  a cost field is exactly where an Indian amount is typed with Indian
 *  grouping. A field the parser refuses is a refusal here, never a NaN sent as
 *  null. */
export function changedFields(asset: CorrectableAsset, form: CorrectionForm): CorrectionResult {
  const base = formFor(asset);
  const body: Record<string, unknown> = {};

  if (form.asset_name !== base.asset_name) body.asset_name = form.asset_name;
  if (form.location !== base.location) body.location = form.location || null;
  if (form.notes !== base.notes) body.notes = form.notes || null;

  if (form.purchase_cost_rs !== base.purchase_cost_rs) {
    const paise = paiseFromRupeeInput(form.purchase_cost_rs);
    if (paise === null) return { ok: false, error: "Enter the corrected cost as an amount." };
    body.purchase_cost_paise = paise;
  }
  if (form.salvage_value_rs !== base.salvage_value_rs) {
    const paise = paiseFromRupeeInput(form.salvage_value_rs);
    if (paise === null) return { ok: false, error: "Enter the salvage value as an amount." };
    body.salvage_value_paise = paise;
  }
  if (form.wdv_rate_percent !== base.wdv_rate_percent) {
    body.wdv_rate_percent = form.wdv_rate_percent === "" ? null : Number(form.wdv_rate_percent);
  }
  if (form.useful_life_years !== base.useful_life_years) {
    body.useful_life_years = form.useful_life_years === "" ? null : Number(form.useful_life_years);
  }

  if (Object.keys(body).length === 0) return { ok: false, error: "Nothing has been changed." };
  if (form.reason.trim()) body.reason = form.reason.trim();
  return { ok: true, body };
}

/** The fields whose presence makes a correction a TIER B one on the server —
 *  the acquisition journal is reversed and re-posted. Exported so a test can
 *  assert a rename never carries one, rather than restating the list. */
export const REPOSTS_THE_ACQUISITION = [
  "purchase_cost_paise", "asset_category", "purchase_date",
  "acquisition_mode", "vendor_id", "purchase_bill_id", "bank_account_id",
  "payment_mode", "igst_paise", "cgst_paise", "sgst_paise",
  "itc_eligible", "itc_blocked_reason",
] as const;
