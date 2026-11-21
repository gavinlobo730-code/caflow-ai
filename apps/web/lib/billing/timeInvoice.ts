/**
 * Hourly billing, as the screen reads it (POST-B-194): one client's unbilled time entry by entry, the lines a draft would
 * carry, and what the server made.
 *
 * NOTHING IS WORKED OUT HERE. What an hour is worth, which entries may be billed and what the lines add up to are the
 * server's (`apps/api/services/time_billing_service.py`); this module reads its answers without trusting their shape, so a
 * screen never draws "0 entries" or "₹0" out of an answer that was not the answer. Each reader returns null for a payload
 * that is not the thing, which the screen says as "could not be read", a different statement from an empty one.
 *
 * Pure: no React and no request.
 */
import { arrayOrEmpty, objectOrNull } from "../api/shape.ts";

export type Grouping = "single" | "by_task" | "by_person" | "by_entry";

/** The words for each way of laying the time out on the invoice. */
export const GROUPING_LABELS: Readonly<Record<Grouping, string>> = {
  by_task: "One line for each task",
  by_person: "One line for each member of staff",
  by_entry: "One line for each time entry",
  single: "One line for all of it",
};
export const GROUPINGS: readonly Grouping[] = ["by_task", "by_person", "by_entry", "single"];

export interface UnbilledEntry {
  id: string;
  day: string | null;
  userName: string | null;
  taskTitle: string | null;
  description: string | null;
  minutes: number;
  ratePaise: number | null;
  /** What the entry is worth, or null when it has no rate or cannot be valued yet. Never 0 for "unknown". */
  valuePaise: number | null;
  /** Why it cannot be billed yet, in the server's words, or null when it can. */
  blocked: string | null;
}

export interface UnbilledEntries {
  entries: UnbilledEntry[];
  billableCount: number;
  billableMinutes: number;
  billableValuePaise: number;
}

const text = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);
const whole = (v: unknown): number | null => (typeof v === "number" && Number.isInteger(v) ? v : null);

export function readUnbilledEntries(data: unknown): UnbilledEntries | null {
  const obj = objectOrNull<Record<string, unknown>>(data);
  if (!obj || !Array.isArray(obj.entries)) return null;
  const count = whole(obj.billable_count), minutes = whole(obj.billable_minutes), value = whole(obj.billable_value_paise);
  if (count === null || minutes === null || value === null) return null;
  const entries: UnbilledEntry[] = [];
  for (const raw of arrayOrEmpty<unknown>(obj.entries)) {
    const row = objectOrNull<Record<string, unknown>>(raw);
    const id = text(row?.id), mins = whole(row?.minutes);
    if (!row || !id || mins === null) return null;   // one unreadable row makes the list unreadable: a short list would bill less
    entries.push({
      id, day: text(row.day), userName: text(row.user_name), taskTitle: text(row.task_title), description: text(row.description),
      minutes: mins, ratePaise: whole(row.rate_paise), valuePaise: whole(row.value_paise), blocked: text(row.blocked),
    });
  }
  return { entries, billableCount: count, billableMinutes: minutes, billableValuePaise: value };
}

export interface PreviewLine { description: string; minutes: number; valuePaise: number }
export interface TimeInvoicePreview { lines: PreviewLine[]; entries: number; minutes: number; valuePaise: number }

export function readPreview(data: unknown): TimeInvoicePreview | null {
  const obj = objectOrNull<Record<string, unknown>>(data);
  if (!obj || !Array.isArray(obj.lines)) return null;
  const entries = whole(obj.entries), minutes = whole(obj.minutes), value = whole(obj.value_paise);
  if (entries === null || minutes === null || value === null) return null;
  const lines: PreviewLine[] = [];
  for (const raw of arrayOrEmpty<unknown>(obj.lines)) {
    const row = objectOrNull<Record<string, unknown>>(raw);
    const description = text(row?.description), mins = whole(row?.minutes), worth = whole(row?.value_paise);
    if (!row || !description || mins === null || worth === null) return null;
    lines.push({ description, minutes: mins, valuePaise: worth });
  }
  return { lines, entries, minutes, valuePaise: value };
}

export interface TimeInvoiceMade { invoiceId: string; practiceClientId: string | null; entriesBilled: number; valuePaise: number }

export function readMade(data: unknown): TimeInvoiceMade | null {
  const obj = objectOrNull<Record<string, unknown>>(data);
  const invoiceId = text(obj?.invoice_id), billed = whole(obj?.entries_billed), value = whole(obj?.value_paise);
  if (!obj || !invoiceId || billed === null || value === null) return null;
  return { invoiceId, practiceClientId: text(obj.practice_client_id), entriesBilled: billed, valuePaise: value };
}

export interface PracticeService { id: string; name: string; gstRateBps: number | null }

/** The practice's own services (`GET /api/billing/service-options`), or null when the answer is not that list. */
export function readServices(data: unknown): PracticeService[] | null {
  const obj = objectOrNull<Record<string, unknown>>(data);
  if (!obj || !Array.isArray(obj.services)) return null;
  const out: PracticeService[] = [];
  for (const raw of arrayOrEmpty<unknown>(obj.services)) {
    const row = objectOrNull<Record<string, unknown>>(raw);
    const id = text(row?.id), name = text(row?.name);
    if (!row || !id || !name) continue;
    const bps = typeof row.gst_rate_bps === "number" ? row.gst_rate_bps : typeof row.gst_rate_bps === "string" && row.gst_rate_bps.trim() ? Number(row.gst_rate_bps) : null;
    out.push({ id, name, gstRateBps: bps !== null && Number.isFinite(bps) ? bps : null });
  }
  return out;
}

/**
 * The rate of GST typed in the box, as a percentage, or null when it is not one. The server refuses anything outside 0 to
 * 100; this refuses what is not a plain number at all ("18%", "1e1", an empty box), so nothing but a figure is sent.
 */
export function gstPercentTyped(raw: string): number | null {
  const typed = raw.trim();
  if (!/^\d{1,3}(\.\d{1,2})?$/.test(typed)) return null;
  const n = Number(typed);
  return n >= 0 && n <= 100 ? n : null;
}

/** The ids ticked to start with: every entry that can be billed. */
export function billableIds(entries: readonly UnbilledEntry[]): string[] {
  return entries.filter((e) => e.blocked === null).map((e) => e.id);
}
