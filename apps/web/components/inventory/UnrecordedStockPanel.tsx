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
 *
 * A DOCUMENT THE CA ALREADY PUT RIGHT BY HAND IS MARKED, NOT COMPLETED (migration 620). The list shows what the stock rows show, so a document
 * corrected with a stock adjustment stayed listed. "Mark as settled" records the CA's own statement with the reason they type; the server then stops
 * listing the document and refuses to complete it, and the marked documents are listed below with who marked them and when, and a way to take the mark
 * off. Nothing is decided here: the reason is sent as typed, the sentences are the server's, and a failed read of the marks is said in words and never
 * drawn as "none are marked". Both buttons that write are offered only to someone the routes admit (accounting write).
 */
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { api, type StockSettlement, type UnrecordedStock, type UnrecordedStockDocument } from "@/lib/api";
import { objectWithLists } from "@/lib/api/shape";
import { usePermissions } from "@/lib/auth/AuthContext";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { Modal } from "@/components/ui/modal";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { useSingleFlight } from "@/lib/async/useSingleFlight";
import { usePermissions } from "@/lib/auth/AuthContext";
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
  // Completing a document's stock asks `accounting` `write`; reading what is missing asks `accounting` `read` (POST-A-455).
  const { can: canDo, resolved: permissionsRead } = usePermissions();
  const mayWriteBooks = canDo("accounting", "write");
  const [settled, setSettled] = useState<StockSettlement[] | null>(null);
  const [settledFailed, setSettledFailed] = useState(false);
  const [marking, setMarking] = useState<UnrecordedStockDocument | null>(null);
  const [reason, setReason] = useState("");
  const [markError, setMarkError] = useState("");
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

  // The marks are read apart from the list: a failed read of one says so about itself and never makes the other look empty.
  const loadSettled = useCallback(async () => {
    setSettledFailed(false);
    try {
      const r = await api.inventory.settledStock(clientId);
      const got = r.success ? objectWithLists<{ settlements: StockSettlement[] }>(r.data, "settlements") : null;
      setSettled(got ? got.settlements : null);
      setSettledFailed(got === null);
    } catch {
      setSettled(null);
      setSettledFailed(true);
    }
  }, [clientId]);

  useEffect(() => { load(); loadSettled(); }, [load, loadSettled]);

  function startMarking(d: UnrecordedStockDocument) {
    setMarking(d);
    setReason("");
    setMarkError("");
  }

  async function mark() {
    if (!marking) return;
    setBusy(marking.document_id);
    setMarkError("");
    try {
      const r = await api.inventory.settleStockEffect({ client_id: clientId, kind: marking.kind, document_id: marking.document_id, reason });
      if (r.success && r.data) {
        setSaid({ ok: true, text: r.data.message });
        setMarking(null);
      } else {
        setMarkError(r.error || "The document could not be marked just now. Nothing was changed.");
      }
    } catch (e) {
      // The server's own refusal (a document not on the list, one already marked, a reason that says nothing) is the answer.
      setMarkError(e instanceof Error && e.message.trim() ? e.message : "The document could not be marked just now. Nothing was changed.");
    } finally {
      setBusy(null);
      await Promise.all([load(), loadSettled()]);
    }
  }

  async function takeOff(m: StockSettlement) {
    const sure = await confirmDialog({
      title: "Take the mark off?",
      message: "The document is listed again if its stock is still not all recorded, and Complete the stock is offered for it again. If you put its stock "
        + "right by hand, do not complete it.",
      confirmLabel: "Take the mark off",
    });
    if (!sure) return;
    setBusy(m.id);
    setSaid(null);
    try {
      const r = await api.inventory.unsettleStockEffect(m.id);
      setSaid(r.success && r.data ? { ok: true, text: r.data.message } : { ok: false, text: r.error || "The mark could not be taken off just now. Nothing was changed." });
    } catch (e) {
      setSaid({ ok: false, text: e instanceof Error && e.message.trim() ? e.message : "The mark could not be taken off just now. Nothing was changed." });
    } finally {
      setBusy(null);
      await Promise.all([load(), loadSettled()]);
    }
  }

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

  /** The documents marked as settled by hand, with who marked them and when, and the way to take a mark off; or the sentence that they could not be read. */
  function marksSection() {
    if (settledFailed) {
      return (
        <p className="text-xs text-state-attention mb-4" role="alert">
          Couldn&apos;t read the documents marked as settled by hand. An empty list here would have meant none are marked — this is not that.
        </p>
      );
    }
    if (!settled || settled.length === 0) return null;
    return (
      <details className="bg-ps-surface border border-ps-border rounded-xl overflow-hidden mb-4">
        <summary className="px-5 py-3 text-sm font-semibold text-ps-ink cursor-pointer">
          Marked as settled by hand ({settled.length})
        </summary>
        <p className="px-5 pb-2 text-xs text-ps-label">
          You put these documents&apos; stock right yourself, so they are not listed above and Complete the stock will not move their goods. The mark records
          what you said; it can be taken off.
        </p>
        <div role="region" aria-label="Documents marked as settled by hand" tabIndex={0}
          className="overflow-x-auto focus:outline-none focus-visible:ring-2 focus-visible:ring-brand">
          <table className="w-full text-sm">
            <caption className="sr-only">Documents marked as settled by hand</caption>
            <thead>
              <tr className="text-xs text-ps-label border-y border-ps-border">
                <th scope="col" className="text-left font-medium px-5 py-2">Document</th>
                <th scope="col" className="text-left font-medium px-5 py-2">Dated</th>
                <th scope="col" className="text-left font-medium px-5 py-2">What was done</th>
                <th scope="col" className="text-left font-medium px-5 py-2">Marked by</th>
                <th scope="col" className="px-5 py-2"><span className="sr-only">Action</span></th>
              </tr>
            </thead>
            <tbody>
              {settled.map((m) => (
                <tr key={m.id} className="border-b border-ps-border last:border-0 align-top">
                  <td className="px-5 py-2 text-ps-body">{STOCK_DOCUMENT_WORDS[m.document_kind] ?? m.document_kind} {m.reference || "—"}</td>
                  <td className="px-5 py-2 text-ps-body whitespace-nowrap">{m.document_date ? formatDate(m.document_date) : "—"}</td>
                  <td className="px-5 py-2 text-xs text-ps-body">{m.reason}</td>
                  <td className="px-5 py-2 text-xs text-ps-body whitespace-nowrap">{m.settled_by_name || "—"} · {formatDate(m.settled_at)}</td>
                  <td className="px-5 py-2 text-right whitespace-nowrap">
                    {mayWriteBooks && (
                      <Button
                        variant="plain" size="none" spinner={false} flight={flight} type="button"
                        onClick={() => takeOff(m)}
                        disabled={busy !== null}
                        className="inline-flex items-center gap-1 rounded-lg border border-ps-border px-2 py-1 text-2xs hover:bg-ps-bg disabled:opacity-50"
                      >
                        {busy === m.id && <Loader2 size={12} className="animate-spin" />}
                        Take the mark off
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    );
  }

  /** The question a mark asks: what did the CA do to put the stock right. The reason is sent as typed and the server judges it. */
  function markDialog() {
    if (!marking) return null;
    const saving = busy === marking.document_id;
    const name = `${STOCK_DOCUMENT_WORDS[marking.kind] ?? marking.kind}${marking.reference ? ` ${marking.reference}` : ""}`;
    return (
      <Modal
        title={`Mark ${name} as settled by hand`}
        note="Use this when you have already put this document's stock right yourself, for example with a stock adjustment. The document leaves the list and Complete the stock will not move its goods. Nothing in the books or the stock is changed: the mark records what you say, with who and when, and can be taken off."
        maxWidthClass="max-w-lg"
        onClose={saving ? () => {} : () => setMarking(null)}
        footer={
          <>
            <button type="button" onClick={() => setMarking(null)} disabled={saving}
              className="text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg disabled:opacity-50">Cancel</button>
            {mayWriteBooks && (
              <Button variant="plain" size="none" type="button" spinner={false} flight={flight} onClick={mark} disabled={saving}
                className="text-xs px-3.5 py-1.5 bg-brand text-white rounded-lg hover:bg-brand-dark disabled:opacity-50 inline-flex items-center gap-1.5">
                {saving && <Loader2 size={12} className="animate-spin" />} Mark as settled
              </Button>
            )}
          </>
        }
      >
        <label htmlFor="stock-settle-reason" className="block text-xs font-medium text-ps-label mb-1">What did you do to put it right? *</label>
        <textarea id="stock-settle-reason" rows={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)}
          placeholder="For example: adjusted 4 units out on 12 April, reference ADJ-12"
          className="w-full px-3 py-1.5 text-xs border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand" />
        {markError && <Callout tone="problem">{markError}</Callout>}
      </Modal>
    );
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
    // The last one was just completed or marked: say what the server said, once, and then the marks if there are any (or that they could not be read).
    const marks = marksSection();
    if (!said && !marks) return null;
    return (
      <>
        {said && <p className={`text-xs mb-4 ${said.ok ? "text-ps-body" : "text-state-problem"}`} role={said.ok ? "status" : "alert"}>{said.text}</p>}
        {marks}
      </>
    );
  }

  return (
    <>
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
            {permissionsRead && !mayWriteBooks && " Completing a document's stock needs write access to the books, so the button is not shown to you."}
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
                  <td className="px-5 py-2 text-right whitespace-nowrap">
                    {mayWriteBooks && (
                      <>
                        <Button
                          variant="plain" size="none" spinner={false} flight={flight} type="button"
                          onClick={() => complete(d)}
                          disabled={busy !== null}
                          className="inline-flex items-center gap-1 rounded-lg border border-ps-border px-2 py-1 text-2xs hover:bg-ps-bg disabled:opacity-50"
                        >
                          {busy === d.document_id && <Loader2 size={12} className="animate-spin" />}
                          Complete the stock
                        </Button>
                        {/* The other way a listed document is dealt with: the CA already put its stock right by hand. */}
                        <Button
                          variant="plain" size="none" spinner={false} flight={flight} type="button"
                          onClick={() => startMarking(d)}
                          disabled={busy !== null}
                          className="ml-2 inline-flex items-center gap-1 rounded-lg border border-ps-border px-2 py-1 text-2xs hover:bg-ps-bg disabled:opacity-50"
                        >
                          Mark as settled
                        </Button>
                      </>
                    )}
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
    {marksSection()}
    {markDialog()}
    </>
  );
}
