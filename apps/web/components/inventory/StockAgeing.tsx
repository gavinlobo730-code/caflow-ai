"use client";

/**
 * How long has the stock ON HAND been held (INV-04, migration 408).
 *
 * A DIFFERENT QUESTION FROM DAYS IDLE, which the register beside this already
 * answers. Days Idle is about the ITEM — when did it last move — and an item
 * selling steadily has a recent answer while still carrying units bought three
 * years ago behind the ones that keep turning over. Those units are the AS-2
 * paragraph 24 obsolescence the write-down action exists for, and until this
 * panel the CA had to decide the write-down with no data to go on.
 *
 * THIS SCREEN DECIDES NOTHING, and there are four things it would be easy to
 * decide here and wrong to:
 *
 *   WHICH BAND a unit falls in. The boundary — 30 days is the FIRST band, not
 *   the second — lives in `domain/reporting/stock_ageing.band_for_age` and in
 *   migration 408's CASE, pinned to each other by a parity test. A third copy
 *   in the browser is how the same figure comes to appear in two adjacent
 *   columns on two screens.
 *
 *   THE BAND ORDER. `bands` is rendered in the server's order because the keys
 *   do not sort into it: 'd0_30' comes AFTER 'd181_365' alphabetically.
 *
 *   HOW THE VALUE SPLITS. It is the item's own carrying amount pro-rated by
 *   quantity, not the cost of the units in the band, and it foots exactly.
 *   Re-deriving it here from a percentage would not.
 *
 *   WHAT A PROVISION SHOULD BE. Nothing multiplies a band by a rate. AS-2
 *   paragraph 21 makes net realisable value an estimate of selling price less
 *   the costs to complete and sell — a fact about the market no ledger holds —
 *   so the CA reads the quantities and uses the write-down action.
 */
import { useCallback, useEffect, useState } from "react";
import { Hourglass, Info } from "lucide-react";
import { api, type StockAgeing as Ageing } from "@/lib/api";
import { formatPaise } from "@/lib/services/formatting";
import { TableSkeleton } from "@/components/ui/skeleton";
import { objectWithLists } from "@/lib/api/shape";

/** The two oldest bands, which are what an obsolescence review is opened for.
 *  Presentational only — no figure is derived from this. */
const OLD_BANDS = new Set(["d181_365", "d365_plus"]);

function qty(v: string | undefined): string {
  // The server sends NUMERIC(10,3) as a string and it stays one: a quantity
  // turned into a float is how a register stops footing. Trailing zeros are
  // trimmed for reading and nothing is recomputed.
  const t = (v ?? "0").trim();
  return t.includes(".") ? t.replace(/\.?0+$/, "") || "0" : t;
}

export function StockAgeingPanel({ clientId, asOf }: { clientId: string; asOf: string }) {
  const [data, setData] = useState<Ageing | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    setError("");
    try {
      const res = await api.inventory.stockAgeing({ client_id: clientId, as_of: asOf });
      if (!res.success || !res.data) throw new Error(res.error || "failed");
      setData(objectWithLists<Ageing>(res.data, "bands", "items", "notes"));
    } catch {
      setData(null);
      setError("Couldn't load the stock ageing — the request failed or timed out.");
    } finally {
      setLoading(false);
    }
  }, [clientId, asOf]);

  useEffect(() => { load(); }, [load]);

  const oldValue = data
    ? data.bands.filter((b) => OLD_BANDS.has(b))
        .reduce((n, b) => n + (data.total_value_by_band[b] ?? 0), 0)
    : 0;

  return (
    <section className="bg-ps-surface border border-ps-border rounded-xl overflow-hidden">
      <button onClick={() => setOpen((v) => !v)}
        className="w-full px-5 py-3 flex items-center justify-between gap-3 bg-ps-bg border-b border-ps-border text-left hover:bg-ps-hover transition-colors">
        <span className="flex items-center gap-2 min-w-0">
          <Hourglass size={14} className="text-ps-label flex-shrink-0" />
          <span className="min-w-0">
            <span className="block font-semibold text-ps-ink text-sm">Stock ageing</span>
            <span className="block text-xs text-ps-label">
              How long the stock on hand has been held, first-in-first-out, as at {asOf}
            </span>
          </span>
        </span>
        <span className="flex items-center gap-3 flex-shrink-0">
          {data && oldValue > 0 && (
            /* THE HEADLINE IS THE OBSOLESCENCE FIGURE, because it is the one
               a CA opens this for. It is a sum of two bands the server sent,
               not a percentage applied to anything. */
            <span className="text-xs text-state-attention font-medium">
              {formatPaise(oldValue)} over 180 days
            </span>
          )}
          <span className="text-xs text-ps-label">{open ? "Hide" : "Show"}</span>
        </span>
      </button>

      {open && (
        <div className="p-5">
          {loading ? (
            <TableSkeleton rows={4} />
          ) : error ? (
            <div className="text-xs text-state-problem">{error}</div>
          ) : !data || data.items.length === 0 ? (
            <p className="text-xs text-ps-label">
              No stock movements on or before {asOf}, so there is nothing to age.
            </p>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-ps-label uppercase border-b border-ps-border">
                      <th className="text-left py-2 pr-3 font-medium">Item</th>
                      <th className="text-right py-2 px-2 font-medium">On hand</th>
                      {data.bands.map((b) => (
                        <th key={b} className={`text-right py-2 px-2 font-medium whitespace-nowrap ${
                          OLD_BANDS.has(b) ? "text-state-attention" : ""}`}>
                          {data.band_labels[b] ?? b}
                        </th>
                      ))}
                      <th className="text-right py-2 pl-2 font-medium">Value</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ps-border">
                    {data.items.map((it) => (
                      <tr key={it.service_catalogue_id} className="hover:bg-ps-bg">
                        <td className="py-2 pr-3 text-ps-ink">
                          {it.name}
                          {it.nothing_on_hand && (
                            /* AN EMPTY ROW OF BANDS MEANS SOMETHING, and it is
                               not "no old stock". Nil or oversold: there are no
                               units to age, and six zeroes would read as a
                               clean bill of health. */
                            <span className="block text-ps-hint">
                              Nothing on hand to age
                            </span>
                          )}
                          {!it.nothing_on_hand && it.oldest_holding_date && (
                            <span className="block text-ps-hint">
                              Oldest unit held since {it.oldest_holding_date}
                            </span>
                          )}
                        </td>
                        <td className="py-2 px-2 text-right font-mono text-ps-body tabular-nums">
                          {qty(it.qty_units)} {it.unit}
                        </td>
                        {data.bands.map((b) => {
                          const q = qty(it.band_qty[b]);
                          return (
                            <td key={b} className={`py-2 px-2 text-right font-mono tabular-nums ${
                              q === "0" ? "text-ps-hint"
                                : OLD_BANDS.has(b) ? "text-state-attention" : "text-ps-body"}`}>
                              {q}
                            </td>
                          );
                        })}
                        <td className="py-2 pl-2 text-right font-mono text-ps-ink tabular-nums">
                          {formatPaise(it.value_paise)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="border-t border-ps-border-strong font-medium">
                      <td className="py-2 pr-3 text-ps-ink">Total</td>
                      <td />
                      {data.bands.map((b) => (
                        <td key={b} className="py-2 px-2 text-right font-mono text-ps-ink tabular-nums">
                          {formatPaise(data.total_value_by_band[b] ?? 0)}
                        </td>
                      ))}
                      <td className="py-2 pl-2 text-right font-mono text-ps-ink tabular-nums">
                        {formatPaise(data.total_value_paise)}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>

              {/* THE CAVEATS ARE THE SERVER'S WORDS. Four sentences saying the
                  bands are a convention, that ageing is FIFO whatever the cost
                  formula is, that the value is pro-rated and that no provision
                  is computed — each of which a reader would otherwise assume
                  the other way. */}
              <div className="mt-4 pt-3 border-t border-ps-border space-y-1.5">
                {data.notes.map((n, i) => (
                  <p key={i} className="text-xs text-ps-label flex gap-2">
                    <Info size={12} className="mt-0.5 flex-shrink-0 text-ps-hint" />
                    <span>{n}</span>
                  </p>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
