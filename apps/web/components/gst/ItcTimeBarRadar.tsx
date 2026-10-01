"use client";

/**
 * THE §16(4) RADAR — credit not yet claimed, with the date it lapses (gst-15).
 *
 * CGST §16(4) takes the credit away: it cannot be availed on an invoice after
 * 30 November following the financial year the invoice pertains to, or the
 * annual return, whichever is earlier. The product could show, bill by bill,
 * that a supplier had not filed; it could not say which of those credits would
 * be GONE on that date. This lists them, nearest lapse first.
 *
 * THE SERVER HOLDS THE RULE AND THE DATE. `domain/gst/itc_time_bar` decides what
 * is on the list and `correction_window` — the one place that knows the date and
 * its "whichever is earlier" — says when. This renders the answer: it computes
 * no date, holds no list of verdicts and names no deadline. The rule sentence on
 * screen is the one the server sent.
 *
 * THREE THINGS ARE KEPT APART, because a CA acts differently on each:
 *   * a row — credit a supplier's action could still rescue, with its date;
 *   * a MONTH with no GSTR-2B reconciled — nothing in it has been judged, so no
 *     bill is called safe or at risk, but the month is inside a closing window;
 *   * a count — bills the portal itself has blocked, which carry no date because
 *     waiting does not change what 2B says.
 * An empty list is therefore NOT a clean bill of health, and the panel never
 * says so while a month is unreconciled.
 *
 * A window that has closed is still shown, in the problem tone: what was lost
 * matters at least as much as what can be saved.
 *
 * Read-only. Nothing is claimed, posted, filed or sent to any portal.
 */

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ItcTimeBar, ItcTimeBarItem, ItcTimeBarStatus } from "@/lib/api";
import { objectWithLists } from "@/lib/api/shape";
import { fromLocalISO } from "@/lib/dateMath";
import { gstPeriodLabel } from "@/lib/gst/period";
import { formatPaise } from "@/lib/money/format";

/** A calendar date, never read back through UTC. */
function day(iso: string): string {
  const d = fromLocalISO(iso);
  return d
    ? d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })
    : iso;
}

const TONE: Record<ItcTimeBarStatus, string> = {
  open: "text-ps-body",
  closing_soon: "text-state-attention",
  closed: "text-state-problem",
};

function left(status: ItcTimeBarStatus, days: number): string {
  if (status === "closed") return `closed ${Math.abs(days)} day(s) ago`;
  if (days === 0) return "closes today";
  return `${days} day(s) left`;
}

const KIND_LABEL: Record<ItcTimeBarItem["kind"], string> = {
  withheld_bill: "Bill — credit withheld",
  not_booked: "On GSTR-2B — no bill",
};

export function ItcTimeBarRadar({ clientId }: { clientId: string }) {
  const [radar, setRadar] = useState<ItcTimeBar | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const r = await api.gstWorkspace.itcTimeBar(clientId);
        if (cancelled) return;
        if (r.success) {
          setRadar(objectWithLists<ItcTimeBar>(
            r.data, "items", "by_financial_year", "periods_not_reconciled",
            "notes", "scanned_financial_years"));
        } else {
          setError(r.error ?? "The deadline list could not be loaded.");
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "The deadline list could not be loaded.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [clientId]);

  return (
    <div className="border rounded p-4 space-y-3 mb-6" data-testid="itc-time-bar">
      <div>
        <h3 className="font-medium">Credit that will lapse — CGST §16(4)</h3>
        <p className="text-xs text-ps-label mt-0.5">
          {radar?.rule ??
            "Credit not yet claimed, with the date it can no longer be taken."}
        </p>
      </div>

      {loading && <p className="text-xs text-ps-label">Reading the bills and GSTR-2B…</p>}
      {error && <p role="alert" className="text-xs text-state-problem">{error}</p>}

      {radar && (
        <>
          <div className="grid grid-cols-3 gap-3 text-sm">
            <div>
              <p className="text-xs text-ps-label">Credit at risk</p>
              <p className="font-medium">{formatPaise(radar.totals.credit_at_risk_paise)}</p>
            </div>
            <div>
              <p className="text-xs text-ps-label">
                Lapsing within {radar.closing_soon_days} days
              </p>
              <p className="font-medium text-state-attention">
                {formatPaise(radar.totals.closing_soon_paise)}
              </p>
            </div>
            <div>
              <p className="text-xs text-ps-label">Already lapsed</p>
              <p className="font-medium text-state-problem">
                {formatPaise(radar.totals.lapsed_paise)}
              </p>
            </div>
          </div>

          {radar.by_financial_year.length > 0 && (
            <ul className="text-xs space-y-1">
              {radar.by_financial_year.map((y) => (
                <li key={y.financial_year} className={TONE[y.status]}>
                  <span className="font-medium">FY {y.financial_year}</span>
                  {" — "}credit lapses on {day(y.closes_on)} ({left(y.status, y.days_left)})
                  {y.shortened_by_annual_return && " · brought forward by the annual return"}
                  {" · "}{y.count} document(s), {formatPaise(y.credit_at_risk_paise)}
                </li>
              ))}
            </ul>
          )}

          {radar.items.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-ps-hint border-b">
                  <tr>
                    <th className="text-left py-1.5 pr-3 font-medium">Lapses on</th>
                    <th className="text-left py-1.5 pr-3 font-medium">Document</th>
                    <th className="text-left py-1.5 pr-3 font-medium">Supplier</th>
                    <th className="text-right py-1.5 pr-3 font-medium">Credit at risk</th>
                    <th className="text-left py-1.5 font-medium">Why</th>
                  </tr>
                </thead>
                <tbody>
                  {radar.items.map((it, i) => (
                    <tr key={`${it.document_id ?? it.label}-${i}`}
                      className="border-b last:border-0 align-top" data-status={it.status}>
                      <td className={`py-1.5 pr-3 ${TONE[it.status]}`}>
                        <span className="font-medium">{day(it.closes_on)}</span>
                        <span className="block text-3xs">{left(it.status, it.days_left)}</span>
                      </td>
                      <td className="py-1.5 pr-3">
                        {it.label || "—"}
                        <span className="block text-3xs text-ps-hint">
                          {KIND_LABEL[it.kind]} · {it.document_date}
                        </span>
                      </td>
                      <td className="py-1.5 pr-3">
                        {it.supplier || "—"}
                        {it.supplier_gstin && (
                          <span className="block text-3xs text-ps-hint">{it.supplier_gstin}</span>
                        )}
                      </td>
                      <td className="py-1.5 pr-3 text-right font-mono">
                        {formatPaise(it.credit_at_risk_paise)}
                      </td>
                      <td className="py-1.5 text-ps-label">{it.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-xs text-ps-label">
              No credit in the reconciled months is withheld or left unbooked
              {radar.periods_not_reconciled.length > 0
                ? " — but see the months below that have not been reconciled."
                : "."}
            </p>
          )}

          {radar.periods_not_reconciled.length > 0 && (
            <div className="space-y-1" data-testid="itc-time-bar-unreconciled">
              <p className="text-xs font-medium text-state-attention">
                No GSTR-2B reconciled for these months — nothing in them has been checked
              </p>
              <ul className="text-xs space-y-0.5">
                {radar.periods_not_reconciled.map((p) => (
                  <li key={p.period} className={TONE[p.status]}>
                    {gstPeriodLabel(p.period)} — credit on its invoices lapses on{" "}
                    {day(p.closes_on)} ({left(p.status, p.days_left)})
                  </li>
                ))}
              </ul>
            </div>
          )}

          {radar.notes.map((n, i) => (
            <p key={i} className="text-3xs text-ps-hint">{n}</p>
          ))}
        </>
      )}
    </div>
  );
}
