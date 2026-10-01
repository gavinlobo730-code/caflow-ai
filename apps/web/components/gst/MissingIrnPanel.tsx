"use client";

/**
 * Invoices that need an IRN and have none (GST-20).
 *
 * CGST Rule 48(5): an invoice Rule 48(4) reaches, issued without an IRN, is not
 * treated as an invoice at all — so the RECIPIENT's input credit goes with it.
 * `irn_scope` has decided that for the one invoice somebody has open; nothing
 * listed the invoices that need one and have none, across a client or a
 * practice, and nothing counted a day against the IRP's thirty-day limit for
 * turnover of ₹10 crore and over.
 *
 * THIS SCREEN DECIDES NOTHING. Which invoices are listed, which of the five
 * window states each is in, how many days are left, which clients could not be
 * assessed and every caveat are the server's. The window's figures are
 * [S]-graded there and the sentence saying so is rendered here, not omitted.
 *
 * IT IS PREPARE-ONLY. The IRN is obtained on the IRP by a human and RECORDED
 * afterwards; nothing here generates one or reaches a portal.
 *
 * A FAILED READ IS NOT AN EMPTY LIST. This panel's emptiness means "all clear",
 * which makes a silent failure a false clean result — so a failure is said, in
 * one line, where an empty answer renders nothing.
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Clock, FileWarning } from "lucide-react";
import { api, type IrnWorklist } from "@/lib/api";
import { objectWithLists } from "@/lib/api/shape";
import { StatutoryNotes } from "@/components/ui/callout";
import { formatPaise } from "@/lib/money/format";
import { documentTarget } from "@/lib/accounting/sourceDocument";
import { irnStateText, windowText, windowTone } from "@/lib/gst/irnWorklist";

const TONE_CLASS = {
  problem: "text-state-problem",
  attention: "text-state-attention",
  neutral: "text-ps-body",
} as const;

export function MissingIrnPanel({ clientId }: { clientId?: string | null }) {
  const [list, setList] = useState<IrnWorklist | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      const r = await api.einvoice.missingIrn(clientId ?? null);
      // `objectWithLists`, not `r.data`: `{}` is truthy and `.map` on a missing
      // `invoices` would throw — which is how two panels crashed the smoke walk.
      const got = r.success
        ? objectWithLists<IrnWorklist>(r.data, "invoices", "caveats", "clients_not_assessed")
        : null;
      setList(got);
      setFailed(got === null);
    } catch {
      setList(null);
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return null;
  if (failed || !list) {
    return (
      <p className="text-xs text-state-attention mb-4" role="alert">
        Couldn&apos;t check which invoices still need an IRN. An empty panel
        here would have meant none do — this is not that.
      </p>
    );
  }

  const rows = list.invoices;
  const notAssessed = list.clients_not_assessed;
  if (rows.length === 0 && notAssessed.length === 0) return null;
  const counts = list.counts ?? {};
  const firm = list.scope === "firm";

  return (
    <section className="bg-ps-surface border border-ps-border rounded-xl overflow-hidden mb-6">
      <div className="px-5 py-3 bg-ps-bg border-b border-ps-border flex items-center gap-2">
        <FileWarning size={14} className="text-ps-label" />
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-ps-ink text-sm">
            Invoices that need an IRN and have none
          </h3>
          <p className="text-xs text-ps-label">
            {(counts.past_window ?? 0) > 0 && <>{counts.past_window} past the IRP limit · </>}
            {(counts.last_day ?? 0) > 0 && <>{counts.last_day} on the last day · </>}
            {(counts.within_window ?? 0) > 0 && <>{counts.within_window} within the window · </>}
            {(counts.no_reporting_limit ?? 0) > 0 && <>{counts.no_reporting_limit} with no IRP limit · </>}
            dated since {list.listed_since} · as at {list.as_of}
          </p>
        </div>
      </div>

      {rows.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-ps-label border-b border-ps-border">
              <th className="text-left font-medium px-5 py-2">Invoice</th>
              {firm && <th className="text-left font-medium px-5 py-2">Client</th>}
              <th className="text-left font-medium px-5 py-2">Customer</th>
              <th className="text-left font-medium px-5 py-2">Dated</th>
              <th className="text-right font-medium px-5 py-2">Value</th>
              <th className="text-left font-medium px-5 py-2">IRN</th>
              <th className="text-left font-medium px-5 py-2">Window</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const target = documentTarget(r.client_id, {
                entry_id: "", source_type: "sales_invoice", source_id: r.invoice_id,
              });
              return (
                <tr key={r.invoice_id} className="border-b border-ps-border last:border-0 align-top">
                  <td className="px-5 py-2">
                    {target
                      ? <Link href={target.href} className="text-brand hover:underline">{r.invoice_no || "—"}</Link>
                      : (r.invoice_no || "—")}
                  </td>
                  {firm && <td className="px-5 py-2 text-ps-body">{r.client_name || "—"}</td>}
                  <td className="px-5 py-2 text-ps-body">{r.customer_name || "—"}</td>
                  <td className="px-5 py-2 text-ps-body">{r.invoice_date}</td>
                  <td className="px-5 py-2 text-right font-mono tabular-nums text-ps-body">
                    {formatPaise(r.total_paise)}
                  </td>
                  <td className="px-5 py-2 text-xs text-ps-label">{irnStateText(r.irn_state)}</td>
                  <td className="px-5 py-2">
                    <span className={`inline-flex items-center gap-1 text-xs ${TONE_CLASS[windowTone(r.window)]}`}>
                      {r.window.status === "past_window"
                        ? <AlertTriangle size={11} /> : <Clock size={11} />}
                      {windowText(r.window)}
                    </span>
                    {r.turnover_unknown && (
                      <p className="text-xs text-ps-hint mt-0.5">
                        No aggregate turnover is recorded for this client.
                      </p>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {list.truncated && (
        <p className="px-5 py-2 text-xs text-ps-hint border-t border-ps-border">
          The list is cut at its first rows, oldest first; the counts above are
          over every invoice found.
        </p>
      )}

      {notAssessed.length > 0 && (
        <div className="px-5 py-3 border-t border-ps-border space-y-1">
          <p className="text-xs font-medium text-state-attention">
            {notAssessed.length} {notAssessed.length === 1 ? "client has" : "clients have"} no
            recorded aggregate turnover and could not be assessed
          </p>
          <ul className="text-xs text-ps-body list-disc pl-4">
            {notAssessed.map((c) => (
              <li key={c.client_id}>
                <Link href={`/clients/${c.client_id}`} className="text-brand hover:underline">
                  {c.client_name || c.client_id}
                </Link>
              </li>
            ))}
          </ul>
          <p className="text-xs text-ps-hint">{notAssessed[0]?.reason}</p>
        </div>
      )}

      <div className="px-5 py-3 border-t border-ps-border bg-ps-bg space-y-1">
        {/* PREPARE-ONLY, said where the list is. The IRN is obtained on the IRP
            by a human and recorded here afterwards. */}
        <p className="text-xs text-ps-hint">
          PracticeSync does not reach the IRP. Obtain the IRN there, then record it
          against the invoice on the e-Invoice screen.
        </p>
      </div>
      {/* The server's caveats, in the shared component: "read this once" is a
          different thing from a gap's "go and record this", and one component
          is what keeps the two inks apart. */}
      <StatutoryNotes caveats={list.caveats} className="px-5 pb-3 pt-2 bg-ps-bg" />
    </section>
  );
}
