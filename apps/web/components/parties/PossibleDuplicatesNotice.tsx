/**
 * "You already have a Sharma Traders" — PUR-32.
 *
 * The server CREATED the party exactly as asked and named what it resembles;
 * `apps/api/domain/party_duplicates.py` carries the argument for reporting
 * rather than merging, and the sentence per reason comes from there. This
 * component renders it and decides nothing — in particular it never offers a
 * "merge these" action, because merging two parties on a name is invisible and
 * moves money, and there is no undo.
 *
 * ONE COMPONENT, THREE SCREENS. Suppliers are created from the firm-level
 * Supplier Master and from the client's Vendors tab, and customers from the
 * Customer modal; the same warning spelled three times is three warnings that
 * can disagree, which is what `components/gst/Gstr3bFindings.tsx` was extracted
 * to end.
 */
"use client";

export type PossibleDuplicate = {
  id: string;
  name: string;
  reason: string;
  gstin?: string | null;
  pan?: string | null;
  /** The sentence is the SERVER'S. A copy here would be a second rule. */
  explanation: string;
};

export function PossibleDuplicatesNotice({
  duplicates,
  noun,
  onDismiss,
}: {
  duplicates: PossibleDuplicate[];
  /** "supplier" or "customer" — the only thing that differs between screens. */
  noun: string;
  onDismiss?: () => void;
}) {
  if (!duplicates.length) return null;
  // The server sorts exact matches first, so the leading explanation is the
  // strongest one. Grouping by reason keeps the two sentences apart: they mean
  // different things and a merged paragraph would assert the stronger claim
  // about both.
  const byReason: { reason: string; rows: PossibleDuplicate[] }[] = [];
  for (const d of duplicates) {
    const group = byReason.find((g) => g.reason === d.reason);
    if (group) group.rows.push(d);
    else byReason.push({ reason: d.reason, rows: [d] });
  }

  return (
    <div
      role="status"
      className="rounded-lg border border-ps-state-attention-border bg-ps-state-attention-surface p-3 text-xs"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="font-semibold text-ps-state-attention">
          This {noun} was saved. You may already have it.
        </p>
        {onDismiss && (
          <button
            onClick={onDismiss}
            className="text-ps-label hover:text-ps-body shrink-0"
            aria-label="Dismiss"
          >
            Dismiss
          </button>
        )}
      </div>
      {byReason.map(({ reason, rows }) => (
        <div key={reason} className="mt-2">
          <p className="text-ps-body">{rows[0].explanation}</p>
          <ul className="mt-1.5 space-y-1">
            {rows.map((d) => (
              <li key={d.id} className="text-ps-body">
                <span className="font-medium">{d.name}</span>
                {/* The identifiers are what tell two real namesakes apart —
                    Sharma Traders in Pune and Sharma Traders in Nashik — so
                    they are shown rather than the CA having to go and look. */}
                {(d.gstin || d.pan) && (
                  <span className="text-ps-hint">
                    {" · "}
                    {d.gstin ? `GSTIN ${d.gstin}` : `PAN ${d.pan}`}
                  </span>
                )}
                {!d.gstin && !d.pan && (
                  <span className="text-ps-hint"> · no GSTIN or PAN recorded</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
