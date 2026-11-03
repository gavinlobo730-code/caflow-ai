"use client";

/**
 * Invoices the ledger and the invoice list disagree about (POST-A-092).
 *
 * TWO DIRECTIONS, ONE PANEL.
 *   * A DRAFT that already has a live Sales entry in the ledger: its revenue and output tax are in the books and the customer's balance,
 *     while the invoice list, the receipts screen and GSTR-1 do not count it. Issuing is one database transaction since migration 577, so
 *     an issue cannot leave this behind; an issue made before it could can, and so can a draft edited after a failed issue.
 *   * An ISSUED invoice with no ledger entry linked: counted by the invoice list and absent from the books.
 *
 * THIS SCREEN DECIDES NOTHING. Which invoices are listed, which entry stands behind each draft and what stands in the way of finishing
 * it are the server's answers, rendered in its own sentences. Finishing a draft is the ordinary Issue on the invoice (the server
 * reuses the entry only if it carries the very figures the draft has, and refuses in words if not); posting the entry of an issued
 * invoice is the server's repost, which asks the locked year first.
 *
 * A FAILED READ IS NOT AN EMPTY LIST. An empty panel here means "the books and the list agree", which makes a silent failure a false
 * clean result, so a failure is said in one line. Past the server's limit a draft is listed UNCHECKED and says so; "nothing in the
 * way" (an empty list) and "not asked" (null) are two statements.
 */
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { api, type PostedDraftRow, type PostedDrafts, type UnpostedInvoiceRow } from "@/lib/api";
import { objectWithLists } from "@/lib/api/shape";
import { Button } from "@/components/ui/button";
import { useSingleFlight } from "@/lib/async/useSingleFlight";
import { formatPaise } from "@/lib/money/format";
import { formatDate } from "@/lib/dates/format";

type Unposted = { unposted: UnpostedInvoiceRow[]; count: number };

export function UnfinishedInvoicesPanel({
  clientId, onOpenInvoice,
}: { clientId: string; onOpenInvoice: (invoiceId: string) => void }) {
  const [drafts, setDrafts] = useState<PostedDrafts | null>(null);
  const [unposted, setUnposted] = useState<Unposted | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [said, setSaid] = useState<string | null>(null);
  // One flight for every button here: a second click while one repost is working is ignored on the same tick.
  const { flight } = useSingleFlight();

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      const [a, b] = await Promise.all([api.salesInvoices.postedDrafts(clientId), api.salesInvoices.unposted(clientId)]);
      // `objectWithLists`, not `r.data`: `{}` is truthy and `.map` on a missing list would throw.
      const gotDrafts = a.success ? objectWithLists<PostedDrafts>(a.data, "drafts") : null;
      const gotUnposted = b.success ? objectWithLists<Unposted>(b.data, "unposted") : null;
      setDrafts(gotDrafts);
      setUnposted(gotUnposted);
      setFailed(gotDrafts === null || gotUnposted === null);
    } catch {
      setDrafts(null);
      setUnposted(null);
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function repost(invoiceId: string) {
    setBusy(invoiceId);
    setSaid(null);
    try {
      const r = await api.salesInvoices.repostJournal(invoiceId);
      if (!r.success) setSaid(r.error || "The entry could not be posted. Nothing was changed.");
    } catch {
      setSaid("The entry could not be posted just now. Nothing was changed. Try again in a moment.");
    } finally {
      setBusy(null);
      await load();
    }
  }

  if (loading) return null;
  if (failed || !drafts || !unposted) {
    return (
      <p className="text-xs text-state-attention mb-4" role="alert">
        Couldn&apos;t check whether the ledger and the invoice list agree. An empty panel here would have meant they do —
        this is not that.
      </p>
    );
  }
  if (drafts.drafts.length === 0 && unposted.unposted.length === 0) return null;

  return (
    <section className="bg-ps-surface border border-ps-border rounded-xl overflow-hidden mb-6" aria-label="Invoices the ledger and the list disagree about">
      <div className="px-5 py-3 bg-ps-bg border-b border-ps-border flex items-center gap-2">
        <AlertTriangle size={14} className="text-state-attention" />
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-ps-ink text-sm">Invoices the ledger and the invoice list disagree about</h3>
          <p className="text-xs text-ps-label">
            {drafts.count} draft{drafts.count === 1 ? "" : "s"} already in the ledger · {unposted.count} issued without a ledger entry
          </p>
        </div>
      </div>
      {said && <p className="px-5 py-2 text-xs text-state-problem border-b border-ps-border" role="alert">{said}</p>}

      {drafts.drafts.length > 0 && (
        <div>
          <p className="px-5 pt-3 text-xs text-ps-body">
            These drafts have their revenue and tax in the ledger already. Issuing a draft again finishes it when the entry carries the
            very figures the draft has; the server says so in words when it does not.
          </p>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-ps-label border-b border-ps-border">
                <th className="text-left font-medium px-5 py-2">Draft</th>
                <th className="text-left font-medium px-5 py-2">Dated</th>
                <th className="text-right font-medium px-5 py-2">Value</th>
                <th className="text-left font-medium px-5 py-2">Entry in the ledger</th>
                <th className="text-left font-medium px-5 py-2">What stands in the way</th>
              </tr>
            </thead>
            <tbody>
              {drafts.drafts.map((d: PostedDraftRow) => (
                <tr key={d.invoice_id} className="border-b border-ps-border last:border-0 align-top">
                  <td className="px-5 py-2">
                    <button type="button" className="text-brand hover:underline" onClick={() => onOpenInvoice(d.invoice_id)}>
                      {d.invoice_no || "—"}
                    </button>
                  </td>
                  <td className="px-5 py-2 text-ps-body">{formatDate(d.invoice_date)}</td>
                  <td className="px-5 py-2 text-right font-mono tabular-nums text-ps-body">{formatPaise(d.total_paise)}</td>
                  <td className="px-5 py-2 text-ps-body">
                    {d.entry_reference_no || "—"}{d.entry_date ? ` · ${formatDate(d.entry_date)}` : ""}
                  </td>
                  <td className="px-5 py-2 text-xs">
                    {d.blockers === null
                      ? <span className="text-ps-label">Not checked: the list is long. Open the draft to see.</span>
                      : d.blockers.length === 0
                        ? <span className="text-ps-body">Nothing. Open the draft and press Issue to finish it.</span>
                        : <span className="text-state-attention">{d.blockers.map((b) => b.message).join(" ")}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {drafts.not_checked > 0 && (
            <p className="px-5 py-2 text-xs text-ps-label">
              {drafts.not_checked} more {drafts.not_checked === 1 ? "draft is" : "drafts are"} listed without the check.
            </p>
          )}
        </div>
      )}

      {unposted.unposted.length > 0 && (
        <div className={drafts.drafts.length > 0 ? "border-t border-ps-border" : ""}>
          <p className="px-5 pt-3 text-xs text-ps-body">
            These invoices are issued and counted in the invoice list, but no ledger entry is linked to them. Posting the entry puts
            their revenue and tax in the books; the server refuses in words if the year is locked.
          </p>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-ps-label border-b border-ps-border">
                <th className="text-left font-medium px-5 py-2">Invoice</th>
                <th className="text-left font-medium px-5 py-2">Dated</th>
                <th className="text-right font-medium px-5 py-2">Value</th>
                <th className="px-5 py-2"><span className="sr-only">Action</span></th>
              </tr>
            </thead>
            <tbody>
              {unposted.unposted.map((u: UnpostedInvoiceRow) => (
                <tr key={u.id} className="border-b border-ps-border last:border-0 align-top">
                  <td className="px-5 py-2">
                    <button type="button" className="text-brand hover:underline" onClick={() => onOpenInvoice(u.id)}>
                      {u.invoice_no || "—"}
                    </button>
                  </td>
                  <td className="px-5 py-2 text-ps-body">{formatDate(u.invoice_date)}</td>
                  <td className="px-5 py-2 text-right font-mono tabular-nums text-ps-body">{formatPaise(u.total_paise)}</td>
                  <td className="px-5 py-2 text-right">
                    <Button
                      variant="plain" size="none" spinner={false} flight={flight} type="button"
                      onClick={() => repost(u.id)}
                      disabled={busy !== null}
                      className="inline-flex items-center gap-1 rounded-lg border border-ps-border px-2 py-1 text-2xs hover:bg-ps-bg disabled:opacity-50"
                    >
                      {busy === u.id && <Loader2 size={12} className="animate-spin" />}
                      Post the entry
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
