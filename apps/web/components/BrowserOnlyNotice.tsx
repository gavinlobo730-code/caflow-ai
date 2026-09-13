"use client";

import { AlertTriangle } from "lucide-react";

/**
 * A screen that keeps what the CA enters in this browser's localStorage, and
 * says so (ACC-06).
 *
 * WHY IT EXISTS
 *     `/accounting/recurring`, `/accounting/budget` and `/accounting/retainer`
 *     store everything in localStorage: no table, no RLS, no sharing, no
 *     scheduler. A partner who sets a recurring template up on their laptop
 *     finds nothing on the office machine, a second user sees an empty screen,
 *     and clearing site data loses the lot with no warning and no backup.
 *
 *     None of that was stated anywhere. The Recurring card on the accounting
 *     hub said "Automate monthly, quarterly & yearly entries" — a promise the
 *     screen cannot keep, since nothing posts a due template. So a CA had
 *     every reason to believe the firm's recurring journals were set up.
 *
 * WHY A NOTICE AND NOT A FIX
 *     The fix is firm-scoped tables with RLS, CRUD behind `rbac()`, and the
 *     scheduler posting due templates as DRAFTS into the approval queue —
 *     which is a migration, and a migration applies to production the moment
 *     it merges. The finding names this notice as the interim in its own
 *     words: "until then the hub cards should say 'this device only'".
 *
 *     This is deliberately NOT the pattern CLAUDE.md warns about, where
 *     `/gst/reconciliation` "carried a banner disowning itself, which is a
 *     warning label rather than a fix". That screen was a DUPLICATE and a
 *     working alternative existed one tab over, so the honest act was to
 *     delete it. These three have no alternative: the work they do is real and
 *     the only thing wrong is where it is kept. Saying where is the whole of
 *     what can be said truthfully today.
 */
export default function BrowserOnlyNotice({ what, alsoNot }: {
  /** What this screen keeps — e.g. "recurring templates". */
  what: string;
  /** One more thing it does not do, where there is one. */
  alsoNot?: string;
}) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
      <AlertTriangle size={15} className="mt-0.5 shrink-0 text-amber-600" />
      <div className="text-xs text-amber-900 space-y-1">
        <p>
          <strong>Saved in this browser only.</strong> The {what} on this screen are kept
          in this browser&apos;s local storage — not in the database. Nobody else in the
          firm can see them, they will not be here on another device or in another
          browser, and clearing site data removes them permanently.
        </p>
        {alsoNot && <p>{alsoNot}</p>}
        <p className="text-amber-800">
          Export anything you need to keep. Firm-wide storage is a scheduled change.
        </p>
      </div>
    </div>
  );
}
