import { getSupabaseClient } from "@/lib/supabase/client";
import type { TimeEntry, TimerState, TimeSummary, ApiResponse } from "@/lib/types";

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
  if (!resp.success) throw new Error(resp.error ?? "Failed to load time entries");
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
}): Promise<TimeEntry> {
  const resp = await apiFetch<{ entry: TimeEntry }>("/api/time-entries/start", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!resp.success) throw new Error(resp.error ?? "Failed to start timer");
  return resp.data.entry;
}

export async function stopTimer(entryId: string): Promise<TimeEntry> {
  const resp = await apiFetch<{ entry: TimeEntry }>(`/api/time-entries/${entryId}/stop`, {
    method: "POST",
  });
  if (!resp.success) throw new Error(resp.error ?? "Failed to stop timer");
  return resp.data.entry;
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
}): Promise<TimeEntry> {
  const resp = await apiFetch<{ entry: TimeEntry }>("/api/time-entries", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!resp.success) throw new Error(resp.error ?? "Failed to create entry");
  return resp.data.entry;
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
