/**
 * A document's own activity, as the drawers of an invoice, a bill and the four notes show it.
 *
 * THE DEFECT THIS REPLACED (POST-A-259). Each drawer asked for the CLIENT's latest hundred timeline events, of every kind,
 * and kept the ones that named its document in the browser. A document older than the client's hundredth event therefore
 * read "No activity recorded yet", an empty state that was only an artefact of where the window stopped. The server now
 * filters on the record (`entity_type` + `entity_id`) and answers `has_more`, so the window is the document's own events;
 * a failed read is said as such and is never drawn as an empty history.
 */
import { readWindow, type ReadWindow } from "../lists/readWindow.ts";

/** How many of one document's events a drawer asks for. A document has a handful; the server's ceiling is far above. */
export const DOCUMENT_ACTIVITY_WINDOW = 100;

/** The columns of a timeline event a drawer reads. */
export interface RawActivityEvent {
  entity_id?: string | null;
  entity_type?: string | null;
  title?: string | null;
  description?: string | null;
  event_type?: string | null;
  created_at?: string | null;
}

export interface ActivityItem { at: string; title: string; detail?: string }

/** The timeline read for ONE record. The ids are the document's own and are encoded, not trusted. */
export function documentActivityUrl(clientId: string, entityType: string, entityId: string): string {
  const qs = new URLSearchParams({
    client_id: clientId,
    entity_type: entityType,
    entity_id: entityId,
    limit: String(DOCUMENT_ACTIVITY_WINDOW),
  });
  return `/api/timeline?${qs.toString()}`;
}

/** What `apiGet` hands back. */
export interface ActivityResponse { success: boolean; data: unknown }

/**
 * The window of a document's events, or `null` when the read failed or was not a window.
 *
 * A server that predates the filter answers a BARE LIST of the client's latest events and ignores the two ids it was sent
 * (the web app deploys a few minutes before or after the API). Those rows are not this document's, so for that payload, and
 * only that one, the match on the record is made here; a window the server answered was filtered by the server.
 */
export function readDocumentActivity(
  resp: ActivityResponse | null | undefined,
  entityType: string,
  entityId: string,
): ReadWindow<RawActivityEvent> | null {
  if (!resp || !resp.success) return null;
  const win = readWindow<RawActivityEvent>(resp.data, "events", DOCUMENT_ACTIVITY_WINDOW);
  if (win && Array.isArray(resp.data)) {
    return { ...win, rows: win.rows.filter((e) => e.entity_type === entityType && e.entity_id === entityId) };
  }
  return win;
}

/** Events as the drawers list them: newest first, undated events left out (a row with no time cannot be placed). */
export function activityItems(events: RawActivityEvent[]): ActivityItem[] {
  return events
    .map((e) => ({
      at: e.created_at ?? "",
      title: e.title ?? e.event_type ?? "Activity",
      detail: e.description ?? undefined,
    }))
    .filter((i) => i.at)
    .sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0));
}

/** What a drawer knows about its activity read: that it could not be read, or the window it was read with. */
export type ActivityStatus =
  | { read: false }
  | { read: true; hasMore: boolean; limit: number; maxLimit: number };

/** Before anything has been asked, nothing is claimed to be cut short. */
export const ACTIVITY_NOT_YET_ASKED: ActivityStatus = {
  read: true, hasMore: false, limit: DOCUMENT_ACTIVITY_WINDOW, maxLimit: DOCUMENT_ACTIVITY_WINDOW,
};

export function activityStatusOf(win: ReadWindow<RawActivityEvent> | null): ActivityStatus {
  return win
    ? { read: true, hasMore: win.hasMore, limit: win.limit, maxLimit: win.maxLimit }
    : { read: false };
}

/** The sentence for a list with no rows: an unread history is not an empty one. */
export function emptyActivityLine(status: ActivityStatus): string {
  return status.read ? "No activity recorded yet." : "The activity could not be loaded.";
}
