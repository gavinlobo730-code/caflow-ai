/**
 * Format a server timestamp for IST display, labelled as such.
 *
 * `journal_entries.posted_at`, `verify_books_runs.started_at` and every other
 * `timestamptz` this product stores comes back from PostgREST in UTC
 * (CLAUDE.md's "Reporting times to the user"). A raw
 * `String(x).slice(0, 16).replace("T", " ")` prints that UTC wall-clock
 * value with no timezone label at all — so from 18:30 to 24:00 UTC (00:00 to
 * 05:30 IST the next day) it silently shows the wrong calendar DATE, and
 * every other hour shows a time five and a half hours behind what actually
 * happened in India.
 *
 * `formatIst` converts through an `Intl.DateTimeFormat` with an explicit
 * `Asia/Kolkata` zone — never a manual UTC+5:30 offset add, which gets the
 * arithmetic right but says nothing about WHICH zone the printed value is
 * in — and the caller appends "IST" so the label travels with the value
 * rather than being assumed. The conversion itself lives in
 * `lib/dates/format.ts`, beside the one calendar-date format.
 */

import { formatDateTime } from "./format.ts";

/** `null`/`undefined`/unparseable in, `null` out — the caller decides what an
 * absent timestamp renders as (this module doesn't guess "—" is always right).
 *
 * DELEGATES to `lib/dates/format.formatDateTime`, which is the one date-time
 * format (frontend_ux-20). It used to build its own `Intl.DateTimeFormat` with
 * `dateStyle: "medium"`, which prints "5 Sept 2026, 3:30 pm" on a current engine
 * and "5 Sep 2026" on an older one, and a second spelling of the same moment
 * beside `formatDateTime`'s "5/9/2026, 10:00:00 am". The names stay because
 * `verify-books-and-approvals-show-ist-not-raw-utc.test.ts` pins them. */
export function formatIst(value: string | null | undefined): string | null {
  const formatted = formatDateTime(value, "");
  return formatted === "" ? null : formatted;
}

/** The common case: `formatIst` plus the "IST" label, or the given fallback
 * (default "—") when the timestamp is absent or unparseable. */
export function formatIstLabelled(value: string | null | undefined, fallback = "—"): string {
  const formatted = formatIst(value);
  return formatted ? `${formatted} IST` : fallback;
}
