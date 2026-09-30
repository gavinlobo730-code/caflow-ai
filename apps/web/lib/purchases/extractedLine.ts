/**
 * What an AI reading of an invoice did not state, and what the bill editor does
 * with that (AI-01 / GST-03).
 *
 * The SERVER decides what was not read (domain/extraction_lines.py, served as
 * `not_read` on each extracted line). This file holds the four names, how an
 * extracted line becomes an editor line with NOTHING invented, and how typing
 * into a field clears its flag — and nothing about which field is which.
 *
 * It is its own module rather than more of `billEditor.ts` because that file's
 * validation is pinned to know nothing of an AI reading's TOTALS
 * (tests/test_an_extracted_invoice_has_to_add_up.py): the totals check warns and
 * never refuses. This is a different thing — a field nobody stated, which DOES
 * stop a line being saved — and keeping it here keeps that pin honest.
 *
 * Pure (no React, no browser), so it runs under `node --test`. The one
 * dependency on `billEditor.ts` is a TYPE, erased at runtime, so the two never
 * form an import cycle.
 */
import type { PurchaseBillLine } from "./billEditor.ts";

export type UnreadField = "quantity" | "unit" | "gst_rate" | "rate";

const UNREAD_FIELDS: readonly UnreadField[] = ["quantity", "unit", "gst_rate", "rate"];

/** The three that move money. An unread UNIT does not: it is flagged, and the
 *  line still saves — the server's own `unit or "NOS"` fallback on the bill
 *  create path is what the caption under the table tells the CA about. */
export const BLOCKING_UNREAD: readonly UnreadField[] = ["quantity", "gst_rate", "rate"];

export const UNREAD_LABEL: Record<UnreadField, string> = {
  quantity: "quantity",
  unit: "unit",
  gst_rate: "GST rate",
  rate: "rate",
};

/** One extracted line as POST /api/document-intelligence-v1/extract-invoice
 *  returns it. Every figure may be null: null is "the document did not say",
 *  and 0 is an answer. */
export interface ExtractedLine {
  description?: string | null;
  hsn_sac?: string | null;
  quantity?: number | null;
  unit?: string | null;
  unit_as_printed?: string | null;
  rate_paise?: number | null;
  gst_rate_bps?: number | null;
  not_read?: string[] | null;
}

/** The editor's own line for an extracted one — with NOTHING invented.
 *
 *  The unread set is the server's `not_read` UNIONED with what the values
 *  themselves say, so a backend one deploy behind (which sends no flags) still
 *  cannot turn a null into 18%: the frontend deploys ahead of the backend
 *  here, and a missing flag must not read as "everything was read".
 *
 *  `gst_rate` is 0 while unread only because the field is a number; the flag,
 *  not the 0, is what the select and the validator read. */
export function lineFromExtraction(li: ExtractedLine): Omit<PurchaseBillLine, "expense_account_id" | "service_catalogue_id"> {
  const flagged = new Set((li.not_read ?? []).filter((f): f is UnreadField =>
    (UNREAD_FIELDS as readonly string[]).includes(f)));
  const qty = typeof li.quantity === "number" && Number.isFinite(li.quantity) && li.quantity > 0
    ? li.quantity : null;
  const unit = typeof li.unit === "string" ? li.unit.trim() : "";
  const bps = typeof li.gst_rate_bps === "number" && Number.isFinite(li.gst_rate_bps) && li.gst_rate_bps >= 0
    ? li.gst_rate_bps : null;
  const ratePaise = typeof li.rate_paise === "number" && Number.isFinite(li.rate_paise)
    ? li.rate_paise : null;
  if (qty === null) flagged.add("quantity");
  if (!unit) flagged.add("unit");
  if (bps === null) flagged.add("gst_rate");
  if (ratePaise === null) flagged.add("rate");
  const unread = UNREAD_FIELDS.filter((f) => flagged.has(f));
  return {
    description: li.description ?? "",
    hsn_sac: li.hsn_sac ?? "",
    qty: qty === null ? "" : String(qty),
    unit,
    rate: ratePaise === null ? "" : String(Math.floor(ratePaise) / 100),
    gst_rate: bps === null ? 0 : bps / 100,
    ...(unread.length ? { unread } : {}),
    ...(li.unit_as_printed ? { unitAsPrinted: li.unit_as_printed } : {}),
  };
}

const EDIT_CONFIRMS: Record<string, UnreadField> = {
  qty: "quantity", unit: "unit", gst_rate: "gst_rate", rate: "rate",
};

/** Typing into a field IS the CA stating it, so that field stops being unread.
 *  Returns undefined once nothing is left, so a fully-confirmed line is
 *  indistinguishable from one typed by hand. */
export function unreadAfterEdit(
  unread: UnreadField[] | undefined, patch: Partial<PurchaseBillLine>,
): UnreadField[] | undefined {
  if (!unread?.length) return unread;
  const touched = Object.keys(patch).map((k) => EDIT_CONFIRMS[k]).filter(Boolean);
  if (!touched.length) return unread;
  const left = unread.filter((f) => !touched.includes(f));
  return left.length ? left : undefined;
}

/** The unread fields that stop the line saving. */
export function blockingUnread(l: PurchaseBillLine): UnreadField[] {
  return (l.unread ?? []).filter((f) => BLOCKING_UNREAD.includes(f));
}

