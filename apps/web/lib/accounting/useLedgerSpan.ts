"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { LedgerSpan } from "@/lib/dates/periods";

/**
 * The client's real posted-ledger bounds, for resolving "All Time".
 *
 * Returns null until it has loaded AND while the ledger is genuinely empty —
 * both mean "cannot split All Time into columns", which is the only decision
 * the caller makes with this. Distinguishing "still loading" from "no entries"
 * would buy a spinner on a control that is already usable, so it is deliberately
 * collapsed; periodSplitNotice() explains the empty case to the user.
 *
 * A failure is also null. If this request breaks, All Time falls back to the
 * single-column behaviour it has always had — a report that is coarser than
 * asked for, never one that is wrong.
 */
export function useLedgerSpan(clientId: string | null | undefined): LedgerSpan {
  const [span, setSpan] = useState<LedgerSpan>(null);

  useEffect(() => {
    if (!clientId || clientId === "_placeholder") {
      setSpan(null);
      return;
    }
    let cancelled = false;

    (async () => {
      try {
        const res = (await api.accounting.ledgerSpan({ client_id: clientId })) as {
          success: boolean;
          data: { first_entry_date: string | null; last_entry_date: string | null } | null;
        };
        const first = res?.data?.first_entry_date;
        const last = res?.data?.last_entry_date;
        // Both halves required: a start without an end is not a range, and
        // letting one through would silently truncate every split column.
        if (!cancelled) setSpan(res?.success && first && last ? { first, last } : null);
      } catch {
        if (!cancelled) setSpan(null);
      }
    })();

    // Guards against a stale response for a PREVIOUS client landing after the
    // user has switched — which would split this client's report across
    // another client's dates.
    return () => { cancelled = true; };
  }, [clientId]);

  return span;
}
