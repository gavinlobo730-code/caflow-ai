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

export interface GetTimelineOptions {
  clientId: string;
  category?: EventCategory;
  financialYear?: string;
  limit?: number;
  offset?: number;
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
      .limit(options.limit ?? 50);

    if (options.category) query = query.eq("category", options.category);
    if (options.financialYear) query = query.eq("financial_year", options.financialYear);
    if (options.offset) query = query.range(options.offset, options.offset + (options.limit ?? 50) - 1);

    const { data, error } = await query;
    if (error) return { success: false, data: [], error: error.message };
    return { success: true, data: (data ?? []) as TimelineEvent[], error: null };
  } catch (err) {
    return { success: false, data: [], error: String(err) };
  }
}
