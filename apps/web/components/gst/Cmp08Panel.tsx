"use client";

/**
 * FORM GST CMP-08 — a composition registration's quarterly statement under
 * CGST Act s.10 (GST-25).
 *
 * WHY IT LIVES ON THE REGISTRATION ROW AND NOWHERE ELSE
 *
 *   A composition registration files CMP-08 quarterly and GSTR-4 annually,
 *   never GSTR-1 or GSTR-3B (`other_return_form` already says so on this same
 *   row) — so offering this panel anywhere a return picker lives would put a
 *   form this registration must not file next to the one it must.
 *
 * IT DECIDES NOTHING. `domain/gst/composition.py` computes the four lines;
 * this fetches and renders. Row 1 (outward supplies) and row 2 (inward
 * reverse-charge supplies) are read from the SAME posted documents the
 * client's ordinary returns would read if it filed them — see
 * `services.gst_return_service.cmp08_statement`. Row 4 (interest) is the CA's
 * own figure: how late a payment actually was is not something this
 * computation can see.
 *
 * Rates are `[S]`-graded (`composition_rates_verified` says so on every
 * answer) — a caveat, never hidden, because a confident-looking rate that has
 * not been checked against Rule 7's own table is exactly the failure this
 * field exists to name.
 *
 * Prepare-only. Nothing here is transmitted or stored — CMP-08 has no row of
 * its own in this product, the same posture as the IFF panel beside it.
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
 */
import { useCallback, useState } from "react";
import { Loader2 } from "lucide-react";
import { api, type Cmp08Working } from "@/lib/api";
import { Callout, GapList } from "@/components/ui/callout";
import { formatPaise } from "@/lib/money/format";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { objectOrNull } from "@/lib/api/shape";

function todayPeriod(): string {
  const d = new Date();
  return `${String(d.getMonth() + 1).padStart(2, "0")}${d.getFullYear()}`;
}

function Cmp08LineRow({ label, line }: { label: string; line: Cmp08Working["outward_supplies"] }) {
  return (
    <tr className="border-b border-ps-border last:border-0">
      <td className="py-1.5 pr-3 text-ps-body">{label}</td>
      <td className="py-1.5 pr-3 text-right font-mono">{formatPaise(line.taxable_value_paise)}</td>
      <td className="py-1.5 pr-3 text-right font-mono">{formatPaise(line.igst_paise)}</td>
      <td className="py-1.5 pr-3 text-right font-mono">{formatPaise(line.cgst_paise)}</td>
      <td className="py-1.5 pr-3 text-right font-mono">{formatPaise(line.sgst_paise)}</td>
      <td className="py-1.5 text-right font-mono font-medium">{formatPaise(line.tax_paise)}</td>
    </tr>
  );
}

export function Cmp08Panel({ clientId, gstin }: { clientId: string; gstin: string }) {
  const [period, setPeriod] = useState(todayPeriod());
  const [interestInput, setInterestInput] = useState("");
  const [data, setData] = useState<Cmp08Working | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!clientId || !/^\d{6}$/.test(period)) return;
    setLoading(true);
    setError(null);
    const interestPaise = paiseFromRupeeInput(interestInput) ?? 0;
    try {
      const res = await api.cmp08.compute(clientId, period, gstin, interestPaise);
      // objectOrNull, not a cast — a payload missing a field must not read as
      // present just because TypeScript was told it would be.
      setData(objectOrNull<Cmp08Working>(res.success ? res.data : null));
      if (!res.success) setError(res.error ?? "Couldn't prepare CMP-08.");
    } catch (e) {
      setData(null);
      setError(e instanceof Error ? e.message : "Couldn't prepare CMP-08.");
    } finally {
      setLoading(false);
    }
  }, [clientId, gstin, period, interestInput]);

  return (
    <div className="mt-2 border border-ps-border rounded-lg p-3 space-y-3 bg-ps-bg/40">
      <div>
        <h5 className="text-xs font-semibold text-ps-ink">Prepare FORM GST CMP-08</h5>
        <p className="text-3xs text-ps-hint mt-0.5">
          CGST Act s.10, Rule 62 — the quarterly self-assessed statement a
          composition dealer pays with, in lieu of GSTR-1 and GSTR-3B.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <label className="text-2xs">
          <span className="block text-ps-body font-medium mb-1">Any month of the quarter</span>
          <input value={period} inputMode="numeric" placeholder="MMYYYY"
            onChange={(e) => { setPeriod(e.target.value.replace(/\D/g, "").slice(0, 6)); setData(null); }}
            className="px-2 py-1 border border-ps-border rounded w-24 font-mono" />
        </label>
        <label className="text-2xs">
          <span className="block text-ps-body font-medium mb-1">Interest paid, if any (₹)</span>
          <input value={interestInput} inputMode="decimal" placeholder="0"
            onChange={(e) => setInterestInput(e.target.value)}
            className="px-2 py-1 border border-ps-border rounded w-28" />
        </label>
        <button onClick={load} disabled={loading || !/^\d{6}$/.test(period)}
          className="text-2xs px-3 py-1.5 rounded-lg font-medium text-white bg-brand hover:bg-brand-dark disabled:opacity-40 inline-flex items-center gap-1.5">
          {loading && <Loader2 size={11} className="animate-spin" />}
          Compute
        </button>
      </div>

      {error && (
        <Callout tone="problem" title="Couldn't prepare CMP-08">{error}</Callout>
      )}

      {data && (
        <div className="space-y-2">
          <p className="text-2xs text-ps-hint">
            {data.quarter} · {data.financial_year} · {gstin}
          </p>

          {!data.composition_rates_verified && (
            <Callout tone="note" title="Rate not independently verified">
              The s.10 rate applied here is recorded from the Finance Act and
              Rule 7 rather than confirmed against the CBIC portal in this
              environment. Check it before relying on this figure.
            </Callout>
          )}

          <GapList gaps={data.gaps} tone="attention" title="Cannot be computed in full" />


          <div className="overflow-x-auto">
            <table className="w-full text-2xs">
              <thead>
                <tr className="text-ps-hint text-left border-b border-ps-border">
                  <th className="py-1.5 pr-3 font-semibold">Row</th>
                  <th className="py-1.5 pr-3 font-semibold text-right">Taxable value</th>
                  <th className="py-1.5 pr-3 font-semibold text-right">IGST</th>
                  <th className="py-1.5 pr-3 font-semibold text-right">CGST</th>
                  <th className="py-1.5 pr-3 font-semibold text-right">SGST</th>
                  <th className="py-1.5 font-semibold text-right">Tax</th>
                </tr>
              </thead>
              <tbody>
                <Cmp08LineRow label="1. Outward supplies (incl. exempt)" line={data.outward_supplies} />
                <Cmp08LineRow label="2. Inward supplies under reverse charge" line={data.inward_rcm_supplies} />
                <Cmp08LineRow label="3. Tax payable (1 + 2)" line={data.tax_paid} />
              </tbody>
            </table>
          </div>

          <p className="text-2xs text-ps-body">
            4. Interest paid, if any: <span className="font-mono font-medium">{formatPaise(data.interest_paise)}</span>
          </p>
        </div>
      )}
    </div>
  );
}
