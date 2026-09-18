"use client";

/**
 * What is at or below its reorder level, grouped by item group (INV-03).
 *
 * `service_catalogue.category` has been a free-text grouping since migration
 * 180 and nothing ever grouped by it, and there was no reorder level at all —
 * so the one question a stock master answers between counts, *what do I need
 * to buy*, was answered by reading the register item by item.
 *
 * THIS SCREEN DECIDES NOTHING, and three things would be easy to decide here:
 *
 *   WHETHER AN ITEM IS SHORT. The server compares the LEDGER's on-hand figure
 *   (`stock_position_as_at`) against the recorded level, at or below. Doing it
 *   in the browser would read the cached `stock_qty_units` off the register
 *   row that is already on screen — and migration 188 documents that column as
 *   a cache, so a purchasing prompt off a drifted one says there is stock
 *   there is not.
 *
 *   WHAT AN ABSENT LEVEL MEANS. It is its OWN state, never rendered as zero.
 *   Zero is a real answer — "tell me when it runs out" — so an item with no
 *   level is listed with the server's sentence rather than parked in the
 *   comfortable bucket.
 *
 *   WHICH GROUP AN ITEM IS IN. Two spellings of one group fold on the server;
 *   an unrecorded group is its own row and is never dropped, so a client who
 *   half-filled the column gets the half they can act on.
 *
 * Nothing statutory turns on any of it: this is a prompt, and it posts
 * nothing and moves no stock.
 */
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, HelpCircle, PackageSearch } from "lucide-react";
import { api, type ReorderLine, type ReorderReport } from "@/lib/api";
import { TableSkeleton } from "@/components/ui/skeleton";

function StateCell({ line }: { line: ReorderLine }) {
  if (line.state === "not_set") {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-ps-hint">
        <HelpCircle size={11} /> No level recorded
      </span>
    );
  }
  if (line.state === "below" || line.state === "at") {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-state-attention">
        <AlertTriangle size={11} /> {line.state === "at" ? "At level" : "Below level"}
      </span>
    );
  }
  return <span className="text-xs text-ps-body">Above level</span>;
}

export function ReorderPanel({ clientId, asOf }: { clientId: string; asOf?: string }) {
  const [report, setReport] = useState<ReorderReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    setFailed(false);
    try {
      const params: Record<string, string> = { client_id: clientId };
      if (asOf) params.as_of = asOf;
      const r = await api.inventory.reorder(params);
      setReport(r.success ? r.data : null);
      if (!r.success) setFailed(true);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId, asOf]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <TableSkeleton rows={4} />;
  if (failed) {
    return (
      <p className="text-xs text-state-problem">
        Couldn&apos;t load the reorder report — the request failed or timed out.
      </p>
    );
  }
  if (!report || report.items_considered === 0) return null;

  return (
    <section className="bg-ps-surface border border-ps-border rounded-xl overflow-hidden">
      <div className="px-5 py-3 bg-ps-bg border-b border-ps-border flex items-center gap-2">
        <PackageSearch size={14} className="text-ps-label" />
        <div className="min-w-0">
          <h3 className="font-semibold text-ps-ink text-sm">Reorder</h3>
          <p className="text-xs text-ps-label">
            {report.to_reorder} at or below level
            {report.no_level_recorded > 0
              && <> · {report.no_level_recorded} with no level recorded</>}
            {" "}· {report.items_considered} goods
          </p>
        </div>
      </div>

      {report.groups.map((g) => (
        <div key={g.group}>
          <div className="px-5 py-2 bg-ps-bg/60 border-b border-ps-border">
            <span className="text-xs font-medium text-ps-label">{g.group}</span>
            {g.below_count > 0 && (
              <span className="text-xs text-ps-hint"> · {g.below_count} to reorder</span>
            )}
          </div>
          <table className="w-full text-sm">
            <tbody>
              {g.lines.map((ln) => (
                <tr key={ln.service_catalogue_id}
                    className="border-b border-ps-border last:border-0">
                  <td className="px-5 py-2 text-ps-ink">{ln.name}</td>
                  <td className="px-5 py-2 text-right font-mono tabular-nums text-ps-body whitespace-nowrap">
                    {ln.on_hand_units}{ln.unit ? ` ${ln.unit}` : ""}
                  </td>
                  <td className="px-5 py-2 text-right font-mono tabular-nums text-ps-label whitespace-nowrap">
                    {/* An absent level is a DASH, never a nought — zero is a
                        real recorded answer and the two must not look alike. */}
                    {ln.reorder_level_units === null ? "—" : ln.reorder_level_units}
                  </td>
                  <td className="px-5 py-2 text-right font-mono tabular-nums text-ps-body whitespace-nowrap">
                    {ln.state === "below" ? `short ${ln.shortfall_units}` : ""}
                  </td>
                  <td className="px-5 py-2"><StateCell line={ln} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}

      {report.no_level_recorded > 0 && (
        <div className="px-5 py-3 border-t border-ps-border bg-ps-bg">
          <p className="text-xs text-ps-hint">{report.note_when_no_level}</p>
        </div>
      )}
    </section>
  );
}
