"use client";

/**
 * MarkFiledModal — the one prompt for recording that an obligation was filed,
 * shared by /deadlines (single row and bulk), a client's Compliance tab and
 * Practice → Compliance.
 *
 * It asks for the DATE the return was filed on the portal, and always shows it.
 * For a GSTR-1 or GSTR-3B the server REQUIRES that date and, with it, records the
 * filing so the period locks; the lock message later quotes it to whoever tries
 * to post into the period, so it is something the CA states rather than
 * something the software stamps. The field is prefilled with today because that
 * is the commonest answer — visible and editable, never sent unseen. The ARN is
 * optional throughout. Which returns lock is the server's knowledge, not this
 * component's: it says what the server will do in general terms and the answer
 * that comes back says what it did (lib/compliance/filingOutcome).
 *
 * Nothing is filed anywhere by this: it records what the CA has already done on
 * the portal. CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
 */
import { useState } from "react";
import { Modal } from "@/components/ui/modal";
import { todayLocalISO } from "@/lib/dateMath";

export interface MarkFiledValues { filedDate: string; arn: string }

export function MarkFiledModal({
  title = "Mark as Filed",
  intro,
  showArn = true,
  initialArn = "",
  busy,
  error,
  onConfirm,
  onClose,
}: {
  title?: string;
  /** One sentence above the fields — which obligation(s) this is about. */
  intro?: string;
  /** Bulk marking collects no per-row ARN. */
  showArn?: boolean;
  /** An ARN already on the row, so re-opening does not lose it. */
  initialArn?: string;
  busy: boolean;
  /** The server's sentence when the last attempt was refused. */
  error?: string | null;
  onConfirm: (v: MarkFiledValues) => void;
  onClose: () => void;
}) {
  const today = todayLocalISO();
  const [filedDate, setFiledDate] = useState(today);
  const [arn, setArn] = useState(initialArn);

  return (
    <Modal title={title} onClose={onClose} maxWidthClass="max-w-md"
      note={intro}>
      <div className="space-y-3">
        <div>
          <label htmlFor="mark-filed-date" className="text-xs font-medium text-ps-body block mb-1">
            Filed on
          </label>
          <input
            id="mark-filed-date"
            type="date"
            value={filedDate}
            max={today}
            onChange={(e) => setFiledDate(e.target.value)}
            className="w-full px-3 py-1.5 text-sm border border-state-working-border rounded-md focus:outline-none focus:ring-2 focus:ring-brand bg-white"
          />
          <p className="text-3xs text-ps-hint mt-1">
            The date it was filed on the portal. Recording a GSTR-1 or GSTR-3B as filed
            also locks that period against new entries, and the lock quotes this date.
          </p>
        </div>

        {showArn && (
          <div>
            <label htmlFor="mark-filed-arn" className="text-xs font-medium text-ps-body block mb-1">
              ARN / acknowledgement number
            </label>
            <input
              id="mark-filed-arn"
              value={arn}
              onChange={(e) => setArn(e.target.value)}
              placeholder="Optional"
              className="w-full px-3 py-1.5 text-sm border border-state-working-border rounded-md focus:outline-none focus:ring-2 focus:ring-brand bg-white"
            />
          </div>
        )}

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
          <button
            type="button"
            onClick={() => onConfirm({ filedDate, arn: arn.trim() })}
            disabled={busy || !filedDate}
            className="text-xs px-3 py-1.5 bg-brand text-white rounded-md hover:bg-brand-dark disabled:opacity-50"
          >
            {busy ? "Saving…" : "Confirm Filed"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
