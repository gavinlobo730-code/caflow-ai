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
import { errorMessage } from "@/lib/api";

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
  if (!res.ok) {
    return { success: false, data: null, error: await refusalSentence(res) };
  }
  return res.json();
}

/**
 * The sentence a CA is shown for a non-OK response, never the body itself.
 *
 * `apiGet` used to hand back the raw body as `error`, so a 500 reached the
 * screen as `{"success":false,"data":null,"error":"Internal server error"}` —
 * the Cash Book rendered exactly that. One reader for both helpers here: the
 * sentence is pulled out by lib/api's `errorMessage` (FastAPI's `detail` as a
 * string, a validation array or `{message, problems}`, else the envelope's
 * `error`), which is the one parser every `request()` caller already gets.
 *
 * Where it finds no sentence it falls back to the raw body, prefixed
 * `API error <status>` — an HTML page from the proxy, or an envelope whose
 * `error` is null. That prefix is the signal it found nothing, and a plain
 * sentence is shown instead: a status code is worth keeping, a page of markup
 * or JSON is not.
 */
async function refusalSentence(res: Response): Promise<string> {
  const message = await errorMessage(res);
  if (message.startsWith(`API error ${res.status}`)) {
    return `The server could not complete this request (HTTP ${res.status}). Please try again in a moment.`;
  }
  return message;
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
    return { success: false, data: null, error: await refusalSentence(res) };
  }
  return res.json();
}
