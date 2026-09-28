import { getSupabaseClient } from "@/lib/supabase/client";

export type EventCategory =
  | "accounting" | "compliance" | "payroll" | "tax"
  | "document" | "work" | "ai" | "portal" | "team";

export type EventSeverity = "info" | "success" | "warning" | "critical";
export type EventActorType = "user" | "system" | "ai" | "client";
export type EventVisibility = "all" | "internal" | "partner_only";

export interface TimelineEventInput {
  client_id: string;
  firm_id: string;
  financial_year: string;
  period?: string;
  category: EventCategory;
  event_type: string;
  severity?: EventSeverity;
  title: string;
  description?: string;
  action_label?: string;
  action_url?: string;
  entity_type?: string;
  entity_id?: string;
  actor_type?: EventActorType;
  actor_id?: string;
  actor_name?: string;
  amount_paise?: number;
  is_pinned?: boolean;
  visibility?: EventVisibility;
}

export interface TimelineEvent extends TimelineEventInput {
  id: string;
  created_at: string;
  deleted_at: string | null;
}

export async function writeTimelineEvent(
  input: TimelineEventInput
): Promise<{ success: boolean; data: TimelineEvent | null; error: string | null }> {
  try {
    const supabase = getSupabaseClient();
    const { data, error } = await supabase
      .from("client_timeline_events")
      .insert({
        ...input,
        severity: input.severity ?? "info",
        actor_type: input.actor_type ?? "system",
        is_pinned: input.is_pinned ?? false,
        visibility: input.visibility ?? "all",
      })
      .select()
      .single();

    if (error) return { success: false, data: null, error: error.message };
    return { success: true, data: data as TimelineEvent, error: null };
  } catch (err) {
    return { success: false, data: null, error: String(err) };
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
