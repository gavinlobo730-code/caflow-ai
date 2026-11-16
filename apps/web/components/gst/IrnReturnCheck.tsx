"use client";

/**
 * The period's live IRN records against the GSTR-1 the books build for it (POST-A-066).
 *
 * An IRN recorded as live for an invoice this return does not declare, or a record whose invoice number or date is no longer the
 * invoice's, is a disagreement between two records of one supply. The server finds them and words each one; this panel asks when
 * the CA presses Check and shows what came back. It DECIDES NOTHING and reaches no portal: what to do (cancel the IRN on the IRP
 * and record it, correct or reinstate the invoice) is the CA's.
 *
 * A FAILED READ IS NOT A CLEAN RESULT. "Nothing to report" is shown only for an answer that compared its records; a failure is
 * said in the server's words.
 */
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/states";
import { checkGSTR1Irns, type IrnReturnCheck as Answer, type IrnReturnRow } from "@/lib/data/gst";
import { formatDate, formatMonthYear } from "@/lib/dates/format";

type State = { state: "idle" } | { state: "loading" } | { state: "ok"; answer: Answer } | { state: "failed"; message: string };

function Rows({ rows, label }: { rows: IrnReturnRow[]; label: string }) {
  if (rows.length === 0) return null;
  return (
    <div>
      <p className="text-xs font-semibold text-ps-ink">{label} ({rows.length})</p>
      <ul className="mt-1 space-y-1.5">
        {rows.map((r) => (
          <li key={`${label}-${r.record_id}`} className="text-xs text-ps-body">
            <span className="font-mono">{r.record_number ?? "(no number)"}</span>
            <span className="text-ps-hint"> · {formatDate(r.record_date)}</span>
            <span className="block text-state-attention">{r.sentence}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function IrnReturnCheck({ clientId, yearMonth, gstin }: { clientId: string; yearMonth: string; gstin?: string }) {
  const [state, setState] = useState<State>({ state: "idle" });

  // A check belongs to the client, month and registration it was asked for: choosing another clears it.
  useEffect(() => { setState({ state: "idle" }); }, [clientId, yearMonth, gstin]);

  async function run() {
    if (state.state === "loading") return;
    setState({ state: "loading" });
    try {
      setState({ state: "ok", answer: await checkGSTR1Irns(clientId, yearMonth, gstin) });
    } catch (e) {
      setState({ state: "failed", message: e instanceof Error && e.message ? e.message : "The check could not be run." });
    }
  }

  const answer = state.state === "ok" ? state.answer : null;
  const clean = answer !== null && (answer.not_declared ?? []).length === 0 && (answer.differs ?? []).length === 0
    && (answer.duplicates ?? []).length === 0;
  return (
    <section className="rounded-lg border border-ps-border p-4 space-y-3" aria-labelledby="irn-return-check-title">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 id="irn-return-check-title" className="text-sm font-semibold text-ps-ink">Recorded IRNs against this return</h3>
          <p className="text-2xs text-ps-hint">
            Every IRN recorded as live for the period of this return ({formatMonthYear(yearMonth)}), checked against the invoices
            the return declares, built again from the books as they stand now.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={run} disabled={state.state === "loading"} data-testid="irn-return-check">
          {state.state === "loading" ? "Checking…" : "Check"}
        </Button>
      </div>
      {state.state === "failed" && <p className="text-xs text-state-problem" role="alert">{state.message}</p>}
      {answer && (
        <div className="space-y-3" data-testid="irn-return-check-answer">
          <p className="text-xs text-ps-label">
            {formatDate(answer.from)} to {formatDate(answer.to)}: {answer.live_irns_compared} live IRN record(s) compared with{" "}
            {answer.declared_invoices} invoice(s) this return declares as B2B supplies or exports.
          </p>
          {clean && answer.live_irns_compared > 0 && (
            <p className="text-xs text-state-ready">Every live IRN record names an invoice this return declares, as recorded.</p>
          )}
          {clean && answer.live_irns_compared === 0 && (
            <EmptyState
              className="py-6"
              title="No IRN is recorded as live for this period"
              description="There was nothing to compare. An IRN is recorded from an invoice's compliance panel once it has been obtained on the portal."
            />
          )}
          <Rows rows={answer.not_declared ?? []} label="Live IRNs this return does not declare as a B2B supply or an export" />
          <Rows rows={answer.differs ?? []} label="Records that no longer match their invoice" />
          {(answer.duplicates ?? []).length > 0 && (
            <div>
              <p className="text-xs font-semibold text-ps-ink">More than one live record for one invoice ({answer.duplicates.length})</p>
              <ul className="mt-1 space-y-1">
                {answer.duplicates.map((d) => (
                  <li key={d.record_ids.join("|")} className="text-xs text-state-attention">{d.sentence}</li>
                ))}
              </ul>
            </div>
          )}
          <p className="text-2xs text-ps-hint">{answer.converse} {answer.not_compared}</p>
        </div>
      )}
    </section>
  );
}
