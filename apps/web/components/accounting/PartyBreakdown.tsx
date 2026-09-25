"use client";

import { useCallback, useEffect, useState } from "react";
import { Users, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import type { PartyBreakdownPayload, PartyBreakdownRow } from "@/lib/api";
import { objectWithLists } from "@/lib/api/shape";
import { formatPaise } from "@/lib/services/formatting";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { DrCr } from "@/components/ui/drcr";
// THE one source-label deriver (ACC-22). Writing a second one here is
// exactly what `test_a_journal_source_reads_as_english` forbids, and it
// caught this file doing it — the docstring below already promised the
// browser would keep no second vocabulary of what a source means.
import { sourceLabel } from "@/lib/accounting/sourceDocument";

/**
 * WHO THIS CONTROL ACCOUNT IS OWED BY, OR OWED TO (ACC-13's other half).
 *
 * The ledger beside this names the DOCUMENT behind each row (ACC-22). This
 * names the PARTY behind the account: Trade Receivables showed one pooled
 * figure, and the per-customer view lived only on the separate Customer
 * Statement screen, so when the two disagreed nothing said WHICH entries were
 * the difference.
 *
 * ── THE UNATTRIBUTED ROWS ARE THE POINT, NOT A FOOTNOTE ───────────────────
 *
 * A manual journal, an opening balance, a trial-balance import, a year-end
 * adjustment and a bank line coded straight to the account name no party —
 * and together they are exactly the difference between this control account
 * and the sum of the party statements. So they are rendered as rows, one per
 * SOURCE KIND with its own sentence, never folded into an "Others" party that
 * does not exist. The server sends the sentences; this file holds no list of
 * source kinds — the short heading comes from `sourceLabel`, the one
 * deriver ACC-22 already established — because a second vocabulary in the
 * browser is how the Schedule III captions came to offer five the engine
 * had never heard of.
 *
 * ── IT DECIDES NOTHING ────────────────────────────────────────────────────
 *
 * Every figure, every sentence and the order of the rows come from the
 * server. `domain/accounting/party_ledger.py` is the authority and
 * `public.party_ledger_as_at` is what production runs; the two are pinned to
 * each other by tests/test_party_ledger_parity_pg.py.
 */
export function PartyBreakdown({
  clientId, accountId, accountName, asOf,
}: {
  clientId: string;
  accountId: string;
  accountName: string;
  asOf?: string;
}) {
  const [data, setData] = useState<PartyBreakdownPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder" || !accountId) {
      setData(null);
      return;
    }
    setLoading(true);
    try {
      const res = await api.accounting.ledgerParties({
        client_id: clientId, account_id: accountId, ...(asOf ? { as_of: asOf } : {}),
      });
      if (res.success && res.data) {
        setData(objectWithLists<PartyBreakdownPayload>(res.data, "rows", "notes"));
        setFailed(false);
      } else {
        setData(null);
        setFailed(true);
      }
    } catch {
      setData(null);
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId, accountId, asOf]);

  useEffect(() => { load(); }, [load]);

  if (failed) {
    return (
      <ErrorState
        title="Could not load the party breakdown"
        message={`The breakdown for ${accountName} could not be fetched. The ledger above is unaffected.`}
        onRetry={load}
      />
    );
  }
  if (loading && !data) {
    return <div className="p-4 text-sm text-ps-label">Loading the party breakdown…</div>;
  }
  const rows = data?.rows ?? [];
  if (!rows.length) {
    return (
      <EmptyState
        icon={<Users size={28} />}
        title="Nothing posted to this account yet"
        description={`${accountName} has no posted entries as at ${data?.as_of ?? "this date"}, so there is nobody to show.`}
      />
    );
  }

  const label = (r: PartyBreakdownRow) =>
    r.party_id ? r.party_name
      : r.unattributed_source ? sourceLabel(r.unattributed_source)
      : "No source document recorded";

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ps-ink">
          Who this balance is with
          {data?.as_of ? <span className="ml-2 font-normal text-ps-label">as at {data.as_of}</span> : null}
        </h3>
        <button
          onClick={load}
          className="inline-flex items-center gap-1.5 rounded-lg border border-ps-border px-2.5 py-1 text-xs text-ps-body transition-colors hover:bg-ps-hover"
        >
          <RefreshCw size={12} /> Refresh
        </button>
      </div>

      <div className="overflow-x-auto rounded-lg border border-ps-border">
        <table className="w-full text-sm">
          <thead className="bg-ps-muted text-left text-xs uppercase tracking-wide text-ps-label">
            <tr>
              <th className="px-3 py-2 font-medium">Party</th>
              <th className="px-3 py-2 font-medium">Kind</th>
              <th className="px-3 py-2 text-right font-medium">Debit</th>
              <th className="px-3 py-2 text-right font-medium">Credit</th>
              <th className="px-3 py-2 text-right font-medium">Balance</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr
                key={r.party_id ?? `un:${r.unattributed_source ?? i}`}
                className={`border-t border-ps-border ${r.party_id ? "" : "bg-ps-muted/40"}`}
              >
                <td className="px-3 py-2">
                  <div className="text-ps-body">{label(r)}</div>
                  {/* The server's own sentence, per source kind. Never a
                      generic one: a manual journal and an opening balance
                      send the CA to different places. */}
                  {r.unattributed_reason ? (
                    <div className="mt-0.5 text-xs text-ps-label">{r.unattributed_reason}</div>
                  ) : null}
                </td>
                <td className="px-3 py-2 text-xs text-ps-label">
                  {r.party_kind ?? "not attributed"}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-ps-body">
                  {r.debit_paise ? formatPaise(r.debit_paise) : "—"}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-ps-body">
                  {r.credit_paise ? formatPaise(r.credit_paise) : "—"}
                </td>
                <td className="px-3 py-2 text-right">
                  <DrCr paise={Math.abs(r.balance_paise)} isDebit={r.balance_paise >= 0} quiet />
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot className="border-t-2 border-ps-border bg-ps-muted text-sm">
            <tr>
              <td className="px-3 py-2 font-medium text-ps-ink" colSpan={4}>
                Attributed to a party
              </td>
              <td className="px-3 py-2 text-right">
                <DrCr
                  paise={Math.abs(data?.attributed_paise ?? 0)}
                  isDebit={(data?.attributed_paise ?? 0) >= 0}
                  quiet
                />
              </td>
            </tr>
            <tr>
              <td className="px-3 py-2 text-ps-body" colSpan={4}>Not attributed</td>
              <td className="px-3 py-2 text-right">
                <DrCr
                  paise={Math.abs(data?.unattributed_paise ?? 0)}
                  isDebit={(data?.unattributed_paise ?? 0) >= 0}
                  quiet
                />
              </td>
            </tr>
            <tr className="border-t border-ps-border">
              <td className="px-3 py-2 font-semibold text-ps-ink" colSpan={4}>
                Account balance
              </td>
              <td className="px-3 py-2 text-right font-semibold">
                <DrCr
                  paise={Math.abs(data?.total_paise ?? 0)}
                  isDebit={(data?.total_paise ?? 0) >= 0}
                />
              </td>
            </tr>
          </tfoot>
        </table>
      </div>

      {(data?.notes ?? []).map((n) => (
        <p key={n} className="text-xs text-ps-label">{n}</p>
      ))}
    </div>
  );
}
