"use client";

/**
 * The banner that OFFERS a draft kept in this tab (frontend_ux-23).
 *
 * Offered, never applied: restoring over a form the person has not looked at
 * would be the browser deciding what goes into a voucher, and discarding is as
 * legitimate an answer as restoring. Both are one click and neither saves
 * anything — the banner says so, because "restored" next to a ledger reads as
 * "posted" to somebody in a hurry.
 *
 * The time is shown in IST with the label (CLAUDE.md, "Reporting times to the
 * user"): `savedAt` is an instant, and a bare local clock reading says nothing
 * about which zone it is in.
 */
import { Callout } from "@/components/ui/callout";
import { Button } from "@/components/ui/button";
import { formatIstLabelled } from "@/lib/dates/formatIst";

export function DraftOffer({
  savedAt, what, onRestore, onDiscard,
}: {
  /** ISO instant the draft was written. */
  savedAt: string;
  /** What was being typed, in the CA's words: "journal entry", "purchase bill". */
  what: string;
  onRestore: () => void;
  onDiscard: () => void;
}) {
  return (
    <Callout tone="attention" title={`Restore your unsaved ${what}?`}>
      <p>
        This browser tab kept what you were typing on {formatIstLabelled(savedAt)}.
        Nothing from it has been saved to the books.
      </p>
      <div className="mt-2 flex gap-2">
        <Button
          type="button" variant="plain" size="none" onClick={onRestore}
          className="rounded-lg bg-brand px-3 py-1.5 text-xs text-white hover:bg-brand-dark"
        >
          Restore draft
        </Button>
        <Button
          type="button" variant="plain" size="none" onClick={onDiscard}
          className="rounded-lg border border-ps-border bg-white px-3 py-1.5 text-xs text-ps-label hover:bg-ps-bg"
        >
          Discard it
        </Button>
      </div>
    </Callout>
  );
}
