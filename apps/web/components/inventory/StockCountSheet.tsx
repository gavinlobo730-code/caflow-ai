"use client";

/**
 * The physical stock count — one sheet, not a hundred adjustments (INV-08).
 *
 * WHAT WAS WRONG
 *   Stock adjustment was one item per API call and one item per modal.
 *   Stock-taking at 31 March produces a sheet with a hundred variances, so the
 *   CA opened each item's ledger, retyped the quantity, chose a reason and
 *   confirmed the s.17(5)(h) checkbox — a hundred times — and the hundred
 *   journals that came out had no common reference tying them to the count.
 *
 * THIS SCREEN COMPUTES NOTHING (CLAUDE.md). The variance, its direction, its
 * reason, whether a line may post and why not are all
 * domain/inventory/count_session.py's answers, recomputed on the server
 * against the position AS AT THE COUNT DATE every time the sheet is read —
 * because stock moves between opening a sheet and keying it in, and the count
 * is a fact about the count date.
 */
import { useCallback, useEffect, useState } from "react";
import { X, ClipboardCheck, AlertTriangle, Check } from "lucide-react";
import { api, type StockCountSheet as Sheet, type StockCountLine,
         type StockCountPostResult } from "@/lib/api";
import { parseQuantity } from "@/lib/money/rupeeInput";
import { Callout } from "@/components/ui/callout";
import { objectWithLists } from "@/lib/api/shape";

export function StockCountSheetPanel({
  clientId, sessionId, onClose, onPosted,
}: {
  clientId: string;
  sessionId: string;
  onClose: () => void;
  onPosted: () => void;
}) {
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<StockCountPostResult | null>(null);
  // What the CA has typed but not yet saved, keyed by item. Held as the TEXT
  // they typed so `parseQuantity` sees it exactly once, at save.
  const [typed, setTyped] = useState<Record<string, string>>({});
  const [itc, setItc] = useState<Record<string, "" | "yes" | "no">>({});

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const res = await api.inventory.countSession(sessionId);
      if (!res.success || !res.data) throw new Error(res.error ?? "Couldn't load the count sheet.");
      setSheet(objectWithLists<Sheet>(res.data, "gaps", "lines"));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load the count sheet.");
    } finally {
      setBusy(false);
    }
  }, [sessionId]);

  useEffect(() => { load(); }, [load]);

  async function save() {
    if (!sheet) return;
    setBusy(true);
    try {
      const entries = sheet.lines.flatMap((l) => {
        const t = typed[l.service_catalogue_id];
        const decision = itc[l.service_catalogue_id];
        if (t === undefined && decision === undefined) return [];
        const entry: Record<string, unknown> = { service_catalogue_id: l.service_catalogue_id };
        if (t !== undefined) {
          // Blank is NOT COUNTED, which is not zero — the server refuses a
          // blank line and a zero count writes the item's stock off.
          entry.counted_qty_units = t.trim() === "" ? null : parseQuantity(t);
        }
        if (decision !== undefined) {
          entry.reverse_itc = decision === "" ? null : decision === "yes";
        }
        return [entry];
      });
      if (!entries.length) { setBusy(false); return; }
      const res = await api.inventory.saveCountSession(sessionId, { client_id: clientId, entries });
      if (!res.success || !res.data) throw new Error(res.error ?? "Couldn't save the sheet.");
      setSheet(objectWithLists<Sheet>(res.data, "gaps", "lines"));
      setTyped({});
      setItc({});
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the sheet.");
    } finally {
      setBusy(false);
    }
  }

  async function post() {
    setBusy(true);
    try {
      const res = await api.inventory.postCountSession(sessionId);
      if (!res.success || !res.data) throw new Error(res.error ?? "Couldn't post the count.");
      setResult(objectWithLists<StockCountPostResult>(res.data, "failed"));
      await load();
      onPosted();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't post the count.");
    } finally {
      setBusy(false);
    }
  }

  const open = sheet?.session.status === "open";

  return (
    <div className="fixed inset-0 bg-brand-dark/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-5xl max-h-[92vh] overflow-y-auto">
        <div className="sticky top-0 bg-white flex items-center justify-between px-5 py-4 border-b">
          <div className="flex items-center gap-2">
            <ClipboardCheck size={16} className="text-emerald-600" />
            <div>
              <p className="text-sm font-semibold text-ps-ink">
                Physical stock count — {sheet?.session.reference_no ?? ""}
              </p>
              <p className="text-2xs text-ps-hint">
                Counted as at {sheet?.session.count_date ?? "—"} · {sheet?.session.status ?? ""}
              </p>
            </div>
          </div>
          <button onClick={onClose} aria-label="Close"><X size={16} className="text-ps-hint" /></button>
        </div>

        <div className="px-5 py-4 space-y-3">
          {error && <Callout tone="problem">{error}</Callout>}

          {result && (
            <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2 text-xs text-emerald-900 space-y-1">
              <p className="font-semibold">
                {result.posted_count} adjustment{result.posted_count !== 1 ? "s" : ""} posted
                under {result.reference_no}.
              </p>
              {/* NAMED, never swallowed: a line that could not post leaves the
                  books disagreeing with the count. */}
              {result.failed_count > 0 && (
                <div className="text-red-800">
                  <p className="font-semibold">{result.failed_count} could not post:</p>
                  {result.failed.map((f, i) => <p key={i}>{f.item} — {f.why}</p>)}
                </div>
              )}
            </div>
          )}

          {sheet && (
            <div className="grid grid-cols-4 gap-3">
              {[["Counted", sheet.counted_count], ["Variances", sheet.variance_count],
                ["Will post", sheet.postable_count], ["Needs you", sheet.blocked_count]]
                .map(([label, n]) => (
                <div key={label as string} className="bg-ps-bg rounded-lg px-3 py-2">
                  <p className="text-2xs text-ps-label">{label}</p>
                  <p className="text-sm font-semibold text-ps-ink">{n}</p>
                </div>
              ))}
            </div>
          )}

          {sheet?.gaps?.map((g, i) => (
            <p key={i} className="text-2xs text-amber-900 flex gap-1.5">
              <AlertTriangle size={12} className="shrink-0 mt-0.5" />{g}
            </p>
          ))}

          <div className="overflow-x-auto border border-ps-muted rounded-lg">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-ps-bg text-ps-label">
                  <th className="px-3 py-2 text-left font-semibold">Item</th>
                  <th className="px-3 py-2 text-right font-semibold">Books</th>
                  <th className="px-3 py-2 text-right font-semibold">Counted</th>
                  <th className="px-3 py-2 text-right font-semibold">Variance</th>
                  <th className="px-3 py-2 text-left font-semibold">s.17(5)(h)</th>
                  <th className="px-3 py-2 text-left font-semibold">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ps-bg">
                {(sheet?.lines ?? []).map((l: StockCountLine) => (
                  <tr key={l.service_catalogue_id} className="align-top">
                    <td className="px-3 py-2">
                      <p className="font-medium text-ps-ink">{l.item_name}</p>
                      {l.caveats.map((c, i) => (
                        <p key={i} className="text-3xs text-ps-label italic">{c}</p>
                      ))}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-ps-label">
                      {l.current_qty_units}{l.unit ? ` ${l.unit}` : ""}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {open ? (
                        <input
                          className="w-24 border border-ps-border rounded px-2 py-1 text-right font-mono"
                          aria-label={`Counted quantity for ${l.item_name}`}
                          value={typed[l.service_catalogue_id] ?? (l.counted_qty_units ?? "")}
                          onChange={(e) => setTyped((t) => ({ ...t, [l.service_catalogue_id]: e.target.value }))}
                          placeholder="—" />
                      ) : (
                        <span className="font-mono">{l.counted_qty_units ?? "—"}</span>
                      )}
                    </td>
                    <td className={`px-3 py-2 text-right font-mono ${
                      l.direction === "decrease" ? "text-state-problem"
                        : l.direction === "increase" ? "text-emerald-700" : "text-ps-hint"}`}>
                      {l.variance_qty_units ?? "—"}
                    </td>
                    <td className="px-3 py-2">
                      {/* Asked only where the section reaches: a shortage. A
                          surplus is stock FOUND, so there is no credit to
                          reverse, and the server refuses one that claims
                          otherwise. */}
                      {l.direction === "decrease" && open ? (
                        <select
                          className="border border-ps-border rounded px-2 py-1"
                          aria-label={`ITC reversal for ${l.item_name}`}
                          value={itc[l.service_catalogue_id]
                                 ?? (l.reverse_itc === null ? "" : l.reverse_itc ? "yes" : "no")}
                          onChange={(e) => setItc((m) => ({
                            ...m, [l.service_catalogue_id]: e.target.value as "" | "yes" | "no" }))}>
                          <option value="">Not decided</option>
                          <option value="yes">Reverse the credit</option>
                          <option value="no">No reversal</option>
                        </select>
                      ) : (
                        <span className="text-ps-hint">
                          {l.direction === "decrease"
                            ? (l.reverse_itc === null ? "—" : l.reverse_itc ? "Reversed" : "No reversal")
                            : "—"}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {l.will_post ? (
                        <span className="inline-flex items-center gap-1 text-emerald-700">
                          <Check size={11} /> will post
                        </span>
                      ) : l.gaps.length ? (
                        l.gaps.map((g, i) => (
                          <p key={i} className="text-amber-900 flex gap-1">
                            <AlertTriangle size={11} className="shrink-0 mt-0.5" />{g}
                          </p>
                        ))
                      ) : (
                        <span className="text-ps-hint">no variance</span>
                      )}
                    </td>
                  </tr>
                ))}
                {!sheet?.lines?.length && (
                  <tr><td colSpan={6} className="px-3 py-8 text-center text-ps-hint">
                    No stock-tracked products on this sheet.
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>

          {open && (
            <div className="flex items-center justify-between gap-3 border-t pt-3">
              <p className="text-2xs text-ps-label">
                Posting writes one adjustment per varying line, all under{" "}
                <span className="font-mono">{sheet?.session.reference_no}</span>, dated{" "}
                {sheet?.session.count_date}. A line that needs you is left alone.
              </p>
              <div className="flex gap-2">
                <button onClick={save} disabled={busy}
                        className="px-3 py-1.5 text-xs border border-ps-border rounded-lg hover:bg-ps-bg">
                  {busy ? "Saving…" : "Save counts"}
                </button>
                <button onClick={post} disabled={busy || !sheet?.postable_count}
                        className="px-3 py-1.5 text-xs bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-40">
                  Post {sheet?.postable_count ?? 0} adjustment{sheet?.postable_count === 1 ? "" : "s"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
