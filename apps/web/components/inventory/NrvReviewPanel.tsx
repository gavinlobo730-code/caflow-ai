"use client";

/**
 * The NRV review — one sheet for the whole register, posted as one batch (POST-A-111, the rest of INV-10).
 *
 * The write-down to net realisable value took one item per modal. A year-end valuation reviews the whole register: the CA reads each
 * item's quantity and carrying value, decides which have fallen below cost, and types the NRV they estimated for those.
 *
 * THIS SCREEN ESTIMATES NOTHING AND COMPUTES NOTHING. The NRV box starts empty for every item and is never filled from the average
 * cost, a selling price or anything else: NRV is the CA's judgement (AS 2). What a typed NRV writes down and the value after are the
 * server's, from the function the posting runs (`domain/inventory/nrv_review.py`), asked again with "Work out the write-downs"; a
 * figure is shown on a row only while the row's box still holds the value the server answered for. The batch posts through the
 * single-item door's function, one line at a time, in parts of `NRV_REVIEW_PART` so no request outlives the browser's wait, and the
 * server's own sentence says what it did. Posting the same sheet again writes down only what is still above the value entered.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { api, type NrvReviewItem, type NrvReviewPostResult, type NrvReviewSheet } from "@/lib/api";
import { objectWithLists } from "@/lib/api/shape";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { formatPaise } from "@/lib/money/format";
import { usePermissions } from "@/lib/auth/AuthContext";
import { useSingleFlight } from "@/lib/async/useSingleFlight";
import { useDateProblems } from "@/lib/dates/useDateProblems";
import { todayIstISO } from "@/lib/dates/format";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { DateInput } from "@/components/ui/date-input";
import { confirmDialog } from "@/components/ui/confirm-dialog";

/** How many lines one request carries. The server takes up to 100 (`nrv_review.MAX_LINES`); each line is several round trips when
 *  it posts, so a sheet is sent in parts that each finish well inside the browser's wait. */
export const NRV_REVIEW_PART = 25;

type Line = { service_catalogue_id: string; nrv_per_unit_paise: number };

/** What the box holds: blank (not entered), an amount in paise, or text that is not an amount. Read through the one parser. */
function readBox(text: string | undefined): { kind: "blank" } | { kind: "amount"; paise: number } | { kind: "bad" } {
  const t = (text ?? "").trim();
  if (t === "") return { kind: "blank" };
  const paise = paiseFromRupeeInput(t.replace(/[,\s₹]/g, ""));
  return paise === null || paise < 0 ? { kind: "bad" } : { kind: "amount", paise };
}

const STATUS_WORDS: Record<NrvReviewItem["status"], string> = {
  not_entered: "",
  write_down: "",
  not_below_carrying_value: "Not below the carrying value: nothing to write down.",
  no_stock: "Holds no stock: nothing to write down.",
};

export function NrvReviewPanel({ clientId, onClose, onPosted }: { clientId: string; onClose: () => void; onPosted: () => void }) {
  const { can } = usePermissions();
  // The route the batch posts to is `rbac("accounting", "write")`; the sheet itself is a read, and whoever may not write sees no Post.
  const canPost = can("accounting", "write");
  const [sheet, setSheet] = useState<NrvReviewSheet | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [typed, setTyped] = useState<Record<string, string>>({});
  const [date, setDate] = useState(todayIstISO());
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [posting, setPosting] = useState(false);
  const [results, setResults] = useState<NrvReviewPostResult[]>([]);
  const dates = useDateProblems();
  const { flight } = useSingleFlight();

  const boxes = useMemo(() => {
    const out: Record<string, ReturnType<typeof readBox>> = {};
    for (const [id, text] of Object.entries(typed)) out[id] = readBox(text);
    return out;
  }, [typed]);
  const lines: Line[] = useMemo(
    () => Object.entries(boxes).flatMap(([id, b]) => (b.kind === "amount" ? [{ service_catalogue_id: id, nrv_per_unit_paise: b.paise }] : [])),
    [boxes],
  );
  const badCount = Object.values(boxes).filter((b) => b.kind === "bad").length;

  const ask = useCallback(async (asked: Line[]) => {
    setLoading(true);
    try {
      const res = await api.inventory.nrvReview({ client_id: clientId, lines: asked });
      const got = res.success ? objectWithLists<NrvReviewSheet>(res.data, "items") : null;
      if (!got) throw new Error(res.error || "The NRV review could not be loaded.");
      setSheet(got);
      setLoadError("");
    } catch (e) {
      setLoadError(e instanceof Error && e.message.trim() ? e.message : "The NRV review could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { ask([]); }, [ask]);

  /** The server's answer for a row counts only while the box still holds the value the server answered for. */
  function fresh(row: NrvReviewItem): boolean {
    const b = boxes[row.service_catalogue_id] ?? { kind: "blank" as const };
    if (b.kind === "bad") return false;
    return (b.kind === "amount" ? b.paise : null) === row.nrv_per_unit_paise;
  }
  const rows = sheet?.items ?? [];
  const typedOffSheet = lines.filter((l) => !rows.some((r) => r.service_catalogue_id === l.service_catalogue_id));
  const sheetIsCurrent = !!sheet && rows.every(fresh) && typedOffSheet.length === 0;

  async function post() {
    if (!sheet || !canPost) return;
    if (dates.first) { dates.refuseWith(setError); return; }
    if (badCount) { setError("A box holds text that is not an amount. Enter rupees per unit, like 120 or 120.50, or clear it."); return; }
    if (!lines.length) { setError("Enter a net realisable value for at least one item."); return; }
    if (!sheetIsCurrent) { setError("A value changed since the write-downs were worked out. Work them out again before posting."); return; }
    const sure = await confirmDialog({
      title: "Post these write-downs?",
      message: `${sheet.write_down_count} ${sheet.write_down_count === 1 ? "item is" : "items are"} written down to the value you entered, `
        + `${formatPaise(sheet.write_down_paise)} in all, dated ${date}. `
        + `${lines.length - sheet.write_down_count} other ${lines.length - sheet.write_down_count === 1 ? "line is" : "lines are"} left as `
        + "they are and recorded as reviewed. Each write-down is its own journal: Dr the write-down expense, Cr Inventory.",
      confirmLabel: "Post write-downs",
    });
    if (!sure) return;
    setPosting(true);
    setError(null);
    const answers: NrvReviewPostResult[] = [];
    try {
      for (let at = 0; at < lines.length; at += NRV_REVIEW_PART) {
        const res = await api.inventory.postNrvReview({
          client_id: clientId, writedown_date: date, lines: lines.slice(at, at + NRV_REVIEW_PART),
          reference_no: reference.trim() || undefined, notes: notes.trim() || undefined,
        });
        const got = res.success ? objectWithLists<NrvReviewPostResult>(res.data, "posted", "not_needed", "failed") : null;
        if (!got) throw new Error(res.error || "The write-downs could not be posted.");
        answers.push(got);
      }
      setTyped({});
    } catch (e) {
      setError(
        (e instanceof Error && e.message.trim() ? e.message : "The write-downs could not be posted just now.")
        + (answers.length ? " The part already posted is listed below; posting the same sheet again writes down only what is still above the value entered." : ""),
      );
    } finally {
      setResults(answers);
      setPosting(false);
      if (answers.length) onPosted();
      await ask([]);
    }
  }

  const footer = (
    <>
      <Button variant="plain" size="none" type="button" onClick={onClose} disabled={posting}
        className="text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg disabled:opacity-50">
        Close
      </Button>
      <Button variant="plain" size="none" type="button" spinner={false} flight={flight}
        onClick={() => ask(lines)} disabled={loading || posting || badCount > 0}
        className="text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg disabled:opacity-50">
        Work out the write-downs
      </Button>
      {canPost && (
        <Button variant="plain" size="none" type="button" spinner={false} flight={flight}
          onClick={post} disabled={posting || loading || !lines.length || !sheetIsCurrent}
          className="text-xs px-3.5 py-1.5 bg-brand text-white rounded-lg hover:bg-brand-dark disabled:opacity-50 inline-flex items-center gap-1.5">
          {posting && <Loader2 size={12} className="animate-spin" />} Post write-downs
        </Button>
      )}
    </>
  );

  return (
    <Modal title="NRV review — write stock down to net realisable value" onClose={posting ? () => {} : onClose}
      maxWidthClass="max-w-5xl" footer={footer}
      note={sheet ? <>{sheet.no_nrv_of_our_own} {sheet.measured_now}</> : undefined}>
      {loadError && <Callout tone="problem">{loadError}</Callout>}
      {error && <Callout tone="problem">{error}</Callout>}
      {results.map((r, i) => (
        <div key={i} role="status" className="rounded-lg border border-ps-border bg-ps-bg px-3 py-2 text-xs text-ps-body space-y-1">
          <p>{r.message}</p>
          {r.failed.map((f) => <p key={f.service_catalogue_id} className="text-state-problem">{f.name}: {f.why}</p>)}
          {r.posted.filter((p) => p.journal_posted === false).map((p) => (
            <p key={p.service_catalogue_id} className="text-state-attention">{p.name}: written down with no journal behind it.</p>
          ))}
        </div>
      ))}

      {sheet && (
        <p className="text-xs text-ps-label">
          {sheet.item_count} {sheet.item_count === 1 ? "item holds" : "items hold"} stock, carried at {formatPaise(sheet.carrying_value_paise)}.
          {sheetIsCurrent && sheet.entered_count > 0
            ? ` ${sheet.write_down_count} of the ${sheet.entered_count} entered would be written down, ${formatPaise(sheet.write_down_paise)} in all.`
            : ""}
        </p>
      )}

      <div className="overflow-x-auto border border-ps-border rounded-lg">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-ps-bg text-ps-label">
              <th className="px-3 py-2 text-left font-semibold">Item</th>
              <th className="px-3 py-2 text-right font-semibold">Held</th>
              <th className="px-3 py-2 text-right font-semibold">Carrying value</th>
              <th className="px-3 py-2 text-right font-semibold">Average cost / unit</th>
              <th className="px-3 py-2 text-right font-semibold">Your NRV / unit (₹)</th>
              <th className="px-3 py-2 text-right font-semibold">Write-down</th>
              <th className="px-3 py-2 text-right font-semibold">Value after</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ps-border">
            {rows.map((r) => {
              const box = boxes[r.service_catalogue_id];
              const answered = fresh(r) && r.status !== "not_entered";
              return (
                <tr key={r.service_catalogue_id} className="align-top">
                  <td className="px-3 py-2">
                    <p className="font-medium text-ps-ink">{r.name}</p>
                    {answered && STATUS_WORDS[r.status] && <p className="text-3xs text-ps-label">{STATUS_WORDS[r.status]}</p>}
                    {box?.kind === "bad" && (
                      <p className="text-3xs text-state-problem flex gap-1"><AlertTriangle size={11} className="shrink-0 mt-0.5" />
                        Not an amount: enter rupees per unit, like 120 or 120.50.</p>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-ps-label">{r.quantity_units}{r.unit ? ` ${r.unit}` : ""}</td>
                  <td className="px-3 py-2 text-right font-mono">{formatPaise(r.carrying_value_paise)}</td>
                  <td className="px-3 py-2 text-right font-mono text-ps-label">{formatPaise(r.average_cost_paise)}</td>
                  <td className="px-3 py-2 text-right">
                    <input
                      type="text" inputMode="decimal"
                      aria-label={`Net realisable value per unit for ${r.name}`}
                      aria-invalid={box?.kind === "bad" ? true : undefined}
                      className="w-28 border border-ps-border rounded px-2 py-1 text-right font-mono"
                      value={typed[r.service_catalogue_id] ?? ""}
                      onChange={(e) => setTyped((t) => ({ ...t, [r.service_catalogue_id]: e.target.value }))}
                      disabled={posting} />
                  </td>
                  <td className={`px-3 py-2 text-right font-mono ${answered && r.status === "write_down" ? "text-state-attention font-semibold" : "text-ps-hint"}`}>
                    {answered ? formatPaise(r.write_down_paise) : "—"}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-ps-label">{answered ? formatPaise(r.new_value_paise) : "—"}</td>
                </tr>
              );
            })}
            {!loading && sheet && rows.length === 0 && (
              <tr><td colSpan={7} className="px-3 py-8 text-center text-ps-hint">
                No item holds stock just now, so there is nothing to write down. Stock comes in through a purchase bill or an opening balance.
              </td></tr>
            )}
            {loading && !sheet && (
              <tr><td colSpan={7} className="px-3 py-8 text-center text-ps-hint">Loading the register…</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {canPost && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div>
            <label htmlFor="nrv-review-date" className="block text-xs font-medium text-ps-label mb-1">Date *</label>
            <DateInput id="nrv-review-date" value={date} onChange={setDate} onStateChange={dates.watch("nrvReviewDate", "Date")}
              className="w-full px-3 py-1.5 text-xs border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand" />
          </div>
          <div>
            <label htmlFor="nrv-review-reference" className="block text-xs font-medium text-ps-label mb-1">Reference</label>
            <input id="nrv-review-reference" value={reference} onChange={(e) => setReference(e.target.value)} placeholder={`NRV-${date}`}
              className="w-full px-3 py-1.5 text-xs border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand" />
          </div>
          <div>
            <label htmlFor="nrv-review-notes" className="block text-xs font-medium text-ps-label mb-1">Basis for the estimates</label>
            <input id="nrv-review-notes" value={notes} onChange={(e) => setNotes(e.target.value)}
              className="w-full px-3 py-1.5 text-xs border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand" />
          </div>
        </div>
      )}
    </Modal>
  );
}
