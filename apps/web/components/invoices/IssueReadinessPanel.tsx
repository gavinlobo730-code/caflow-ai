"use client";

/**
 * What stands between this draft and its issue, in the editor's summary rail (POST-A-125).
 *
 * The server lists the reasons (`GET /api/sales-invoices/{id}/issue-preflight`: the SAME list the issue route refuses from) and this panel
 * shows them with the action each offers. It holds no rule and writes no sentence of its own: which things block an issue is
 * `domain/sales/issue_readiness`, and what the browser decides about the payload is `lib/invoices/issueReadiness`.
 *
 * WHAT IT SAYS, AND WHAT IT DOES NOT
 *   * it is checked against the draft AS LAST SAVED, and it says so; with unsaved changes it says the answer may be out of date;
 *   * an answer that could not be had says that, with Retry, and never "ready": "nothing in the way" is the server's claim to make;
 *   * a new invoice that has not been saved has no draft to check, and the panel says to save a draft first;
 *   * the only thing it can write is the chart of accounts set-up (`api.account.seedCoa`, idempotent), behind the one-flight guard, and
 *     it asks again afterwards.
 */
import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, AlertCircle } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { useSingleFlight } from "@/lib/async/useSingleFlight";
import { readinessFrom, type IssueBlocker, type ReadinessState } from "@/lib/invoices/issueReadiness";

type Field = "invoice_no" | "supply_state" | "lines";

export function IssueReadinessPanel({ invoiceId, checkNonce, unsavedChanges, onState, onFix }: {
  invoiceId: string | null;
  /** Changes whenever the editor has just tried to save or issue, so the panel asks the server again. */
  checkNonce: number;
  unsavedChanges: boolean;
  onState: (state: ReadinessState) => void;
  onFix: (field: Field) => void;
}) {
  const [state, setState] = useState<ReadinessState>({ status: "loading" });
  const [retry, setRetry] = useState(0);
  const [setupError, setSetupError] = useState<string | null>(null);
  const { flight } = useSingleFlight();

  useEffect(() => {
    if (!invoiceId) return;
    let cancelled = false;
    setState({ status: "loading" });
    (async () => {
      let next: ReadinessState;
      try {
        next = readinessFrom(await api.salesInvoices.issuePreflight(invoiceId));
      } catch (e) {
        next = { status: "unknown", reason: e instanceof Error && e.message ? e.message : "The server did not answer." };
      }
      if (cancelled) return;
      setState(next);
      onState(next);
    })();
    return () => { cancelled = true; };
    // onState is the editor's state setter: stable, and not a reason to ask again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoiceId, checkNonce, retry]);

  const setUpChart = useCallback(async () => {
    setSetupError(null);
    try {
      const res = await api.account.seedCoa();
      if (!res.success) setSetupError(res.error ?? "The chart of accounts could not be set up.");
    } catch (e) {
      setSetupError(e instanceof Error && e.message ? e.message : "The chart of accounts could not be set up.");
    }
    setRetry((n) => n + 1);
  }, []);

  return (
    <div className="bg-white rounded-xl border border-ps-border p-4 space-y-2 text-xs mt-3" data-testid="issue-readiness-panel">
      <p className="font-semibold text-ps-body">Ready to issue?</p>
      {!invoiceId ? (
        <p className="text-ps-hint">Save the invoice as a draft and this panel will check whether it can be issued.</p>
      ) : state.status === "loading" ? (
        <p className="text-ps-hint">Checking the draft…</p>
      ) : state.status === "unknown" ? (
        <div className="space-y-1.5">
          <p className="text-state-attention">Could not check whether this draft can be issued. {state.reason}</p>
          <button type="button" onClick={() => setRetry((n) => n + 1)}
            className="text-2xs font-medium text-brand hover:underline">Check again</button>
        </div>
      ) : state.status === "ready" ? (
        <p className="flex items-start gap-1.5 text-state-ready">
          <CheckCircle2 size={12} className="mt-px flex-shrink-0" aria-hidden />
          <span>Nothing is in the way of issuing the draft as saved.</span>
        </p>
      ) : (
        <ul className="space-y-2" aria-label="What is in the way of issuing this draft">
          {state.blockers.map((b: IssueBlocker, i: number) => (
            <li key={`${b.code}-${i}`} className="space-y-1">
              <p className="flex items-start gap-1.5 text-state-problem">
                <AlertCircle size={12} className="mt-px flex-shrink-0" aria-hidden />
                <span>{b.message}</span>
              </p>
              {b.action?.kind === "fix_in_editor" && (
                <button type="button" onClick={() => onFix((b.action as { field: Field }).field)}
                  className="ml-[18px] text-2xs font-medium text-brand hover:underline">{b.action.label}</button>
              )}
              {b.action?.kind === "seed_chart_of_accounts" && (
                <Button variant="plain" size="none" flight={flight} onClick={setUpChart}
                  className="ml-[18px] text-2xs px-2.5 py-1 border border-brand/30 text-brand rounded-md hover:bg-brand-light/20 disabled:opacity-50">
                  {b.action.label}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {setupError && <p className="text-3xs text-state-problem">{setupError}</p>}
      {invoiceId && (
        <p className="text-3xs text-ps-hint">
          {unsavedChanges
            ? "Checked against the draft as last saved. You have unsaved changes, so this may be out of date; Save & Issue checks again."
            : "Checked against the draft as saved."}
        </p>
      )}
    </div>
  );
}
