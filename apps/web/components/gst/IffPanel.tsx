/**
 * The Invoice Furnishing Facility — CGST Rule 59(2), GST-11's remaining half.
 *
 * WHY IT IS ON THE QUARTERLY GSTR-1 SCREEN AND NOWHERE ELSE
 *
 *   A QRMP filer's GSTR-1 covers a QUARTER, and the moment a CA opens it is
 *   the moment the question arises: the two interim months' documents are in
 *   this return, so the customer's input tax credit has been waiting for it.
 *   `return_period.IFF_AVAILABLE` already says so in the return's own caveats;
 *   this is the panel that lets the CA act on the sentence rather than read it.
 *
 *   It renders NOTHING for a monthly filer. A monthly GSTR-1 furnishes every
 *   month on the 11th and the facility is meaningless — offering it would be a
 *   control that does nothing, which is the shape this repository keeps having
 *   to delete.
 *
 * THE MONTH IS A CALENDAR MONTH AND THE RETURN'S PERIOD IS A QUARTER, which is
 * the one thing to hold on to while reading this. `period` here is the
 * quarter's own key — its FIRST month, which is what `return_period.resolve`
 * canonicalises to — so months 1 and 2 are that month and the one after it.
 * The third is deliberately not offered: its documents are in the quarterly
 * return itself and furnishing them here would declare them twice, which the
 * server refuses in `domain/gst/iff.build_iff` as well.
 *
 * IT DECIDES NOTHING. Every figure, every reason and every refusal comes from
 * `domain/gst/iff.py`; this fetches and renders. In particular the CAP is
 * REPORTED and not enforced anywhere — Rule 59(2) lets the supplier furnish
 * "as he may consider necessary", so which documents fit inside ₹50 lakh is
 * the CA's choice, and a screen that trimmed the list would show a set that
 * does not match the sales register.
 *
 * Prepare-only. Nothing is transmitted and nothing is stored: the facility has
 * no row of its own, because `gstr1_returns` is keyed on (client, period,
 * gstin) and a month of a quarter is not a return period.
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { api, type IffWorking } from "@/lib/api";
import { Callout, GapList } from "@/components/ui/callout";
import { formatPaise } from "@/lib/money/format";
import { objectOrNull } from "@/lib/api/shape";

const MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
                     "July", "August", "September", "October", "November",
                     "December"];

/** MMYYYY -> "May 2025". Returns the key itself if it is not one. */
function monthLabel(mmyyyy: string): string {
  if (!/^\d{6}$/.test(mmyyyy)) return mmyyyy;
  const m = Number(mmyyyy.slice(0, 2));
  return m >= 1 && m <= 12 ? `${MONTH_NAMES[m - 1]} ${mmyyyy.slice(2)}` : mmyyyy;
}

export interface IffPanelProps {
  clientId: string;
  /** The window's OWN months, as the server resolved them
   *  (`period_window.months`) — three for a quarter, and the first two are the
   *  ones the facility reaches.
   *
   *  TAKEN FROM THE SERVER RATHER THAN DERIVED HERE. Rolling a month forward
   *  is date arithmetic, and which calendar months make up a GST quarter is a
   *  fact about the financial year that `core.ist_clock.fy_quarters` already
   *  owns. A second answer in the browser would be one more place for a
   *  quarter to mean something different. */
  months: string[];
  /** False for a monthly filer, where the facility does not arise. */
  isQuarter: boolean;
  gstin?: string;
}

export function IffPanel({ clientId, months: windowMonths, isQuarter, gstin }: IffPanelProps) {
  // Only the FIRST TWO. The third month's documents are in the quarterly
  // return itself, and `build_iff` refuses it on the server as well.
  const months = (windowMonths ?? []).slice(0, 2);
  const [month, setMonth] = useState<string>(months[0] ?? "");
  const [data, setData] = useState<IffWorking | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The quarter can change under this panel (the CA switches period), so the
  // chosen month follows it rather than pointing at a month of the old one.
  useEffect(() => { setMonth(months[0] ?? ""); setData(null); },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [months.join(",")]);

  const load = useCallback(async () => {
    if (!clientId || !month) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.iff.compute(clientId, month, gstin);
      // `objectOrNull`, not `res.data as IffWorking`: a cast satisfies the
      // compiler however absent the payload is at runtime, and the September
      // crashes this helper exists for were all of that shape.
      setData(objectOrNull<IffWorking>(res.success ? res.data : null));
      if (!res.success) setError(res.error ?? "Couldn't prepare the facility.");
    } catch (e) {
      setData(null);
      setError(e instanceof Error ? e.message : "Couldn't prepare the facility.");
    } finally {
      setLoading(false);
    }
  }, [clientId, month, gstin]);

  if (!isQuarter || months.length === 0) return null;

  const notCarried = data?.not_carried ?? [];
  const notes = data?.notes ?? [];

  return (
    <div className="mt-4 border border-ps-border rounded-lg p-4 space-y-3">
      <div>
        <h4 className="text-sm font-semibold text-ps-ink">
          Invoice Furnishing Facility
        </h4>
        <p className="text-xs text-ps-body mt-1">
          CGST Rule 59(2). Furnish the first or second month&apos;s documents to
          registered customers by the 13th of the following month, so their
          input tax credit does not wait for this quarterly return. Optional —
          nothing is owed if it is not used.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {months.map((m) => (
          <button key={m} onClick={() => { setMonth(m); setData(null); }}
            aria-pressed={month === m}
            className={`text-xs px-3 py-1.5 rounded-lg border ${month === m
              ? "border-brand bg-brand/5 text-ps-ink font-medium"
              : "border-ps-border text-ps-label hover:bg-ps-bg"}`}>
            {monthLabel(m)}
          </button>
        ))}
        <button onClick={load} disabled={loading || !month}
          className="text-xs px-3 py-1.5 rounded-lg font-medium text-white bg-brand hover:bg-brand-dark disabled:opacity-40 inline-flex items-center gap-1.5">
          {loading && <Loader2 size={12} className="animate-spin" />}
          Prepare {monthLabel(month)}
        </button>
      </div>

      {error && (
        <Callout tone="problem" title="Couldn't prepare the facility">
          {error}
        </Callout>
      )}

      {data && data.available === false && (
        <Callout tone="note" title={`${monthLabel(data.period)} has no facility`}>
          {data.reason}
        </Callout>
      )}

      {data && data.available !== false && (
        <div className="space-y-3">
          <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div>
              <dt className="text-ps-hint">Documents</dt>
              <dd className="text-ps-ink font-medium tabular-nums">{data.document_count}</dd>
            </div>
            <div>
              <dt className="text-ps-hint">Cumulative value</dt>
              <dd className="text-ps-ink font-medium font-mono">
                {formatPaise(data.cumulative_value_paise)}
              </dd>
            </div>
            <div>
              <dt className="text-ps-hint">Rule 59(2) limit</dt>
              <dd className="text-ps-ink font-medium font-mono">
                {formatPaise(data.cap_paise)}
              </dd>
            </div>
            <div>
              <dt className="text-ps-hint">Furnish by</dt>
              <dd className="text-ps-ink font-medium">{data.due_date ?? "—"}</dd>
            </div>
          </dl>

          {data.cap_exceeded && (
            <Callout tone="attention" title="Above the monthly limit">
              This month&apos;s documents come to {formatPaise(data.cumulative_value_paise)},
              which is {formatPaise(data.excess_paise)} above the Rule 59(2)
              limit. Nothing has been left out — choose which documents to
              furnish, and the rest go in the quarterly return.
            </Callout>
          )}

          <GapList
            gaps={notCarried.map((n) => ({
              reference_no: n.reference_no ?? n.section,
              reason: n.reason,
            }))}
            tone="withheld"
            title="Not carried by this facility"
          />

          {notes.length > 0 && (
            <Callout tone="note" title="About this working">
              <ul className="space-y-1.5">
                {notes.map((n, i) => <li key={i}>{n}</li>)}
              </ul>
            </Callout>
          )}
        </div>
      )}
    </div>
  );
}
