"use client";

/**
 * The annual return, consolidated from the year's own returns (GST-10).
 *
 * WHAT WAS MISSING
 *   The GSTR-9 tab loaded a saved draft and nothing produced one. CGST Act
 *   s.44 with Rule 80(1) makes the annual return a consolidation of the
 *   financial year's GSTR-1 and GSTR-3B — the portal opens FORM GSTR-9 once
 *   every one of them is furnished and auto-populates it from them — so the
 *   figures were all there and nothing added them up.
 *
 * THIS SCREEN DECIDES NOTHING (CLAUDE.md). Which figure belongs on which row,
 * which rows cannot be derived and why, and every sentence below the tables are
 * `domain/gst/gstr9_builder.py`'s answers. Nothing is filed and nothing is
 * saved: this is a working for a CA to check the portal's own auto-population
 * against.
 */
import { useCallback, useState } from "react";
import { AlertTriangle, Check, Calculator } from "lucide-react";
import { api, type GSTR9Working as Working } from "@/lib/api";
import { Callout, GapList } from "@/components/ui/callout";

const TABLE_TITLES: Record<string, string> = {
  "4": "Table 4 — supplies on which tax is payable",
  "5": "Table 5 — supplies on which tax is not payable",
  "6": "Table 6 — input tax credit availed",
  "7": "Table 7 — input tax credit reversed and ineligible",
  "8": "Table 8 — other input tax credit information",
  "9": "Table 9 — tax paid as declared in the year's returns",
};

function money(paise: number): string {
  return (paise / 100).toLocaleString("en-IN", {
    minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function GSTR9Working({
  clientId, financialYear,
}: { clientId: string; financialYear: string }) {
  const [working, setWorking] = useState<Working | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const compute = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const r = await api.gstr9.compute(clientId, financialYear);
      if (!r.success || !r.data) throw new Error(r.error ?? "Couldn't consolidate the year.");
      setWorking(r.data);
    } catch (e) {
      setWorking(null);
      setError(e instanceof Error ? e.message : "Couldn't consolidate the year.");
    } finally {
      setBusy(false);
    }
  }, [clientId, financialYear]);

  return (
    <div className="space-y-4 border-t border-ps-muted pt-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h4 className="text-sm font-semibold text-ps-ink">
            Consolidate FY {financialYear} from the year&apos;s returns
          </h4>
          <p className="text-2xs text-ps-label mt-1 max-w-2xl">
            CGST Act s.44 with Rule 80(1): the annual return consolidates this
            year&apos;s GSTR-1 and GSTR-3B. This adds them up and says which rows
            it could not derive. Nothing is saved and nothing is filed.
          </p>
        </div>
        <button onClick={compute} disabled={busy}
          className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1.5">
          <Calculator size={13} /> {busy ? "Consolidating…" : "Compute from filed returns"}
        </button>
      </div>

      {error && <Callout tone="problem">{error}</Callout>}

      {working && (
        <>
          {working.is_complete ? (
            <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2 text-xs text-emerald-800 flex gap-2">
              <Check size={13} className="shrink-0 mt-0.5" />
              <span>
                Every month of FY {working.financial_year} has a filed GSTR-1 and
                GSTR-3B, which is the condition the portal opens FORM GSTR-9 on.
              </span>
            </div>
          ) : (
            <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs text-amber-900 flex gap-2">
              <AlertTriangle size={13} className="shrink-0 mt-0.5" />
              <span>
                This is a consolidation of <strong>part</strong> of the year — not
                every monthly return is filed. The rows below are short by
                whatever the outstanding months carry.
              </span>
            </div>
          )}

          {/* WHAT COULD NOT BE DERIVED, verbatim. A nil on an annual return is
              a positive declaration that nothing was owed, so a row the server
              could not derive must never read as one. */}
          <GapList gaps={working.gaps} tone="withheld"
                   title="What this working does not answer" />

          {Object.entries(TABLE_TITLES).map(([key, title]) => {
            const rows = working.tables[key] ?? [];
            if (rows.length === 0) return null;
            return (
              <div key={key} className="space-y-1">
                <p className="text-xs font-semibold text-ps-body">{title}</p>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-ps-muted text-ps-hint text-left">
                        <th className="py-1.5 font-semibold w-16">Row</th>
                        <th className="py-1.5 font-semibold">Particulars</th>
                        <th className="py-1.5 font-semibold text-right">Taxable value</th>
                        <th className="py-1.5 font-semibold text-right">IGST</th>
                        <th className="py-1.5 font-semibold text-right">CGST</th>
                        <th className="py-1.5 font-semibold text-right">SGST</th>
                        <th className="py-1.5 font-semibold text-right">Cess</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-ps-bg">
                      {rows.map((r) => (
                        <tr key={r.code} className="align-top">
                          <td className="py-1.5 font-mono text-ps-label">{r.code}</td>
                          <td className="py-1.5 text-ps-ink">
                            {r.label}
                            {/* A row the server could not derive says so HERE,
                                beside its own figure — a note in a list at the
                                bottom is read as being about some other row. */}
                            {r.note && (
                              <span className="block text-3xs text-amber-800 mt-0.5 max-w-xl">
                                {r.note}
                              </span>
                            )}
                          </td>
                          {([r.txval_paise, r.igst_paise, r.cgst_paise, r.sgst_paise,
                             r.cess_paise]).map((v, i) => (
                            <td key={i} className={`py-1.5 text-right tabular-nums ${
                              r.note ? "text-ps-hint" : ""}`}>
                              {r.note && v === 0 ? "—" : money(v)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            );
          })}

          {working.hsn.length > 0 && (
            <div className="space-y-1">
              <p className="text-xs font-semibold text-ps-body">
                Table 17 — HSN summary of outward supplies
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-ps-muted text-ps-hint text-left">
                      <th className="py-1.5 font-semibold">HSN / SAC</th>
                      <th className="py-1.5 font-semibold">Description</th>
                      <th className="py-1.5 font-semibold">UQC</th>
                      <th className="py-1.5 font-semibold text-right">Quantity</th>
                      <th className="py-1.5 font-semibold text-right">Taxable value</th>
                      <th className="py-1.5 font-semibold text-right">IGST</th>
                      <th className="py-1.5 font-semibold text-right">CGST</th>
                      <th className="py-1.5 font-semibold text-right">SGST</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ps-bg">
                    {working.hsn.map((h) => (
                      <tr key={h.hsn_sc}>
                        <td className="py-1.5 font-mono text-ps-ink">{h.hsn_sc}</td>
                        <td className="py-1.5 text-ps-body">{h.desc ?? "—"}</td>
                        <td className="py-1.5 text-ps-label">{h.uqc ?? "—"}</td>
                        <td className="py-1.5 text-right tabular-nums">{h.qty}</td>
                        <td className="py-1.5 text-right tabular-nums">{money(h.txval_paise)}</td>
                        <td className="py-1.5 text-right tabular-nums">{money(h.igst_paise)}</td>
                        <td className="py-1.5 text-right tabular-nums">{money(h.cgst_paise)}</td>
                        <td className="py-1.5 text-right tabular-nums">{money(h.sgst_paise)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* The parts of the FORM this working does not build, each with the
              server's own reason — so the screen never implies the working is
              the whole return. */}
          {working.not_built && Object.keys(working.not_built).length > 0 && (
            <div className="space-y-1">
              <p className="text-xs font-semibold text-ps-body">
                Still to be completed on the portal
              </p>
              <dl className="text-2xs text-ps-label space-y-1">
                {Object.entries(working.not_built).map(([table, why]) => (
                  <div key={table} className="flex gap-2">
                    <dt className="font-mono text-ps-hint shrink-0">Table {table}</dt>
                    <dd className="max-w-2xl">{why}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}

          <p className="text-3xs text-ps-hint">{working.source}</p>
        </>
      )}
    </div>
  );
}
