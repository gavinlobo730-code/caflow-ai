"use client";

/**
 * Challans recorded in the register that no ledger entry is tied to, across the caller's clients (POST-A-272).
 *
 * The Challans tab shows one client's challans with a Ledger column; a practice with many clients had no way to ask "which recorded challans have
 * nobody tied to the entry that paid them" without opening each tab. A recorded challan with no entry behind it is a deposit the register says
 * was made while TDS Payable may still show the tax as owing, so this lists the oldest first and sends the CA to the client's own Challans tab,
 * where the Match dialog offers the entries that could be the payment. It reads, and changes nothing.
 *
 * The server decides which clients the caller sees (a Partner sees the firm, anyone else the clients assigned to them) and counts every
 * challan; this component adds nothing up. A read that fails SAYS it failed: an empty panel would read as "all tied".
 */
import { useEffect, useState } from "react";
import { Callout } from "@/components/ui/callout";
import { listUnlinkedTdsChallans, type UnlinkedChallans } from "@/lib/data/tds";
import { formatDate } from "@/lib/dates/format";
import { formatPaise } from "@/lib/services/formatting";

const SHOWN = 25;

export function UnlinkedChallansPanel({ onOpenClient, reloadKey = 0 }: { onOpenClient: (clientId: string) => void; reloadKey?: number }) {
  const [state, setState] = useState<{ kind: "loading" } | { kind: "failed"; why: string } | { kind: "ready"; data: UnlinkedChallans }>({ kind: "loading" });

  useEffect(() => {
    let live = true;
    setState({ kind: "loading" });
    listUnlinkedTdsChallans(SHOWN)
      .then((data) => { if (live) setState({ kind: "ready", data }); })
      .catch((e: unknown) => { if (live) setState({ kind: "failed", why: e instanceof Error ? e.message : "Could not read the list" }); });
    return () => { live = false; };
  }, [reloadKey]);

  if (state.kind === "loading") return <p role="status" className="text-xs text-ps-hint">Checking which recorded challans are tied to a ledger entry…</p>;
  if (state.kind === "failed") {
    return (
      <Callout tone="attention" title="Challans with no ledger entry could not be listed">
        {state.why}. Until it can be read, the Ledger column on each client&apos;s Challans tab is the way to see which challans are tied.
      </Callout>
    );
  }
  return <UnlinkedChallansView data={state.data} onOpenClient={onOpenClient} />;
}

/** What the server said, drawn. Apart from the container so it can be rendered and read without a request. */
export function UnlinkedChallansView({ data, onOpenClient }: { data: UnlinkedChallans; onOpenClient: (clientId: string) => void }) {
  const { rows, total, totalPaise, hasMore, longWaitDays, totalWaitingLong } = data;
  if (total === 0) {
    return <p role="status" className="text-xs text-ps-hint">Every challan recorded for your clients is tied to a ledger entry.</p>;
  }
  return (
    <section aria-labelledby="unlinked-challans-heading" className="rounded-xl border border-state-attention-border bg-state-attention-surface p-4 space-y-2 print:hidden">
      <h2 id="unlinked-challans-heading" className="text-sm font-semibold text-ps-ink">
        {total} recorded challan{total === 1 ? " is" : "s are"} tied to no ledger entry · {formatPaise(totalPaise)}
        {totalWaitingLong > 0 ? ` · ${totalWaitingLong} waiting over ${longWaitDays} days` : ""}
      </h2>
      <p className="text-xs text-ps-label">
        The register says the tax was deposited; the ledger may still show it as owed until the bank payment is tied to its challan. Open a client to match
        the challan to the entry that paid it. {hasMore ? `Showing the ${rows.length} that have waited longest.` : ""}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-ps-label">
              <th scope="col" className="py-1 pr-3 font-medium">Client</th>
              <th scope="col" className="py-1 pr-3 font-medium">Challan</th>
              <th scope="col" className="py-1 pr-3 font-medium">Section</th>
              <th scope="col" className="py-1 pr-3 font-medium">Paid on</th>
              <th scope="col" className="py-1 pr-3 font-medium text-right">Amount</th>
              <th scope="col" className="py-1 pr-3 font-medium text-right">Waiting</th>
              <th scope="col" className="py-1 font-medium"><span className="sr-only">Open</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className="border-t border-state-attention-border/60">
                <td className="py-1 pr-3 text-ps-ink">{c.client_name ?? "A client"}</td>
                <td className="py-1 pr-3 font-mono">{c.challan_no ?? "—"}</td>
                <td className="py-1 pr-3">{c.section ?? "—"}</td>
                <td className="py-1 pr-3">{c.payment_date ? formatDate(c.payment_date) : "—"}</td>
                <td className="py-1 pr-3 text-right">{formatPaise(c.total_paise)}</td>
                <td className={`py-1 pr-3 text-right ${c.waiting_long ? "font-semibold text-state-problem" : ""}`}>
                  {c.days_since_payment === null ? "—" : `${c.days_since_payment} day${c.days_since_payment === 1 ? "" : "s"}`}
                  {c.waiting_long ? <span className="sr-only"> (over {longWaitDays} days)</span> : null}
                </td>
                <td className="py-1 text-right">
                  <button type="button" onClick={() => onOpenClient(c.client_id)}
                    aria-label={`Open ${c.client_name ?? "the client"}'s challans, ${c.challan_no ?? "challan"}`}
                    className="text-xs font-medium text-blue-700 underline">
                    Open
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
