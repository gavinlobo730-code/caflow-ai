import { getSupabaseClient } from "@/lib/supabase/client";
import { api } from "@/lib/api";

export type EventCategory =
  | "accounting" | "compliance" | "payroll" | "tax"
  | "document" | "work" | "ai" | "portal" | "team";

export type EventSeverity = "info" | "success" | "warning" | "critical";
export type EventActorType = "user" | "system" | "ai" | "client";
export type EventVisibility = "all" | "internal" | "partner_only";

/** What a browser may SAY about an event it wants recorded. There is deliberately no firm, no actor and no pin here
 *  (POST-A-228): the server sets the firm from the signed-in person, the actor to that person, and a new event is unpinned.
 *  The row it stores is `TimelineEvent`. */
export interface TimelineEventInput {
  client_id: string;
  financial_year: string;
  category: EventCategory;
  event_type: string;
  severity?: EventSeverity;
  title: string;
  description?: string;
  action_label?: string;
  /** A path inside the product, starting with a single "/". */
  action_url?: string;
  entity_type?: string;
  entity_id?: string;
  amount_paise?: number;
  visibility?: EventVisibility;
}

/** An event as it is held: what was said, plus the facts the server decided. */
export interface TimelineEvent extends TimelineEventInput {
  id: string;
  firm_id: string;
  period?: string;
  actor_type?: EventActorType;
  actor_id?: string;
  actor_name?: string;
  is_pinned?: boolean;
  created_at: string;
  deleted_at: string | null;
}

/** Record an event on a client's activity feed, AS THE SIGNED-IN PERSON, through the server. The browser used to INSERT
 *  into the table itself and choose the actor; it can no longer (migration 515). A failure comes back as `success: false`
 *  with the server's own sentence, and every caller treats the timeline as non-blocking. */
export async function writeTimelineEvent(
  input: TimelineEventInput
): Promise<{ success: boolean; data: TimelineEvent | null; error: string | null }> {
  try {
    const res = await api.timeline.write(input) as { success?: boolean; data?: TimelineEvent; error?: string | null };
    if (res?.success === false) return { success: false, data: null, error: res.error ?? "The event was not recorded." };
    return { success: true, data: (res?.data ?? null) as TimelineEvent | null, error: null };
  } catch (err) {
    return { success: false, data: null, error: err instanceof Error ? err.message : String(err) };
  }
}

/** Where the previous page ended: its LAST event, in feed order. */
export interface TimelineCursor {
  created_at: string;
  id: string;
}

export interface GetTimelineOptions {
  clientId: string;
  category?: EventCategory;
  financialYear?: string;
  limit?: number;
  /** Return only events strictly after this one in feed order — the next page.
   *
   *  A CURSOR, NOT AN OFFSET. The feed is newest first, so an event written
   *  while somebody is reading shifts every offset by one and the next page
   *  repeats a row; and `created_at` alone is not a total order (a posting
   *  writes several events in one statement), so rows sharing it could land
   *  either side of a page boundary. The order is (created_at, id) descending,
   *  which is total, and the cursor names a position in it. */
  before?: TimelineCursor;
}

export async function getClientTimeline(
  options: GetTimelineOptions
): Promise<{ success: boolean; data: TimelineEvent[]; error: string | null }> {
  try {
    const supabase = getSupabaseClient();
    let query = supabase
      .from("client_timeline_events")
      .select("*")
      .eq("client_id", options.clientId)
      .is("deleted_at", null)
      .order("created_at", { ascending: false })
      .order("id", { ascending: false })
      .limit(options.limit ?? 50);

    if (options.category) query = query.eq("category", options.category);
    if (options.financialYear) query = query.eq("financial_year", options.financialYear);
    if (options.before) {
      // (created_at, id) < (cursor.created_at, cursor.id), spelled for
      // PostgREST. The timestamp is double-quoted because it carries `.` and
      // `:`, both reserved inside a logical filter.
      const { created_at: at, id } = options.before;
      query = query.or(`created_at.lt."${at}",and(created_at.eq."${at}",id.lt.${id})`);
    }

    const { data, error } = await query;
    if (error) return { success: false, data: [], error: error.message };
    return { success: true, data: (data ?? []) as TimelineEvent[], error: null };
  } catch (err) {
    return { success: false, data: [], error: String(err) };
  }
}
