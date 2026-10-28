"use client";

/**
 * The last few events of ONE document, for the summary rail beside an editor (POST-A-150, the density audit's F5).
 *
 * The Hub drawer of a document draws its whole history; the editor's rail had none, so a CA correcting an invoice could not see
 * that it had been emailed or when it was issued without leaving the page. This is the same read the drawers make
 * (`lib/documents/activity`: the server filters on the record and says whether older entries exist) in a component of its own, so
 * the editor, which is already a long file, asks for nothing itself. Which events show, and whether to say older ones exist, is
 * `miniActivity` in that module, where it is tested.
 *
 * WHAT IT SAYS, AND WHAT IT DOES NOT
 *   * it lists the document's own timeline events only. A drawer also merges the delivery attempts and the e-invoice and e-way bill
 *     records into its feed; this does not, and its heading says "Recent activity" and not "History";
 *   * a read that failed says "The activity could not be loaded." and never "No activity recorded yet." (`emptyActivityLine`);
 *   * more than `ACTIVITY_MINI_COUNT` events, or a window the server said was cut, is said in a sentence and never left looking
 *     complete.
 */
import { useEffect, useState } from "react";
import { Clock } from "lucide-react";
import { apiGet, getAuthToken } from "@/lib/invoices/shared";
import { formatDateTime } from "@/lib/services/formatting";
import {
  ACTIVITY_MINI_COUNT, ACTIVITY_NOT_YET_ASKED, activityItems, activityStatusOf, documentActivityUrl, emptyActivityLine, miniActivity,
  readDocumentActivity, type ActivityItem, type ActivityStatus,
} from "@/lib/documents/activity";

export function ActivityMini({ clientId, entityType, entityId }: { clientId: string; entityType: string; entityId: string }) {
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [status, setStatus] = useState<ActivityStatus>(ACTIVITY_NOT_YET_ASKED);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const token = await getAuthToken();
        const tl = await apiGet(documentActivityUrl(clientId, entityType, entityId), token);
        if (cancelled) return;
        const win = readDocumentActivity(tl, entityType, entityId);
        setItems(win ? activityItems(win.rows) : []);
        setStatus(activityStatusOf(win));
      } catch {
        if (cancelled) return;
        setItems([]);
        setStatus({ read: false });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [clientId, entityType, entityId]);

  const { shown, more } = miniActivity(items, status);
  return (
    <div className="bg-white rounded-xl border border-ps-border p-4 space-y-2 text-xs mt-3" data-testid="activity-mini">
      <h4 className="font-semibold text-ps-body flex items-center gap-1"><Clock size={11} /> Recent activity</h4>
      {loading ? (
        <p className="text-ps-hint">Loading…</p>
      ) : shown.length === 0 ? (
        <p className="text-ps-hint">{emptyActivityLine(status)}</p>
      ) : (
        <ol className="space-y-2 border-l border-ps-border pl-3">
          {shown.map((a, i) => (
            <li key={`${a.at}-${i}`} className="relative">
              <span className="absolute -left-[15px] top-1 h-1.5 w-1.5 rounded-full bg-ps-border-strong" />
              <p className="text-2xs text-ps-body">{a.title}</p>
              {a.detail && <p className="text-3xs text-ps-hint">{a.detail}</p>}
              <p className="text-3xs text-ps-disabled">{formatDateTime(a.at)}</p>
            </li>
          ))}
        </ol>
      )}
      {more && <p className="text-3xs text-ps-hint">Showing the latest {ACTIVITY_MINI_COUNT}. Older entries exist.</p>}
    </div>
  );
}
