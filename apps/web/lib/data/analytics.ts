import { getSupabaseClient } from "@/lib/supabase/client";
import type {
  TeamAnalyticsReport,
  ClientAnalyticsReport,
  FirmAnalyticsReport,
  TeamWorkload,
  ApiResponse,
} from "@/lib/types";

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

export type AnalyticsPeriod = "week" | "month" | "quarter";

export async function getTeamAnalytics(period: AnalyticsPeriod = "month"): Promise<TeamAnalyticsReport> {
  const resp = await apiFetch<TeamAnalyticsReport>(`/api/analytics/team?period=${period}`);
  if (!resp.success) throw new Error(resp.error ?? "Failed to load team analytics");
  return resp.data;
}

export async function getClientAnalytics(period: AnalyticsPeriod = "month"): Promise<ClientAnalyticsReport> {
  const resp = await apiFetch<ClientAnalyticsReport>(`/api/analytics/clients?period=${period}`);
  if (!resp.success) throw new Error(resp.error ?? "Failed to load client analytics");
  return resp.data;
}

export async function getFirmAnalytics(period: AnalyticsPeriod = "month"): Promise<FirmAnalyticsReport> {
  const resp = await apiFetch<FirmAnalyticsReport>(`/api/analytics/firm?period=${period}`);
  if (!resp.success) throw new Error(resp.error ?? "Failed to load firm analytics");
  return resp.data;
}

export async function getTeamWorkload(): Promise<TeamWorkload> {
  const resp = await apiFetch<TeamWorkload>("/api/workload");
  if (!resp.success) throw new Error(resp.error ?? "Failed to load workload");
  return resp.data;
}

export function formatRupees(paise: number): string {
  const rupees = paise / 100;
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(rupees);
}

export function formatHours(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `${m}m`;
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}
