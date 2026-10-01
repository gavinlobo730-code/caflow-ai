/**
 * The unbilled-work answer, as the screen holds it (practice_management-11).
 *
 * `GET /api/billing/unbilled-work` returns the SERVER's total — billable time
 * not yet on an invoice, valued at minutes x rate / 60 in whole paise — and,
 * apart from it, the time that has NO rate. Nothing here computes a figure.
 *
 * WHY A READER AND NOT A CAST. The answer is an object whose useful parts are
 * records and a list, and `{}` is a truthy payload that passes `if (!data)` and
 * then throws on `.entries.map`. `readUnbilledWork` takes `unknown` and always
 * returns a fully-shaped answer, so a refusal, a cold start or a half-deployed
 * backend renders as "nothing unbilled", which is a state the screen already
 * has, rather than a blank page (see `lib/api/shape.ts`).
 *
 * "NO RATE" IS NOT ZERO and is kept apart all the way down: `no_rate.count` and
 * `no_rate.minutes` never reach `total_value_paise`, and a screen that adds them
 * to it is wrong in the one direction a Partner acts on.
 */
import { arrayOrEmpty, objectOrNull } from "../api/shape.ts";

export interface UnbilledGroup {
  minutes: number;
  value_paise: number;
  count: number;
}

export interface NoRateEntry {
  id: string;
  user_id?: string | null;
  user_name?: string | null;
  client_id?: string | null;
  task_id?: string | null;
  description?: string | null;
  started_at?: string | null;
  duration_minutes?: number | null;
  engagement_id?: string | null;
}

export interface UnbilledWork {
  by_client: Record<string, UnbilledGroup>;
  by_work_item: Record<string, UnbilledGroup>;
  total_value_paise: number;
  priced_minutes: number;
  total_minutes: number;
  no_rate: {
    count: number;
    minutes: number;
    by_client: Record<string, { minutes: number; count: number }>;
    entries: NoRateEntry[];
  };
}

function whole(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

function record<T>(v: unknown): Record<string, T> {
  return objectOrNull<Record<string, T>>(v) ?? {};
}

/** A fully-shaped answer from whatever arrived. */
export function readUnbilledWork(data: unknown): UnbilledWork {
  const d = objectOrNull<Record<string, unknown>>(data) ?? {};
  const nr = objectOrNull<Record<string, unknown>>(d.no_rate) ?? {};
  return {
    by_client: record<UnbilledGroup>(d.by_client),
    by_work_item: record<UnbilledGroup>(d.by_work_item),
    total_value_paise: whole(d.total_value_paise),
    priced_minutes: whole(d.priced_minutes),
    total_minutes: whole(d.total_minutes),
    no_rate: {
      count: whole(nr.count),
      minutes: whole(nr.minutes),
      by_client: record<{ minutes: number; count: number }>(nr.by_client),
      entries: arrayOrEmpty<NoRateEntry>(nr.entries),
    },
  };
}

/** True when there is nothing unbilled at all — priced or not. */
export function nothingUnbilled(w: UnbilledWork): boolean {
  return w.total_minutes === 0 && w.no_rate.count === 0;
}
