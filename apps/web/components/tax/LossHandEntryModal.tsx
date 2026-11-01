"use client";

/**
 * LossHandEntryModal — the one prompt for correcting a brought-forward loss record by hand (POST-A-368, items 2 and 3).
 *
 * Two jobs, one dialog, because both need the same thing: a REASON, which the server requires and keeps with what the record held in the audit
 * log before it changes anything.
 *
 *   * `record`    "this year used this much of the loss". A year that a filed return already holds is refused by the server, as is an amount
 *                 past what the record could take (the sentence says how much it could); the screen decides neither and shows the sentence as
 *                 written. Recording the same year again SETS it. This is for a return filed before this product, or one whose saved
 *                 computation was never pinned; a return that is pinned writes its own use when its loss records are written.
 *   * `take_back` one entry off the record: a use somebody typed, or the use a filed return wrote. A return's entry comes back the next time
 *                 that return's loss records are written, and the dialog says so before the click.
 *
 * It holds no rule and adds nothing up: the amount is converted by the one rupee parser, the years come from the clock, and every refusal is
 * the server's. Nothing is filed. CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
 */
import { useState } from "react";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/field";
import { YearPicker } from "@/components/ui/year-picker";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";

/** How many years back the year picker reaches: a loss is carried forward for up to eight years. */
const YEARS_OFFERED = 10;

export type LossHandEntryMode =
  | { kind: "record"; lossName: string }
  | { kind: "take_back"; lossName: string; entryLabel: string; byAReturn: boolean };

export function LossHandEntryModal({
  mode,
  busy,
  error,
  onRecord,
  onTakeBack,
  onClose,
}: {
  mode: LossHandEntryMode;
  busy: boolean;
  /** The server's sentence when the last attempt was refused. */
  error?: string | null;
  /** Return the request's promise: it is what lets the confirm button ignore a second click made in the same moment. */
  onRecord: (financialYear: string, amountPaise: number, reason: string) => unknown;
  onTakeBack: (reason: string) => unknown;
  onClose: () => void;
}) {
  const [year, setYear] = useState("");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const why = reason.trim();
  const paise = paiseFromRupeeInput(amount);
  const recording = mode.kind === "record";
  const amountProblem =
    !recording ? null
    : amount.trim() === "" ? null
    : paise === null || paise < 0 ? "Enter the amount in rupees with no commas, for example 400000 or 400000.50."
    : paise === 0 ? "Enter more than nothing. To remove a year's use, take it back from the list."
    : null;
  const ready = recording
    ? year !== "" && paise !== null && paise > 0 && why !== ""
    : why !== "";

  return (
    <Modal
      title={recording ? "Record a year's use by hand" : "Take this use off the loss"}
      onClose={onClose}
      maxWidthClass="max-w-md"
      note={mode.lossName}
    >
      <div className="space-y-3">
        {recording ? (
          <p className="text-xs text-ps-body">
            Use this for a return filed before PracticeSync, or one whose saved computation was never pinned, so the loss record does not show
            what that year used. Recording the same year again replaces it. A year that a filed return already holds is corrected on that
            return, not here. Your reason is kept with the change in the audit log.
          </p>
        ) : (
          <p className="text-xs text-ps-body">
            This takes {mode.entryLabel} off the loss record, so the loss is offered again for later computations. Your reason and what the
            record held are kept in the audit log.
            {mode.byAReturn
              ? " It was written by a filed return and comes back the next time that return's loss records are written; to keep it off, do not write them again."
              : ""}
          </p>
        )}

        {recording && (
          <>
            <YearPicker kind="fy" label="Financial year that used the loss" value={year} onChange={setYear} placeholder="Choose a year" count={YEARS_OFFERED} />
            <Field label="Amount of the loss it used (₹)" error={amountProblem ?? undefined}>
              <Input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="400000" autoComplete="off" />
            </Field>
          </>
        )}

        <Field label={recording ? "Why is this being recorded?" : "Why is it being taken off?"} hint="Kept in the audit log.">
          <Textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            placeholder={recording ? "For example: filed on the portal before we took over the books" : "For example: typed against the wrong loss"}
          />
        </Field>

        {error && (
          <p role="alert" className="text-xs text-state-problem bg-state-problem-surface rounded px-2 py-1.5">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="text-xs px-3 py-1.5 border border-ps-border rounded-md hover:bg-ps-muted bg-white">
            Cancel
          </button>
          {/* The shared button holds a synchronous guard from the click until the promise settles, so a second click in the same moment is
              ignored (a `busy` flag lags the click by a render and lets both through). */}
          <Button
            type="button"
            variant="plain"
            size="none"
            onClick={() => (recording ? onRecord(year, paise ?? 0, why) : onTakeBack(why))}
            disabled={busy || !ready}
            className="text-xs px-3 py-1.5 bg-brand text-white rounded-md hover:bg-brand-dark disabled:opacity-50"
          >
            {busy ? "Saving…" : recording ? "Record" : "Take it off"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
