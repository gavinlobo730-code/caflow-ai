import type { ClientSection } from "./ClientNavContext";

/**
 * Per-client "last section visited" — lets re-opening a client from the
 * client list resume where the user left off (e.g. Sales) instead of always
 * landing on Overview. Deliberately separate from the client sidebar's own
 * active-section detection: this is only ever read by the bare
 * /clients/{id} root redirect (see app/clients/[id]/page.tsx), so an
 * explicit deep link straight to a section (e.g. /clients/{id}/sales/ from
 * search results) is never intercepted or overridden by it.
 */
const STORAGE_KEY = "practicesync_client_sections_v1";

function readAll(): Record<string, ClientSection> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Record<string, ClientSection>) : {};
  } catch {
    return {};
  }
}

export function getLastClientSection(clientId: string): ClientSection | null {
  if (!clientId) return null;
  return readAll()[clientId] ?? null;
}

export function recordLastClientSection(clientId: string, section: ClientSection): void {
  if (typeof window === "undefined" || !clientId) return;
  try {
    const all = readAll();
    if (all[clientId] === section) return;
    all[clientId] = section;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(all));
  } catch {
    // ignore storage errors (private browsing, quota, etc.)
  }
}
