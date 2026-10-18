/**
 * The statement layouts the product has been taught, in the words a screen shows.
 *
 * `GET /api/banking/statements/column-mappings` answers a window (apps/api/core/list_window.py) of saved mappings: one per
 * (bank account, header layout), each holding the column POSITIONS the CA mapped and the header LABELS they saw when they did it.
 * A position alone ("0 -> 3") is unreadable and goes stale the day the bank renames a column, so the labels are kept for display;
 * this module turns the two into "Date <- Txn Date". It decides nothing about a mapping: whether one is valid and which one
 * applies to a file are `domain/banking/normalizer` and `services/bank_column_mapping_service`, on the server.
 */
import { readWindow, type ReadWindow } from "../lists/readWindow.ts";

export interface SavedColumnMapping {
  id: string;
  client_id: string;
  bank_account_id: string;
  header_labels: unknown;
  mapping: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
}

/**
 * The fields a mapping may carry, in the order a person reads them. It is a copy of `normalizer.MAPPING_KEYS` and
 * `apps/api/tests/test_what_a_bank_taught_us_is_a_window_a_ca_can_read_and_forget.py` holds the two equal, so a field added on
 * the server and not here fails a test instead of vanishing from the screen.
 */
export const MAPPING_FIELDS: ReadonlyArray<{ key: string; label: string }> = [
  { key: "date", label: "Date" },
  { key: "desc", label: "Description" },
  { key: "ref", label: "Reference" },
  { key: "debit", label: "Debit" },
  { key: "credit", label: "Credit" },
  { key: "amount", label: "Amount" },
  { key: "drcr", label: "Dr/Cr" },
  { key: "balance", label: "Balance" },
];

export interface DescribedField {
  label: string;
  /** What the column was called when the CA mapped it, or its position when the saved header cannot name it. */
  column: string;
}

/** The mapped fields of a saved layout. A field that is not mapped is left out; a position the saved header cannot name is shown
 *  as its position (1-based, as a person counts columns), never as an invented label. */
export function describeMapping(mapping: Record<string, unknown>, headerLabels: unknown): DescribedField[] {
  const labels = Array.isArray(headerLabels) ? headerLabels : [];
  const out: DescribedField[] = [];
  for (const { key, label } of MAPPING_FIELDS) {
    const raw = mapping?.[key];
    if (typeof raw !== "number" || !Number.isInteger(raw) || raw < 0) continue;
    const name = labels[raw];
    out.push({
      label,
      column: typeof name === "string" && name.trim() !== "" ? `"${name.trim()}"` : `column ${raw + 1}`,
    });
  }
  return out;
}

/** The window from the envelope's `data`, or null when it is neither a window nor a bare list (a refusal, null, a scalar): the
 *  screen then says the layouts could not be read, which is a different statement from "none have been saved". A row that
 *  cannot be drawn (no id) is dropped; a bare list from a server that predates the window is read as complete. */
export function readSavedMappings(data: unknown, askedLimit: number): ReadWindow<SavedColumnMapping> | null {
  const window = readWindow<unknown>(data, "mappings", askedLimit);
  if (!window) return null;
  const rows = window.rows.filter(
    (r): r is SavedColumnMapping => typeof r === "object" && r !== null && typeof (r as { id?: unknown }).id === "string",
  );
  return { ...window, rows };
}
