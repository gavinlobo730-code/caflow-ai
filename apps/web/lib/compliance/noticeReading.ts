/**
 * Correcting a staged government-notice reading: the form's values and the patch it sends.
 *
 * `PATCH /api/document-intelligence-v2/notices/{id}/reading` takes only the fields that changed. This module reads a stored row
 * into form text and builds that patch; it decides nothing about what is valid (the notice-type vocabulary, ISO dates, length
 * limits and the pair rule for dates are `domain/ai/extraction_schemas.correct_notice` on the server, and the refusal comes back
 * as a sentence the modal shows).
 */

/** The notice types the reading may carry. A copy of `extraction_schemas.NOTICE_TYPES` in the same order; a Python test holds the
 *  two equal, so a type added on the server cannot be missing from the select. */
export const NOTICE_TYPE_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "gst_scrutiny", label: "GST scrutiny" },
  { value: "income_tax_demand", label: "Income tax demand" },
  { value: "income_tax_notice", label: "Income tax notice" },
  { value: "mca_show_cause", label: "MCA show-cause" },
  { value: "tds_default", label: "TDS default" },
  { value: "customs", label: "Customs" },
  { value: "other", label: "Other" },
];

export interface NoticeReadingForm {
  authority: string;
  notice_type: string;
  reference_no: string;
  issue_date: string;
  response_due_date: string;
  description: string;
}

const FIELDS = ["authority", "notice_type", "reference_no", "issue_date", "response_due_date", "description"] as const;

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

/** The stored row as form text. An absent value is the empty string (the notice states none), never "null". A stored date that
 *  is a timestamp is cut to its calendar day, because the field holds a date. */
export function readingFormFrom(row: Record<string, unknown>): NoticeReadingForm {
  return {
    authority: text(row.authority),
    notice_type: text(row.notice_type),
    reference_no: text(row.reference_no),
    issue_date: text(row.issue_date).slice(0, 10),
    response_due_date: text(row.response_due_date).slice(0, 10),
    description: text(row.description),
  };
}

/** Only what the person changed, trimmed; an empty string means "clear it" and is sent as such. An unchanged form is an empty
 *  patch, which the modal does not send. */
export function buildCorrection(row: Record<string, unknown>, form: NoticeReadingForm): Partial<NoticeReadingForm> {
  const before = readingFormFrom(row);
  const patch: Partial<NoticeReadingForm> = {};
  for (const key of FIELDS) {
    const now = form[key].trim();
    if (now !== before[key]) patch[key] = now;
  }
  return patch;
}
