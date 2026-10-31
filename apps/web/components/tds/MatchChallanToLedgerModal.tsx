"use client";

/**
 * MatchChallanToLedgerModal — tie a recorded TDS challan to the ledger entry that paid it, or take that link back (POST-A-272).
 *
 * A LINK, NEVER A POSTING. The bank line the CA passes already writes Dr TDS Payable / Cr Bank, and posting from the challan as well
 * would debit it twice, so this only records which entry paid which challan. Without it, a liability nobody has paid and one that was
 * paid and never tied back look identical on the ledger.
 *
 * The server decides everything: which entries are offered (the ones that debited the TDS Payable account the challan's section
 * belongs to, inside a week of its payment date, best first, each with its own sentence for why), and which link is refused and why.
 * This component decides nothing; it shows the server's sentences as written, never a score, and ties nothing until a person presses
 * the button on one entry. CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: nothing here reaches a portal.
 */
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/dates/format";
import type { ChallanLedgerCandidates } from "@/lib/data/tds";

export function MatchChallanToLedgerModal({
  intro,
  answer,
  loading,
  loadError,
  busy,
  error,
  canTie,
  onLink,
  onUnlink,
  onClose,
}: {
  /** One sentence above the list: which challan this is (its serial number, date and amount). */
  intro?: string;
  /** What the server found; null until it has answered. */
  answer: ChallanLedgerCandidates | null;
  loading: boolean;
  /** Why the entries could not be read, in the server's words. */
  loadError?: string | null;
  busy: boolean;
  /** The server's sentence when the last attempt to tie or take back was refused. */
  error?: string | null;
  /** The person holds the tier the server asks for; the server asks again. */
  canTie: boolean;
  /** Return the request's promise: the shared Button ignores a second click until it settles. */
  onLink: (journalEntryId: string) => unknown;
  onUnlink: () => unknown;
  onClose: () => void;
}) {
  const tied = answer?.journal_entry_id ?? null;

  return (
    <Modal title="Match this challan to the ledger" onClose={onClose} maxWidthClass="max-w-xl" note={intro}>
      <div className="space-y-3">
        <p className="text-xs text-ps-body">
          This records which ledger entry paid the challan. It posts nothing: the entry is the one the bank statement line was passed
          to, and the challan only points at it.
        </p>

        {loading && <p className="text-xs text-ps-hint" role="status">Looking in the ledger…</p>}
        {loadError && !loading && (
          <p role="alert" className="text-xs text-state-problem bg-state-problem-surface rounded px-2 py-1.5">{loadError}</p>
        )}

        {answer && !loading && tied && (
          <div className="rounded-md border border-ps-border bg-ps-bg px-3 py-2 space-y-2">
            <p className="text-xs text-ps-ink">This challan is tied to a ledger entry.</p>
            {canTie && (
              <Button
                type="button"
                variant="plain"
                size="none"
                onClick={() => onUnlink()}
                disabled={busy}
                className="text-xs px-3 py-1.5 border border-ps-border rounded-md hover:bg-ps-muted bg-white disabled:opacity-50"
              >
                {busy ? "Working…" : "Take the link back"}
              </Button>
            )}
          </div>
        )}

        {answer && !loading && !tied && (
          <>
            <p className="text-xs text-ps-label">
              Entries that debited {answer.account_name} within {answer.window_days} days of the payment date, best first.
            </p>
            {answer.gap && <p className="text-xs text-ps-body bg-ps-bg rounded px-2 py-1.5">{answer.gap}</p>}
            {!answer.gap && answer.candidates.length === 0 && (
              <p className="text-xs text-ps-body bg-ps-bg rounded px-2 py-1.5">
                No entry debited {answer.account_name} in that window. If the bank line has not been passed yet, pass it first, then
                come back here.
              </p>
            )}
            <ul className="space-y-2">
              {answer.candidates.map((c) => (
                <li key={c.journal_entry_id} className="rounded-md border border-ps-border px-3 py-2 flex items-start justify-between gap-3">
                  <div className="min-w-0 space-y-0.5">
                    <p className="text-xs font-medium text-ps-ink">
                      {formatDate(c.entry_date)}
                      {c.reference_no ? <span className="font-mono text-ps-label"> · {c.reference_no}</span> : null}
                      {c.grade === "exact" ? <span className="ml-2 text-3xs text-state-ready">Same amount</span> : null}
                    </p>
                    {c.narration ? <p className="text-2xs text-ps-label truncate">{c.narration}</p> : null}
                    <p className="text-2xs text-ps-body">{c.reason}</p>
                  </div>
                  {canTie && (
                    <Button
                      type="button"
                      variant="plain"
                      size="none"
                      onClick={() => onLink(c.journal_entry_id)}
                      disabled={busy}
                      aria-label={`Tie the challan to the entry of ${formatDate(c.entry_date)}${c.reference_no ? ` ${c.reference_no}` : ""}`}
                      className="shrink-0 text-xs px-3 py-1.5 bg-brand text-white rounded-md hover:bg-brand-dark disabled:opacity-50"
                    >
                      {busy ? "Working…" : "Tie to this entry"}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}

        {error && (
          <p role="alert" className="text-xs text-state-problem bg-state-problem-surface rounded px-2 py-1.5">{error}</p>
        )}

        <div className="flex justify-end pt-1">
          <button
            type="button"
            onClick={onClose}
            className="text-xs px-3 py-1.5 border border-ps-border rounded-md hover:bg-ps-muted bg-white"
          >
            Close
          </button>
        </div>
      </div>
    </Modal>
  );
}
