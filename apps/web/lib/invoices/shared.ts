/**
 * Shared Sales-Invoice primitives for client components. Re-exports the pure domain
 * layer (types, computeGst, state master, badges — see ./gst) and adds the
 * browser-only pieces: the money formatter and the Supabase-authed REST client.
 *
 * Split from ./gst in Batch 3 so the pure layer stays unit-testable under node
 * (no @/ aliases or browser deps), while components keep one import surface here.
 */
import { getSupabaseClient } from "@/lib/supabase/client";
import { formatPaise } from "@/lib/services/formatting";

export * from "./gst";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export { API };

// ── Money formatter (paise → ₹) ──────────────────────────────────────────────
export function fmt(paise: number): string {
  return paise === 0 ? "—" : formatPaise(paise);
}

// A bulk action can loop hundreds of these calls with a single token fetched
// once at the start — refresh once and retry on 401 rather than surfacing a
// raw "Token expired" mid-batch (see purchases/page.tsx's handleBulkReceive,
// which hit exactly this on a 754-row selection). Safe to retry: a 401 means
// auth rejected the request before any handler ran, so nothing was processed.
async function refreshedAuthToken(): Promise<string | null> {
  const supabase = getSupabaseClient();
  const { data } = await supabase.auth.refreshSession();
  return data.session?.access_token ?? null;
}

// ── REST client (Supabase-authed calls to the FastAPI backend) ───────────────
export async function apiCall(
  endpoint: string,
  method: "POST" | "PUT" | "PATCH" | "DELETE",
  body?: unknown,
  token?: string
): Promise<{ success: boolean; data: unknown; error: string | null }> {
  const doFetch = (t?: string) => fetch(`${API}${endpoint}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(t ? { Authorization: `Bearer ${t}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  let res = await doFetch(token);
  if (res.status === 401) {
    const newToken = await refreshedAuthToken();
    if (newToken && newToken !== token) res = await doFetch(newToken);
  }
  if (!res.ok && res.status !== 200) {
    // Try to parse as JSON first (FastAPI returns structured errors)
    const text = await res.text().catch(() => "Request failed");
    let errorMsg = text;
    try {
      const json = JSON.parse(text);
      // FastAPI validation error: { detail: [{msg, loc, type}] }
      if (json.detail && Array.isArray(json.detail)) {
        errorMsg = json.detail.map((e: { msg?: string }) => e.msg ?? String(e)).join("; ");
      } else if (typeof json.detail === "string") {
        errorMsg = json.detail;
      } else if (json.error) {
        errorMsg = json.error;
      }
    } catch {
      // text is not JSON — use as-is
    }
    return { success: false, data: null, error: errorMsg };
  }
  return res.json();
}

export async function getAuthToken(): Promise<string> {
  const supabase = getSupabaseClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session?.access_token ?? "";
}

export async function apiGet(
  endpoint: string,
  token?: string
): Promise<{ success: boolean; data: unknown; error: string | null }> {
  const doFetch = (t?: string) => fetch(`${API}${endpoint}`, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
      ...(t ? { Authorization: `Bearer ${t}` } : {}),
    },
  });
  let res = await doFetch(token);
  if (res.status === 401) {
    const newToken = await refreshedAuthToken();
    if (newToken && newToken !== token) res = await doFetch(newToken);
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "Request failed");
    return { success: false, data: null, error: text };
  }
  return res.json();
}
