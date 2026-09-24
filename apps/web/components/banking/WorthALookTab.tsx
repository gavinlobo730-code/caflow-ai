"use client";
/**
 * Worth a Look — what a partner should test in this client's bank, and why.
 *
 * `apps/api/domain/banking/exceptions.py` decides which posted lines carry a
 * reason to look and writes the sentence for each; this screen renders them and
 * decides nothing. It holds no threshold, no severity ordering and no message:
 * the one place a rule lives is the domain module, and a browser copy is what
 * the Schedule III captions and the TDS engine were each extracted to end.
 *
 * READ-ONLY, AND THAT IS THE FEATURE
 *   There is no Approve, no Clear, no Accept and no Undo here, on purpose. The
 *   module's own argument is that a platform should not hold a CA's books
 *   hostage to a threshold it invented; raising a flag is not blocking a
 *   posting, and an action on this screen would make it one. A row carrying
 *   `blocking` says so in words — that is the rules' judgement about what a
 *   gate WOULD stop, shown so a firm can see it, never acted on.
 *
 *   The one thing a row does is OPEN the line on Entries, because a partner who
 *   wants to look needs the line, not a copy of it.
 *
 * THE PERIOD IS A CONTROL, NOT A DEFAULT THAT DRIFTS
 *   It opens on the previous whole month — the thing a partner actually
 *   reviews, and a complete one, since half of this month is not a review. The
 *   server requires both dates, so no code path here can ask for "everything".
 */
import { useCallback, useEffect, useState } from "react";
import { api, type WorthALook, type WorthALookRow } from "@/lib/api";
import { TableSkeleton } from "@/components/ui/skeleton";
import { fmt } from "@/components/banking/shared";
import { toLocalISO } from "@/lib/dateMath";
import { GapList } from "@/components/ui/callout";
import { objectWithLists } from "@/lib/api/shape";

/** The previous whole month, on the LOCAL calendar — the period a partner
 *  reviews, and a complete one, since half of this month is not a review.
 *
 *  Built from local components and read back with `toLocalISO`, never
 *  `toISOString().slice(0, 10)`: the second reads a calendar date out of a UTC
 *  instant, which between 00:00 and 05:30 IST is the day before — so a partner
 *  opening this before dawn on 1 August would be shown 1–30 June.
 *  scripts/a-calendar-date-is-never-read-back-in-utc.test.ts is the guard, and
 *  it caught exactly that here. */
function previousMonth(): { from: string; to: string } {
  const now = new Date();
  const end = new Date(now.getFullYear(), now.getMonth(), 0);   // day 0 = last of previous
  const start = new Date(end.getFullYear(), end.getMonth(), 1);
  return { from: toLocalISO(start), to: toLocalISO(end) };
}

const SEVERITY_STYLE: Record<string, string> = {
  high: "bg-state-problem-surface border-state-problem-border text-state-problem",
  medium: "bg-state-attention-surface border-state-attention-border text-state-attention",
  low: "bg-ps-bg border-ps-border text-ps-label",
};

export function WorthALookTab({ clientId }: { clientId: string }) {
  const initial = previousMonth();
  const [from, setFrom] = useState(initial.from);
  const [to, setTo] = useState(initial.to);
  const [data, setData] = useState<WorthALook | null>(null);
  const [loading, setLoading] = useState(true);
  // A failed load must never render as "nothing to look at" — the whole value
  // of this list is that an empty one means something (audit M17's lesson,
  // applied where it matters most).
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    setFailed(false);
    try {
      const res = await api.banking.worthALook({
        client_id: clientId, from_date: from, to_date: to,
      });
      if (!res.success || !res.data) throw new Error(res.error ?? "failed");
      setData(objectWithLists<WorthALook>(res.data, "flagged"));
    } catch {
      setData(null);
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId, from, to]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor="wal-from" className="block text-2xs font-medium text-ps-label mb-1">From</label>
          <input id="wal-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)}
            className="text-xs px-2 py-1.5 border border-ps-border rounded-lg" />
        </div>
        <div>
          <label htmlFor="wal-to" className="block text-2xs font-medium text-ps-label mb-1">To</label>
          <input id="wal-to" type="date" value={to} onChange={(e) => setTo(e.target.value)}
            className="text-xs px-2 py-1.5 border border-ps-border rounded-lg" />
        </div>
        <p className="text-2xs text-ps-hint pb-1.5">
          Posted lines only. Nothing here changes an entry — it is what to test,
          not what to approve.
        </p>
      </div>

      {loading && <TableSkeleton rows={4} />}

      {!loading && failed && (
        <div className="rounded-lg border border-state-problem-border bg-state-problem-surface p-3 text-xs text-state-problem">
          The review list could not be built, so this is not &ldquo;nothing to look
          at&rdquo;. Try again, or narrow the period.
        </div>
      )}

      {!loading && !failed && data && (
        <>
          {/* What could not be asked comes FIRST. A rule that did not run looks
              exactly like one that passed, and a partner reading a short list
              needs to know which rules were behind it. */}
          <GapList gaps={data.gaps} tone="attention" />

          <p className="text-xs text-ps-label">
            {data.reviewed_count === 0
              ? "No posted lines in this period."
              : <>
                  {data.flagged.length === 0
                    ? `Nothing stood out in ${data.reviewed_count} posted line${data.reviewed_count === 1 ? "" : "s"}.`
                    : `${data.flagged.length} of ${data.reviewed_count} posted lines are worth a look.`}
                </>}
          </p>

          <div className="space-y-2">
            {data.flagged.map((row) => <Row key={row.transaction_id} row={row} />)}
          </div>

          {Object.keys(data.policy).length > 0 && (
            /* Materiality is a judgement, not a constant. A list that does not
               say what it was measured against cannot be argued with. */
            <p className="text-2xs text-ps-hint">
              Measured at: material above {fmt(data.policy.materiality_paise)},
              settlement tolerance {fmt(data.policy.settlement_tolerance_paise)},
              cash withdrawal {fmt(data.policy.cash_withdrawal_paise)},
              duplicates within {data.policy.duplicate_window_days} days.
            </p>
          )}
        </>
      )}
    </div>
  );
}

function Row({ row }: { row: WorthALookRow }) {
  const amount = row.debit_paise || row.credit_paise;
  const out = row.debit_paise > 0;
  return (
    <div className="rounded-lg border border-ps-border bg-white p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="min-w-0">
          <span className="text-xs font-medium text-ps-ink">{row.payee_name || "—"}</span>
          <span className="text-2xs text-ps-hint"> · {row.transaction_date}</span>
          {row.matched_document_no && (
            <span className="text-2xs text-ps-hint"> · {row.matched_document_no}</span>
          )}
          <p className="text-2xs text-ps-label truncate">{row.description}</p>
        </div>
        {/* Money direction, which is NOT state — the ps.money scale exists so a
            withdrawal is not rendered in the colour that means "a problem". */}
        <span className={`text-xs font-mono ${out ? "text-money-out" : "text-money-in"}`}>
          {out ? "−" : "+"}{fmt(amount)}
        </span>
      </div>
      <ul className="mt-2 space-y-1">
        {row.exceptions.map((e) => (
          <li key={e.code}
            className={`rounded border px-2 py-1 text-2xs ${SEVERITY_STYLE[e.severity] ?? SEVERITY_STYLE.low}`}>
            {e.message}
            {e.blocking && (
              <span className="ml-1 opacity-75">
                (a firm that wanted a hard stop would stop here — this one does not)
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
