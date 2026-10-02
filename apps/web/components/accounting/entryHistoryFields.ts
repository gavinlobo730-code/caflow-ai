/**
 * CA-facing descriptions of what changed on a journal_entries / journal_lines
 * audit row — the pure half of EntryHistory.tsx's History panel.
 *
 * WHY A SEPARATE FILE
 *   `pnpm test` here is `node --experimental-strip-types --test`, which
 *   strips TypeScript types but does not parse JSX — so a `.tsx` file's own
 *   logic cannot be unit-tested directly. `components/ui/async-state.ts`
 *   (consumed by `states.tsx`) already splits pure logic out for exactly
 *   this reason; this module does the same for EntryHistory.
 *
 * WHY IT EXISTS AT ALL
 *   `audit_log.old_data` / `new_data` are `to_jsonb(OLD)` / `to_jsonb(NEW)` of
 *   the real table row (migration 266), so every key in them is a raw
 *   Postgres column name — `rate_selected_by`, `base_currency`, `txn_debit`.
 *   The History panel is Partner-only and exists to answer the Companies
 *   (Accounts) Rules 2014 Rule 3(1) edit-log question; a Partner reading it
 *   should not need the schema to do so.
 */

// Relative, not "@/…" — this module is imported directly by
// entryHistoryFields.test.ts under plain `node --experimental-strip-types`,
// which does not resolve the Next.js path alias.
import { formatPaise } from "../../lib/money/format.ts";
import { formatDate, formatDateTime } from "../../lib/dates/format.ts";

export type AuditRowLike = {
  action: string;
  old_data?: Record<string, unknown> | null;
  new_data?: Record<string, unknown> | null;
};

export type FieldChange = { key: string; label: string; before: string; after: string };

/** CA-facing label for a column worth naming specifically. A column not
 *  listed here is not hidden — `describeChanges` humanizes its own name —
 *  only `FIELD_DROP` below is ever silently omitted. */
const FIELD_LABELS: Record<string, string> = {
  entry_date: "Date",
  reference_no: "Reference No.",
  narration: "Narration",
  entry_type: "Entry Type",
  status: "Status",
  is_posted: "Posted",
  posted_at: "Posted At",
  is_reversed: "Reversed",
  debit_paise: "Debit",
  credit_paise: "Credit",
  attachments: "Attachments",
};

/** Bookkeeping columns that name no fact a CA reading the edit log needs:
 *  row/tenant identifiers (id, client_id, account_id, ...) and the
 *  multi-currency / rate-provenance columns nobody but the posting kernel
 *  reads (base_currency, rate_selected_by, ...). `updated_at` belongs here
 *  too — every update moves it, so on its own it says nothing the row's own
 *  timestamp does not already say. */
// NOTE: this set deliberately says nothing about the journal_lines column
// that records a voucher line's DISPLAY POSITION — that column's own
// backend module documents, and a backend guard enforces, that apps/web
// must never mention its name at all: reasoning about it here would become
// a second implementation of the display-order rule that guard exists to
// prevent (that column has a fallback chain a plain ORDER BY cannot
// express). If a raw audit row ever carries it, it falls through to the
// generic humanized label below, exactly like any other column this map
// does not otherwise name.
const FIELD_DROP = new Set([
  "id", "firm_id", "client_id", "journal_entry_id", "account_id",
  "cost_centre_id", "reversal_of", "recurring_template_id",
  "recurring_occurrence", "created_by", "posted_by", "created_at",
  "updated_at", "deleted_at", "source_type", "source_id",
  "base_currency", "txn_currency", "exchange_rate", "txn_debit",
  "txn_credit", "rate_source", "rate_type", "rate_date",
  "rate_selected_by", "rate_overridden", "rate_selected_at",
  "line_count",
]);

function humanizeKey(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function describeValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (key === "debit_paise" || key === "credit_paise") {
    return formatPaise(value as number | string | null | undefined);
  }
  // `entry_date` is a DATE column — a calendar date with no time or zone to
  // convert — and `posted_at` a stored UTC instant shown in IST. Both go through
  // lib/dates/format, which is the one place either rule is written; an
  // unreadable value is shown as it was stored, because this is an edit log and
  // a placeholder would hide what the row actually held.
  if (key === "entry_date") return formatDate(String(value), String(value));
  if (key === "posted_at") return formatDateTime(String(value), String(value));
  if (key === "attachments" && Array.isArray(value)) {
    return value.length === 1 ? "1 file" : `${value.length} files`;
  }
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/**
 * What changed on one audit row, described for a CA rather than for a
 * developer — the field's own label, and its before/after value.
 *
 * A create's `old_data` is `{}` and a delete's `new_data` is `{}`, so every
 * column of the row would otherwise show up as "changed" — the row was
 * never edited, it was made or removed whole. The action badge already
 * reads "Created" / "Deleted", so there is nothing for this to add.
 */
export function describeChanges(entry: AuditRowLike): FieldChange[] {
  if (entry.action === "create" || entry.action === "delete") return [];
  const before = (entry.old_data ?? {}) as Record<string, unknown>;
  const after = (entry.new_data ?? {}) as Record<string, unknown>;
  const keys = Array.from(new Set([...Object.keys(before), ...Object.keys(after)]))
    .filter((k) => !FIELD_DROP.has(k))
    .filter((k) => JSON.stringify(before[k]) !== JSON.stringify(after[k]))
    .sort();
  return keys.map((k) => ({
    key: k,
    label: FIELD_LABELS[k] ?? humanizeKey(k),
    before: describeValue(k, before[k]),
    after: describeValue(k, after[k]),
  }));
}
