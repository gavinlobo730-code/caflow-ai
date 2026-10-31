"use client";

/**
 * RetractChallanModal — the one prompt for taking a TDS challan recorded in error out of the register (POST-A-362).
 *
 * It asks for a REASON and nothing else. The server requires one, keeps it with the whole challan in the audit log BEFORE the row
 * goes, and refuses in a sentence when it cannot (no reason, a reason past its limit, a locked year, a row somebody else has
 * already retracted): that sentence is shown as written, and this component decides nothing. To correct a challan, retract it and
 * record it again; there is no edit.
 *
 * The screen says what retracting does NOT do, because it is the part a person assumes: a monthly deposit on the compliance
 * calendar that this challan helped to close is not reopened by it (the register does not record which challan closed which
 * month), and the answer says which months still read filed.
 *
 * Nothing is filed or un-filed at any portal by this: it corrects the practice's own register. CA REVIEW REQUIRED — DO NOT
 * AUTO-SUBMIT.
 */
import { useState } from "react";
import { Modal } from "@/components/ui/modal";

export function RetractChallanModal({
  intro,
  busy,
  error,
  onConfirm,
  onClose,
}: {
  /** One sentence above the field: which challan this is about (its serial number, date and amount). */
  intro?: string;
  busy: boolean;
  /** The server's sentence when the last attempt was refused. */
  error?: string | null;
  onConfirm: (reason: string) => void;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const trimmed = reason.trim();

  return (
    <Modal title="Retract this challan" onClose={onClose} maxWidthClass="max-w-md" note={intro}>
      <div className="space-y-3">
        <p className="text-xs text-ps-body">
          This takes the challan out of the register: it no longer counts toward what has been deposited, the deposit worksheet or
          the quarter&apos;s statement. The challan and your reason are kept in the audit log. A monthly deposit on the compliance
          calendar that this challan helped to close is not reopened by this; the answer says which months still read filed, and a
          Manager or Partner can reopen them.
        </p>
        <div>
          <label htmlFor="retract-challan-reason" className="text-xs font-medium text-ps-body block mb-1">
            Why is it being retracted?
          </label>
          <textarea
            id="retract-challan-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            placeholder="For example: keyed against the wrong quarter"
            className="w-full px-3 py-1.5 text-sm border border-state-working-border rounded-md focus:outline-none focus:ring-2 focus:ring-brand bg-white"
          />
          <p className="text-3xs text-ps-hint mt-1">Kept with the challan in the audit log.</p>
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
          <button
            type="button"
            onClick={() => onConfirm(trimmed)}
            disabled={busy || trimmed === ""}
            className="text-xs px-3 py-1.5 bg-brand text-white rounded-md hover:bg-brand-dark disabled:opacity-50"
          >
            {busy ? "Retracting…" : "Retract challan"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
