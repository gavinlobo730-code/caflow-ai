"use client";

/**
 * The emails sent for one customer's statements, newest first.
 *
 * A CA who emails a statement used to get "sent" from the modal and nothing afterwards: the log the send path writes had no
 * reader, so a failed or bounced message was invisible. This reads `GET /api/customer-statements/deliveries` (a window of the
 * newest rows) and says, in order of what a person needs: that it is loading, that it could not be read (a different
 * statement from "nothing has been sent"), that nothing has been sent, or the rows with the window notice when older ones exist.
 */
import { useEffect, useState } from "react";
import { apiGet, getAuthToken } from "@/lib/invoices/shared";
import { formatDate, formatDateTime } from "@/lib/dates/format";
import { Callout } from "@/components/ui/callout";
import { EmptyState } from "@/components/ui/states";
import { ListWindowNotice } from "@/components/lists/ListWindowNotice";
import { windowDescription } from "@/lib/lists/window";
import {
  STATEMENT_DELIVERY_NOTE,
  deliveryStatusLabel,
  readStatementDeliveries,
  type StatementDelivery,
} from "@/lib/sales/statementDeliveries";

const INITIAL_LIMIT = 50;

const STATUS_TONE: Record<string, string> = {
  queued: "bg-ps-muted text-ps-label",
  sending: "bg-state-working-surface text-state-working",
  sent: "bg-state-ready-surface text-state-ready",
  failed: "bg-state-problem-surface text-state-problem",
  bounced: "bg-state-attention-surface text-state-attention",
};

type Loaded =
  | { kind: "loading" }
  | { kind: "unreadable" }
  | { kind: "ready"; rows: StatementDelivery[]; hasMore: boolean; limit: number; maxLimit: number };

export function StatementDeliveryLog({
  clientId, customerId, refreshKey,
}: { clientId: string; customerId: string; refreshKey: number }) {
  const [limit, setLimit] = useState(INITIAL_LIMIT);
  const [state, setState] = useState<Loaded>({ kind: "loading" });
  const [busy, setBusy] = useState(false);

  // A different customer starts again from the first window.
  useEffect(() => { setLimit(INITIAL_LIMIT); }, [customerId, clientId]);

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    (async () => {
      try {
        const token = await getAuthToken();
        const res = await apiGet(
          `/api/customer-statements/deliveries?client_id=${encodeURIComponent(clientId)}`
          + `&customer_id=${encodeURIComponent(customerId)}&limit=${limit}`,
          token,
        );
        if (cancelled) return;
        const window = res.success ? readStatementDeliveries(res.data, limit) : null;
        setState(window
          ? { kind: "ready", rows: window.rows, hasMore: window.hasMore, limit: window.limit, maxLimit: window.maxLimit }
          : { kind: "unreadable" });
      } catch {
        if (!cancelled) setState({ kind: "unreadable" });
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => { cancelled = true; };
  }, [clientId, customerId, limit, refreshKey]);

  return (
    <section className="bg-white rounded-xl border border-ps-border p-4" aria-label="Statement emails sent">
      <h3 className="text-sm font-semibold text-ps-ink">Emails sent for this customer</h3>
      {state.kind === "loading" && <p className="mt-2 text-xs text-ps-hint">Loading the delivery log…</p>}
      {state.kind === "unreadable" && (
        <Callout tone="problem" className="mt-2">The delivery log could not be loaded. This is not the same as nothing having been sent.</Callout>
      )}
      {state.kind === "ready" && state.rows.length === 0 && (
        <EmptyState
          className="py-6"
          title="No statement has been emailed to this customer yet"
          description="Generate the statement above and use Email to send it. Each send is recorded here, whether it worked or not."
        />
      )}
      {state.kind === "ready" && state.rows.length > 0 && (
        <>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-ps-label border-b border-ps-border">
                  <th className="py-1.5 pr-3 font-medium">Sent to</th>
                  <th className="py-1.5 pr-3 font-medium">Statement period</th>
                  <th className="py-1.5 pr-3 font-medium">Status</th>
                  <th className="py-1.5 pr-3 font-medium">When</th>
                  <th className="py-1.5 font-medium">By</th>
                </tr>
              </thead>
              <tbody>
                {state.rows.map((d) => (
                  <tr key={d.id} className="border-b border-ps-border last:border-0 align-top">
                    <td className="py-1.5 pr-3 text-ps-body">{d.sent_to}</td>
                    <td className="py-1.5 pr-3 text-ps-label">{formatDate(d.period_start)} → {formatDate(d.period_end)}</td>
                    <td className="py-1.5 pr-3">
                      <span className={`px-1.5 py-0.5 rounded-full text-3xs font-medium ${STATUS_TONE[d.status] ?? "bg-ps-muted text-ps-label"}`}>
                        {deliveryStatusLabel(d.status)}
                      </span>
                      {d.error_message && <p className="mt-1 text-3xs text-state-problem">{d.error_message}</p>}
                    </td>
                    <td className="py-1.5 pr-3 text-ps-label">{formatDateTime(d.sent_at ?? d.created_at)}</td>
                    <td className="py-1.5 text-ps-label">{d.sent_by_email ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-3xs text-ps-hint">{STATEMENT_DELIVERY_NOTE}</p>
          <ListWindowNotice
            hasMore={state.hasMore}
            what={windowDescription(state.rows.length, "emails", "latest")}
            limit={state.limit}
            maxLimit={state.maxLimit}
            onShowMore={(next) => setLimit(next)}
            busy={busy}
          />
        </>
      )}
    </section>
  );
}
