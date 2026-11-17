"use client";

/**
 * ObligationRequiredModal — the one prompt for recording that an obligation is NOT REQUIRED of the client, or taking that back
 * (POST-A-267, item 4), shared by /deadlines and a client's Compliance tab.
 *
 * It asks for a REASON and nothing else: whether a client owes an instalment is the CA's statement (a §44AD or §44ADA assessee
 * pays the whole of its advance tax by 15 March), the product holds no threshold and decides nothing, and the server keeps the
 * reason on the obligation and in the audit log. Which obligations may be recorded so is the server's knowledge
 * (`not_requirable_types`), so this is only shown for those. Nothing is filed anywhere by this. CA REVIEW REQUIRED — DO NOT
 * AUTO-SUBMIT.
 */
import { useState } from "react";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";

export function ObligationRequiredModal({
  required,
  intro,
  maxReasonChars,
  busy,
  error,
  onConfirm,
  onClose,
}: {
  /** False: record it as not required. True: take a "not required" record back. */
  required: boolean;
  /** One sentence above the field: which obligation this is about. */
  intro?: string;
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
  const verb = required ? "Required again" : "Not required";

  return (
    <Modal title={required ? "Mark this obligation required again" : "Record this obligation as not required"}
      onClose={onClose} maxWidthClass="max-w-md" note={intro}>
      <div className="space-y-3">
        <p className="text-xs text-ps-body">
          {required
            ? "The obligation goes back to Not Started, and its due date says again whether it is late."
            : "The obligation stays on the calendar but stops counting as open or late anywhere. It is not recorded as filed, and no "
              + "payment is recorded. The reason is your statement of why this client does not owe it."}
        </p>
        <div>
          <label htmlFor="obligation-required-reason" className="text-xs font-medium text-ps-body block mb-1">
            {required ? "Why is it required after all?" : "Why is it not required of this client?"}
          </label>
          <textarea
            id="obligation-required-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={maxReasonChars}
            rows={3}
            placeholder={required ? "For example: not presumptive this year" : "For example: presumptive under section 44AD"}
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
          <Button
            type="button"
            variant="plain"
            size="none"
            onClick={() => onConfirm(trimmed)}
            disabled={busy || trimmed === ""}
            className="text-xs px-3 py-1.5 bg-brand text-white rounded-md hover:bg-brand-dark disabled:opacity-50"
          >
            {busy ? "Saving…" : verb}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
