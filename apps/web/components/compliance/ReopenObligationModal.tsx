"use client";

/**
 * ReopenObligationModal — the one prompt for taking back a recorded filing on a statutory deposit (POST-A-267, item 3), shared by
 * /deadlines and a client's Compliance tab.
 *
 * It asks for a REASON and nothing else: the server requires one, keeps it on the obligation and in the audit log, and says in the
 * answer what it did and did not do (a payment record that closed the obligation is NOT retracted by this). Which obligations may
 * be reopened is the server's knowledge (`GET /api/compliance/reopenable-types`), so this component is only shown for those and
 * decides nothing; a refusal comes back as a sentence and is shown as written.
 *
 * Nothing is filed or un-filed at any portal by this: it corrects the practice's own calendar line. CA REVIEW REQUIRED — DO NOT
 * AUTO-SUBMIT.
 */
import { useState } from "react";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";

export function ReopenObligationModal({
  intro,
  maxReasonChars,
  busy,
  error,
  onConfirm,
  onClose,
}: {
  /** One sentence above the field: which obligation this is about. */
  intro?: string;
  /** The server's limit on the reason. */
  maxReasonChars: number;
  busy: boolean;
  /** The server's sentence when the last attempt was refused. */
  error?: string | null;
  /** Returns the request's promise, which is what lets the confirm button ignore a second click made in the same moment. */
  onConfirm: (reason: string) => unknown;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const trimmed = reason.trim();

  return (
    <Modal title="Reopen this obligation" onClose={onClose} maxWidthClass="max-w-md" note={intro}>
      <div className="space-y-3">
        <p className="text-xs text-ps-body">
          This takes the filing back off the calendar: the obligation returns to Ready To File and its filing date and
          acknowledgement number are cleared. A payment record that closed it is not touched by this, and for some deposits a later
          save of that register can close the obligation again, so correct the record first if it was wrong. The answer says which
          applies.
        </p>
        <div>
          <label htmlFor="reopen-reason" className="text-xs font-medium text-ps-body block mb-1">
            Why is it being reopened?
          </label>
          <textarea
            id="reopen-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={maxReasonChars}
            rows={3}
            placeholder="For example: entered against the wrong month"
            className="w-full px-3 py-1.5 text-sm border border-state-working-border rounded-md focus:outline-none focus:ring-2 focus:ring-brand bg-white"
          />
          <p className="text-3xs text-ps-hint mt-1">Kept on the obligation and in the audit log. Up to {maxReasonChars} characters.</p>
        </div>

        {error && (
          <p role="alert" className="text-xs text-state-problem bg-state-problem-surface rounded px-2 py-1.5">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            className="text-xs px-3 py-1.5 border border-ps-border rounded-md hover:bg-ps-muted bg-white"
          >
            Cancel
          </button>
          {/* The shared button: it holds a synchronous guard from the click until the promise settles, so a second click in the same
              moment is ignored (a `busy` flag lags the click by a render and lets both through). */}
          <Button
            type="button"
            variant="plain"
            size="none"
            onClick={() => onConfirm(trimmed)}
            disabled={busy || trimmed === ""}
            className="text-xs px-3 py-1.5 bg-brand text-white rounded-md hover:bg-brand-dark disabled:opacity-50"
          >
            {busy ? "Reopening…" : "Reopen"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
