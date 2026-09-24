"use client";

/**
 * E-way bills at or past their Rule 138(10) validity (SALES-28).
 *
 * `eway_validity` has computed the expiry since SALES-28's first half and
 * `/records/{id}/validity` served it — but only to somebody who had already
 * opened that one record. A bill that lapses while the lorry is still moving
 * exposes the consignment to detention and seizure under CGST §129, and the
 * extension path has existed the whole time with nothing to prompt it.
 *
 * IT IS NOT A COMPLIANCE ROW AND IS DELIBERATELY NOT RENDERED AS ONE. The
 * table below it holds `ComplianceEntry` rows, each with a filing status and a
 * Mark Filed action. Nothing is FILED for an e-way bill: the action is to
 * extend it on the NIC portal under the proviso to Rule 138(10). Folding it
 * into that table would mean inventing a compliance_type and offering a button
 * that means nothing.
 *
 * THIS SCREEN DECIDES NOTHING. Which bills are listed, which bucket each falls
 * in, whether the date was recorded or computed, and both caveats are the
 * server's — including the one that says the portal remains authoritative.
 * Rendering the source is the point rather than a detail: "recorded off the
 * portal" and "worked out from the distance" are different claims and a CA
 * acts differently on each.
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Clock, HelpCircle, Truck } from "lucide-react";
import { api, type ExpiringEwayBill, type ExpiringEwayBills as Report } from "@/lib/api";
import { objectOrNull } from "@/lib/api/shape";

const STATE_LABEL: Record<ExpiringEwayBill["state"], string> = {
  expired: "Expired",
  expires_today: "Expires today",
  expiring: "Expiring",
  unknown: "Cannot be told",
};

function daysText(b: ExpiringEwayBill): string {
  if (b.state === "unknown" || b.days_left === null) return "—";
  if (b.days_left < 0) return `${Math.abs(b.days_left)}d ago`;
  if (b.days_left === 0) return "today";
  return `in ${b.days_left}d`;
}

export function ExpiringEwayBills() {
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.ewayBill.expiring(2);
      // `objectOrNull`, not `r.data` — `lib/api/shape.ts` exists for exactly
      // this and its own docstring records thirteen screens that crashed this
      // way on 16-09-2026. `[]` is TRUTHY, so the `!report` guard below passes
      // an array straight through and `report.bills.length` throws; so does a
      // `{}` from a backend that has not deployed this endpoint yet, which is
      // a real state on every rolling deploy.
      setReport(objectOrNull<Report>(r.success ? r.data : null));
    } catch {
      // Silent: this is a panel above the deadline table, not the screen's
      // own data. A red banner here would suggest the deadlines failed to
      // load when they did not.
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // The FIELDS are defended too, not just the envelope. `objectOrNull` answers
  // "is this the right KIND of thing" and deliberately validates no field —
  // its docstring says so — so an object arriving without `bills` still
  // reaches here. Reading a missing list as empty renders nothing, which is
  // this panel's own no-data state.
  const bills = report?.bills ?? [];
  const caveats = report?.caveats ?? [];
  if (loading || !report || bills.length === 0) return null;

  return (
    <section className="bg-ps-surface border border-ps-border rounded-xl overflow-hidden mb-6">
      <div className="px-5 py-3 bg-ps-bg border-b border-ps-border flex items-center gap-2">
        <Truck size={14} className="text-ps-label" />
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-ps-ink text-sm">E-way bills expiring</h3>
          <p className="text-xs text-ps-label">
            {report.expired > 0 && <>{report.expired} expired · </>}
            {report.expires_today > 0 && <>{report.expires_today} today · </>}
            {report.expiring > 0 && <>{report.expiring} within {report.horizon_days}d · </>}
            {report.undeterminable > 0 && <>{report.undeterminable} undeterminable · </>}
            as at {report.as_of}
          </p>
        </div>
      </div>

      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-ps-label border-b border-ps-border">
            <th className="text-left font-medium px-5 py-2">Invoice</th>
            <th className="text-left font-medium px-5 py-2">E-way bill</th>
            <th className="text-left font-medium px-5 py-2">Valid upto</th>
            <th className="text-left font-medium px-5 py-2">Source</th>
            <th className="text-right font-medium px-5 py-2">When</th>
            <th className="text-left font-medium px-5 py-2">State</th>
          </tr>
        </thead>
        <tbody>
          {bills.map((b) => (
            <tr key={b.record_id} className="border-b border-ps-border last:border-0 align-top">
              <td className="px-5 py-2">
                <Link href={`/clients/${b.client_id}`}
                      className="text-brand hover:underline">{b.invoice_number || "—"}</Link>
              </td>
              <td className="px-5 py-2 font-mono text-xs text-ps-body">{b.ewb_number || "—"}</td>
              <td className="px-5 py-2 text-ps-body">{b.valid_upto || "—"}</td>
              <td className="px-5 py-2 text-xs text-ps-label">
                {/* The two are different CLAIMS, not two ways of saying one
                    thing. A recorded date came off the portal; a computed one
                    is Rule 138(10) arithmetic on a distance somebody typed. */}
                {b.source === "recorded" ? "Portal" : b.source === "computed" ? "Computed" : "—"}
              </td>
              <td className="px-5 py-2 text-right font-mono tabular-nums text-ps-body">{daysText(b)}</td>
              <td className="px-5 py-2">
                <span className={`inline-flex items-center gap-1 text-xs ${
                  b.state === "expired" ? "text-state-problem"
                    : b.state === "expires_today" ? "text-state-attention"
                    : b.state === "unknown" ? "text-ps-hint" : "text-ps-body"}`}>
                  {b.state === "unknown"
                    ? <HelpCircle size={11} />
                    : b.state === "expired" ? <AlertTriangle size={11} /> : <Clock size={11} />}
                  {STATE_LABEL[b.state]}
                </span>
                {b.gap && <p className="text-xs text-ps-hint mt-0.5">{b.gap}</p>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="px-5 py-3 border-t border-ps-border bg-ps-bg space-y-1">
        {caveats.map((c, i) => (
          <p key={i} className="text-xs text-ps-hint">{c}</p>
        ))}
      </div>
    </section>
  );
}
