import { getSupabaseClient } from "@/lib/supabase/client";
import type { TimeEntry, TimerState, TimeSummary, ApiResponse } from "@/lib/types";
import { arrayOrEmpty, objectOrNull } from "@/lib/api/shape";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<ApiResponse<T>> {
  const { data: { session } } = await getSupabaseClient().auth.getSession();
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  return res.json();
}

/**
 * The sentence the server gave for a refusal. FastAPI answers a 422/409 as
 * `{detail: "..."}` and not as `{success: false, error}`, so reading only
 * `error` showed "Failed to start timer" for "That engagement is not one of this
 * client's" — which tells a person nothing about what to change.
 */
function refusal(resp: unknown, fallback: string): Error {
  const r = objectOrNull<{ error?: unknown; detail?: unknown }>(resp);
  if (r && typeof r.error === "string" && r.error) return new Error(r.error);
  if (r && typeof r.detail === "string" && r.detail) return new Error(r.detail);
  return new Error(fallback);
}

/** What the server said about the rate a recorded hour bills at. */
export interface RateAnswer {
  /** "entry" | "engagement" | "user", or null when no rate could be found. */
  source: string | null;
  /** Sentences for the person: why no engagement was chosen, that the time will
   *  be listed as "no rate" until one is recorded. */
  notes: string[];
}

export interface RecordedTime {
  entry: TimeEntry;
  rate: RateAnswer | null;
}

function readRate(data: unknown): RateAnswer | null {
  const d = objectOrNull<{ rate?: unknown }>(data);
  const r = objectOrNull<{ source?: unknown; notes?: unknown }>(d?.rate);
  if (!r) return null;
  return {
    source: typeof r.source === "string" ? r.source : null,
    notes: arrayOrEmpty<unknown>(r.notes).filter((n): n is string => typeof n === "string"),
  };
}

export interface EngagementChoices {
  /** The client's LIVE engagements, which an hour may be recorded against. */
  engagements: { id: string; service_type: string | null; status: string | null }[];
  /** The one it defaults to — the client's single active engagement — or null. */
  default_engagement_id: string | null;
  /** Why there is no default, when there is not. */
  reason: string | null;
}

/**
 * The engagements a time entry for this client may be recorded against, and the
 * one the server will default to. The billing-rate OVERRIDE is deliberately not
 * served here: it is fee economics, `billing:write`.
 */
export async function getEngagementChoices(clientId: string): Promise<EngagementChoices> {
  const resp = await apiFetch<unknown>(
    `/api/time-entries/engagement-choices?client_id=${encodeURIComponent(clientId)}`);
  if (!resp.success) throw refusal(resp, "Failed to load engagements");
  const d = objectOrNull<Record<string, unknown>>(resp.data) ?? {};
  return {
    engagements: arrayOrEmpty<EngagementChoices["engagements"][number]>(d.engagements),
    default_engagement_id: typeof d.default_engagement_id === "string" ? d.default_engagement_id : null,
    reason: typeof d.reason === "string" ? d.reason : null,
  };
}

/**
 * Give one time entry a rate — how a "no rate" hour on the unbilled-work list
 * gets one. Whole paise, as `paiseFromRupeeInput` returns them; the server
 * refuses a negative and refuses time already on an invoice.
 */
export async function setEntryRate(entryId: string, billableRatePaise: number): Promise<void> {
  const resp = await apiFetch<unknown>(`/api/time-entries/${entryId}`, {
    method: "PATCH",
    body: JSON.stringify({ billable_rate_paise: billableRatePaise }),
  });
  if (!resp.success) throw refusal(resp, "Failed to set the rate");
}

export async function listTimeEntries(params?: {
  client_id?: string;
  task_id?: string;
  user_id?: string;
  start_date?: string;
  end_date?: string;
  is_billable?: boolean;
  limit?: number;
}): Promise<{ entries: TimeEntry[]; total: number }> {
  const qs = new URLSearchParams();
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) qs.set(k, String(v));
    });
  }
  const resp = await apiFetch<{ entries: TimeEntry[]; total: number }>(
    `/api/time-entries${qs.toString() ? `?${qs}` : ""}`
  );
  if (!resp.success) throw refusal(resp, "Failed to load time entries");
  return resp.data;
}

export async function getRunningTimer(): Promise<TimerState> {
  const resp = await apiFetch<{ running: TimeEntry | null }>("/api/time-entries/running/me");
  if (!resp.success) throw new Error(resp.error ?? "Failed to check timer");
  const entry = resp.data.running;
  if (!entry) return { is_running: false, elapsed_seconds: 0 };
  const elapsed = Math.floor((Date.now() - new Date(entry.started_at).getTime()) / 1000);
  return { is_running: true, entry, elapsed_seconds: elapsed };
}

export async function startTimer(payload: {
  task_id?: string;
  client_id?: string;
  engagement_id?: string;
  description?: string;
  is_billable?: boolean;
}): Promise<RecordedTime> {
  const resp = await apiFetch<{ entry: TimeEntry }>("/api/time-entries/start", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!resp.success) throw refusal(resp, "Failed to start timer");
  return { entry: resp.data.entry, rate: readRate(resp.data) };
}

export async function stopTimer(entryId: string): Promise<RecordedTime> {
  const resp = await apiFetch<{ entry: TimeEntry }>(`/api/time-entries/${entryId}/stop`, {
    method: "POST",
  });
  if (!resp.success) throw refusal(resp, "Failed to stop timer");
  return { entry: resp.data.entry, rate: readRate(resp.data) };
}

export async function createManualEntry(payload: {
  task_id?: string;
  client_id?: string;
  engagement_id?: string;
  description?: string;
  started_at: string;
  ended_at: string;
  is_billable?: boolean;
  hourly_rate_paise?: number;
}): Promise<RecordedTime> {
  const resp = await apiFetch<{ entry: TimeEntry }>("/api/time-entries", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!resp.success) throw refusal(resp, "Failed to create entry");
  return { entry: resp.data.entry, rate: readRate(resp.data) };
}

export async function deleteTimeEntry(id: string): Promise<void> {
  const resp = await apiFetch<null>(`/api/time-entries/${id}`, { method: "DELETE" });
  if (!resp.success) throw new Error(resp.error ?? "Failed to delete entry");
}

export async function getMyTimeSummary(params?: {
  start_date?: string;
  end_date?: string;
}): Promise<TimeSummary> {
  const qs = new URLSearchParams();
  if (params?.start_date) qs.set("start_date", params.start_date);
  if (params?.end_date) qs.set("end_date", params.end_date);
  const resp = await apiFetch<TimeSummary>(
    `/api/time-entries/summary/me${qs.toString() ? `?${qs}` : ""}`
  );
  if (!resp.success) throw new Error(resp.error ?? "Failed to load summary");
  return resp.data;
}

export function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

export function formatElapsed(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return [
    h > 0 ? String(h).padStart(2, "0") : null,
    String(m).padStart(2, "0"),
    String(s).padStart(2, "0"),
  ]
    .filter(Boolean)
    .join(":");
}
