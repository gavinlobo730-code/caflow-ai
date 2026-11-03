"use client";

/**
 * Documents whose stock was not all recorded (POST-A-092).
 *
 * A sales invoice, purchase bill, credit note or debit note moves stock AFTER it is issued, and a failure there never un-issues it: the
 * response that issued the document says so once. This panel is where the document is found again. The database counts (migration 579):
 * a document with goods lines owed and fewer stock rows than lines, or a stock row with a value and no journal behind it.
 *
 * THIS SCREEN DECIDES NOTHING. Which documents are listed, how many lines were owed and how many moved are the server's numbers, and the
 * result of "Complete the stock" is the server's own sentence, shown as it came: the server moves only the lines that did not move
 * (a line already recorded is never recorded twice), journals what has no journal, and REFUSES in words a line it cannot complete
 * exactly (one recorded while the item's stock was already below nil).
 *
 * A FAILED READ IS NOT AN EMPTY LIST. An empty panel means "every goods document has its stock", so a read that failed says so in one
 * line and renders no list; a list cut at the server's limit says how many more there are.
 */
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { api, type UnrecordedStock, type UnrecordedStockDocument } from "@/lib/api";
import { objectWithLists } from "@/lib/api/shape";
import { Button } from "@/components/ui/button";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { useSingleFlight } from "@/lib/async/useSingleFlight";
import { formatDate } from "@/lib/dates/format";

/** The words for the four kinds. The kinds themselves are the server's (`stock_effect.DOCUMENTS`); a test on the Python side holds the two lists equal. */
export const STOCK_DOCUMENT_WORDS: Record<UnrecordedStockDocument["kind"], string> = {
  sales_invoice: "Sales invoice",
  purchase_bill: "Purchase bill",
  credit_note: "Credit note",
  debit_note: "Debit note",
};

function whatIsMissing(d: UnrecordedStockDocument): string {
  const parts: string[] = [];
  if (d.moved_lines < d.owed_lines) {
    parts.push(`Stock recorded for ${d.moved_lines} of ${d.owed_lines} goods ${d.owed_lines === 1 ? "line" : "lines"}.`);
  }
  if (d.unjournalled_rows > 0) {
    parts.push(`${d.unjournalled_rows} stock ${d.unjournalled_rows === 1 ? "row has" : "rows have"} no journal behind ${d.unjournalled_rows === 1 ? "it" : "them"}.`);
  }
  return parts.join(" ");
}

export function UnrecordedStockPanel({ clientId }: { clientId: string }) {
  const [found, setFound] = useState<UnrecordedStock | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [said, setSaid] = useState<{ ok: boolean; text: string } | null>(null);
  // One flight for every button here: a second click while one retry is working is ignored on the same tick.
  const { flight } = useSingleFlight();

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      const r = await api.inventory.unrecordedStock(clientId);
      // `objectWithLists`, not `r.data`: `{}` is truthy and `.map` on a missing list would throw.
      const got = r.success ? objectWithLists<UnrecordedStock>(r.data, "documents") : null;
      setFound(got);
      setFailed(got === null);
    } catch {
      setFound(null);
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function complete(d: UnrecordedStockDocument) {
    // Asked every time: a document the CA has already put right by hand (a stock adjustment) is still listed here, because the list is
    // what the stock rows show, and completing it would take the goods out, or put them back, a second time.
    const sure = await confirmDialog({
      title: `Complete the stock for ${STOCK_DOCUMENT_WORDS[d.kind] ?? d.kind} ${d.reference || ""}?`.replace(/\s+\?$/, "?"),
      message: "This records the goods lines that have no stock row and journals what has no journal. If you have already adjusted this "
        + "stock by hand, do not continue: the goods would be taken out, or put back, a second time.",
      confirmLabel: "Complete the stock",
    });
    if (!sure) return;
    setBusy(d.document_id);
    setSaid(null);
    try {
      const r = await api.inventory.retryStockEffect({ client_id: clientId, kind: d.kind, document_id: d.document_id });
      if (r.success && r.data) setSaid({ ok: r.data.recorded !== false, text: r.data.message });  // null: no goods line, nothing to complete
      else setSaid({ ok: false, text: r.error || "The stock could not be completed. Nothing was changed." });
    } catch (e) {
      // A refusal (a cancelled document, a retry already running) is an HTTP error the client turns into an Error carrying the
      // server's own sentence: that sentence is the answer, and only a failure with no words of its own gets ours.
      setSaid({
        ok: false,
        text: e instanceof Error && e.message.trim() ? e.message : "The stock could not be completed just now. Try again in a moment.",
      });
    } finally {
      setBusy(null);
      await load();
    }
  }

  if (loading && !found) return null;
  if (failed || !found) {
    return (
      <p className="text-xs text-state-attention mb-4" role="alert">
        Couldn&apos;t check which documents have unrecorded stock. An empty panel here would have meant every goods document has its
        stock — this is not that.
      </p>
    );
  }
  if (found.documents.length === 0) {
    // The last one was just completed: say what the server said, once, and nothing else.
    return said ? (
      <p className={`text-xs mb-4 ${said.ok ? "text-ps-body" : "text-state-problem"}`} role={said.ok ? "status" : "alert"}>{said.text}</p>
    ) : null;
  }

  return (
    <section className="bg-ps-surface border border-ps-border rounded-xl overflow-hidden mb-4" aria-label="Documents whose stock was not all recorded">
      <div className="px-5 py-3 bg-ps-bg border-b border-ps-border flex items-center gap-2">
        <AlertTriangle size={14} className="text-state-attention" />
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-ps-ink text-sm">Documents whose stock was not all recorded</h3>
          <p className="text-xs text-ps-label">
            {found.total} {found.total === 1 ? "document is" : "documents are"} issued, with goods on {found.total === 1 ? "it" : "them"}, whose stock effect is incomplete
          </p>
        </div>
      </div>
      {said && (
        <p className={`px-5 py-2 text-xs border-b border-ps-border ${said.ok ? "text-ps-body" : "text-state-problem"}`} role={said.ok ? "status" : "alert"}>
          {said.text}
        </p>
      )}
      {found.documents.length > 0 && (
        <>
          <p className="px-5 pt-3 text-xs text-ps-body">
            Each document below is in the books and the return. Completing the stock moves only the lines that did not move and journals
            what has no journal; a line already recorded is never recorded twice. The server says in words when it cannot finish one.
          </p>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-ps-label border-b border-ps-border">
                <th className="text-left font-medium px-5 py-2">Document</th>
                <th className="text-left font-medium px-5 py-2">Dated</th>
                <th className="text-left font-medium px-5 py-2">What is missing</th>
                <th className="px-5 py-2"><span className="sr-only">Action</span></th>
              </tr>
            </thead>
            <tbody>
              {found.documents.map((d) => (
                <tr key={`${d.kind}-${d.document_id}`} className="border-b border-ps-border last:border-0 align-top">
                  <td className="px-5 py-2 text-ps-body">{STOCK_DOCUMENT_WORDS[d.kind] ?? d.kind} {d.reference || "—"}</td>
                  <td className="px-5 py-2 text-ps-body">{d.document_date ? formatDate(d.document_date) : "—"}</td>
                  <td className="px-5 py-2 text-xs text-ps-body">{whatIsMissing(d)}</td>
                  <td className="px-5 py-2 text-right">
                    <Button
                      variant="plain" size="none" spinner={false} flight={flight} type="button"
                      onClick={() => complete(d)}
                      disabled={busy !== null}
                      className="inline-flex items-center gap-1 rounded-lg border border-ps-border px-2 py-1 text-2xs hover:bg-ps-bg disabled:opacity-50"
                    >
                      {busy === d.document_id && <Loader2 size={12} className="animate-spin" />}
                      Complete the stock
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {found.total > found.documents.length && (
            <p className="px-5 py-2 text-xs text-ps-label">
              Showing the first {found.documents.length} of {found.total}. Complete these and the rest will follow.
            </p>
          )}
        </>
      )}
    </section>
  );
}
